"""Tableaux de bord Grafana : structure et exécution des requêtes sous `p5test_grafana`."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from grafana_sql import (
    DASHBOARD_DIR,
    iter_panel_queries,
    iter_panels,
    load_dashboards,
    render_macros,
)
from sqlalchemy import select, text
from synth import EXAMPLE_FEATURES, add_year

from app.db.models import ApiRequest, BuildingActual, MlModel, Prediction, User
from app.db.registry import CATBOOST_NAME, KUMO_NAME

DASHBOARD_ROOT = DASHBOARD_DIR.parents[2]
DATASOURCE = {"type": "grafana-postgresql-datasource", "uid": "p5-postgres"}
FED_PANELS = {
    "Requêtes",
    "Taux 5xx",
    "Taux 4xx",
    "Latence p95",
    "Utilisateurs authentifiés",
    "Requêtes par minute",
    "Latence par route",
    "Par route",
    "20 dernières erreurs",
    "Prédictions par modèle",
    "Par origine",
    "Prédictions par heure",
    "Distribution des consommations prédites",
    "Erreur réelle par année",
    "Prédit vs réel",
    "CatBoost vs Kumo",
}


def _window():
    now = datetime.now(UTC)
    return now - timedelta(days=1), now + timedelta(hours=1)


def _all_queries():
    return [q for d in load_dashboards().values() for q in iter_panel_queries(d)]


def _panel_rows(conn, title):
    start, end = _window()
    (sql,) = [q for t, q in _all_queries() if t == title]
    return conn.execute(text(render_macros(sql, start, end))).all()


def test_render_macros():
    start = datetime(2026, 10, 1, tzinfo=UTC)
    end = datetime(2026, 10, 2, tzinfo=UTC)
    out = render_macros(
        "WHERE $__timeFilter(created_at) GROUP BY $__timeGroupAlias(created_at, 1m)",
        start,
        end,
    )
    assert (
        "created_at BETWEEN '2026-10-01T00:00:00+00:00' AND '2026-10-02T00:00:00+00:00'"
        in out
    )
    assert (
        'to_timestamp(floor(extract(epoch FROM created_at) / 60) * 60) AS "time"' in out
    )
    assert "$__" not in out


@pytest.mark.parametrize("unit,seconds", [("5m", 300), ("1h", 3600), ("1d", 86400)])
def test_render_macros_intervals(unit, seconds):
    out = render_macros(f"$__timeGroupAlias(t, {unit})", _window()[0], _window()[1])
    assert f"/ {seconds}) * {seconds})" in out


@pytest.mark.parametrize(
    "sql", ["$__timeFrom()", "WHERE x = $route", "$__unixEpochFilter(t)"]
)
def test_render_macros_rejects_unknown(sql):
    with pytest.raises(ValueError, match="non prise en charge"):
        render_macros(sql, *_window())


def test_dashboards_structure():
    dashboards = load_dashboards()
    assert {d["uid"] for d in dashboards.values()} == {"p5-api", "p5-model"}
    assert len({d["uid"] for d in dashboards.values()}) == len(dashboards)
    for name, dash in dashboards.items():
        assert dash["title"], name
        assert dash["time"] == {"from": "now-24h", "to": "now"}, name
        assert dash["refresh"] == "30s", name
        for panel in iter_panels(dash):
            assert panel["datasource"] == DATASOURCE, (name, panel["title"])
            assert panel["targets"], (name, panel["title"])
            for target in panel["targets"]:
                assert target["rawQuery"] is True
                assert target["format"] in {"table", "time_series"}
                assert target["rawSql"].strip()


GRAFANA_VERSION = "12.4.3"  # image du service grafana (docker-compose.yml)


def test_panels_pinned_to_grafana_version():
    """Sans pluginVersion, Grafana migre le panneau au chargement : la migration
    du xychart plante sur des options partielles (tableau « Modèle » vide)."""
    compose = (DASHBOARD_ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    assert f"grafana/grafana-oss:{GRAFANA_VERSION}" in compose
    for name, dash in load_dashboards().items():
        for panel in iter_panels(dash):
            assert panel.get("pluginVersion") == GRAFANA_VERSION, (name, panel["title"])
            if panel["type"] == "xychart":
                assert panel["options"]["mapping"] == "manual"
                (series,) = panel["options"]["series"]
                assert {"x", "y"} <= series.keys()


@pytest.fixture
def monitoring_data(grafana_conn):
    """Trafic API de la dernière heure (sous le rôle propriétaire)."""
    now = datetime.now(UTC)
    calls = (
        [("/model/predict", 200, 15)] * 6
        + [("/buildings/28", 200, 40), ("/model/list", 401, 3)]
        + [("/buildings/999", 404, 6), ("/model/predict/compare", 503, 15600)]
    )
    with grafana_conn.owner() as s:
        user_id = s.scalar(select(User.id).where(User.username == "johndoe"))
        for i, (path, status, ms) in enumerate(calls):
            s.add(
                ApiRequest(
                    request_id=uuid.uuid4(),
                    user_id=None if status == 401 else user_id,
                    method="POST" if path.startswith("/model/predict") else "GET",
                    path=path,
                    status_code=status,
                    duration_ms=ms,
                    created_at=now - timedelta(minutes=i),
                )
            )
        # Requête en cours (ou plantée avant la finalisation) : ni statut ni durée.
        s.add(
            ApiRequest(
                request_id=uuid.uuid4(), method="GET", path="/buildings", created_at=now
            )
        )
        s.flush()
        api_ids = s.scalars(
            select(ApiRequest.id).where(ApiRequest.status_code == 200)
        ).all()
        models = dict(s.execute(select(MlModel.name, MlModel.id)).all())
        catboost, kumo = models[CATBOOST_NAME], models[KUMO_NAME]

        def predict(model_id, energy, api_request_id=None, year_id=None):
            s.add(
                Prediction(
                    model_id=model_id,
                    api_request_id=api_request_id,
                    building_year_id=year_id,
                    input_features=EXAMPLE_FEATURES,
                    energy_use_kbtu=energy,
                    ghg_emissions_tco2e=energy / 1000,
                )
            )

        years = [add_year(s, building_id, 2019) for building_id in (901, 902)]
        for year, actual in zip(years, (2000.0, 4000.0), strict=True):
            s.add(
                BuildingActual(
                    building_year_id=year.id,
                    site_energy_use_kbtu=actual,
                    total_ghg_emissions_tco2e=actual / 1000,
                )
            )
            predict(catboost, actual * 1.1, year_id=year.id)  # lot : 10 % d'erreur
        for api_id in api_ids[:3]:
            predict(catboost, 3000.0, api_id, years[0].id)  # par identifiant
        predict(catboost, 2500.0, api_ids[3])  # saisie libre
        predict(catboost, 1000.0, api_ids[4], years[1].id)  # /compare
        predict(kumo, 1200.0, api_ids[4], years[1].id)
        s.commit()
    return {"finished": len(calls)}


def test_panel_queries_run_on_empty_database(grafana_conn):
    conn = grafana_conn.as_grafana()
    for title, sql in _all_queries():
        conn.execute(text(render_macros(sql, *_window()))).all()


def test_panel_queries_run_under_grafana_role(grafana_conn, monitoring_data):
    conn = grafana_conn.as_grafana()
    fed = set()
    for title, sql in _all_queries():
        rows = conn.execute(text(render_macros(sql, *_window()))).all()
        if rows and any(v is not None for v in rows[0]):
            fed.add(title)
    assert FED_PANELS <= fed, FED_PANELS - fed


def test_api_error_rate_ignores_unfinished_requests(grafana_conn, monitoring_data):
    conn = grafana_conn.as_grafana()
    ((rate,),) = _panel_rows(conn, "Taux 5xx")
    assert float(rate) == pytest.approx(10.0)


def test_routes_grouped_by_id(grafana_conn, monitoring_data):
    conn = grafana_conn.as_grafana()
    routes = {row[0] for row in _panel_rows(conn, "Par route")}
    assert "/buildings/{id}" in routes
    assert "/buildings/28" not in routes


def test_model_origin_breakdown(grafana_conn, monitoring_data):
    rows = _panel_rows(grafana_conn.as_grafana(), "Par origine")
    assert {origin: n for origin, n in rows} == {
        "Par identifiant": 5,
        "Saisie libre": 1,
        "Lot": 2,
    }


def test_catboost_vs_kumo_median_gap(grafana_conn, monitoring_data):
    ((gap,),) = _panel_rows(grafana_conn.as_grafana(), "CatBoost vs Kumo")
    assert float(gap) == pytest.approx(20.0)


def test_catboost_vs_kumo_empty_without_compare(grafana_conn):
    rows = _panel_rows(grafana_conn.as_grafana(), "CatBoost vs Kumo")
    assert rows in ([], [(None,)])


def test_real_error_by_year(grafana_conn, monitoring_data):
    rows = _panel_rows(grafana_conn.as_grafana(), "Erreur réelle par année")
    assert [(r[0], r[1], r[-1]) for r in rows] == [(2019, CATBOOST_NAME, 2)]
    assert float(rows[0][2]) == pytest.approx(10.0)  # MedAPE énergie (%)
