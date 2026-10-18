"""Routes de prédiction : écriture input → prédiction → trace (spec §4.3)."""

import json

import pytest
from sqlalchemy import func, select, update
from synth import EXAMPLE_FEATURES, add_building, add_year

from app.core import kumo_service, model_service
from app.db.models import ApiRequest, MlModel, Prediction, User
from app.db.registry import CATBOOST_NAME

pytestmark = pytest.mark.db

MANUAL_PAYLOAD = {
    "BuildingType": "Commercial",
    "PrimaryPropertyType": "Office",
    "Neighborhood": "Ballard",
    "Latitude": 47.62,
    "Longitude": -122.35,
    "YearBuilt": 1990,
    "NumberofBuildings": 1,
    "NumberofFloors": 4,
    "PropertyGFAParking": 5000,
    "PropertyGFABuilding": 15000,
    "LargestPropertyUseType": "Office",
    "SecondLargestPropertyUseType": "Retail",
    "SecondLargestPropertyUseTypeGFA": 3000,
    "ThirdLargestPropertyUseType": "Parking",
    "ThirdLargestPropertyUseTypeGFA": 2000,
    "Has_NaturalGas": True,
    "Has_Steam": False,
}


@pytest.fixture
def buildings(db):
    """Bâtiment 1 (2016, 2018) dans le périmètre ; bâtiment 2 résidentiel (sans année)."""
    with db() as s:
        y16 = add_year(s, 1, 2016)
        y18 = add_year(s, 1, 2018)
        add_building(s, 2)
        s.commit()
        return {"2016": y16.id, "2018": y18.id}


@pytest.fixture
def seen_buildings(db):
    """Bâtiments 10 (train) et 11 (test) : vus par l'entraînement."""
    with db() as s:
        add_year(s, 10, 2018, split="train")
        add_year(s, 11, 2018, split="test")
        s.commit()


def _prediction(db, prediction_id) -> Prediction:
    with db() as s:
        return s.get(Prediction, prediction_id)


def test_predict_by_id_uses_latest_year(
    client, db, auth_headers, demo_models, buildings
):
    r = client.post("/model/predict", json={"building_id": 1}, headers=auth_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["energy_use_kbtu"] > 0
    assert body["request_id"] == r.headers["x-request-id"]
    pred = _prediction(db, body["prediction_id"])
    assert pred.building_year_id == buildings["2018"]
    assert pred.api_request_id is not None
    assert (
        pred.input_features["PropertyGFABuilding(s)"]
        == EXAMPLE_FEATURES["PropertyGFABuilding(s)"]
    )


def test_predict_trace_carries_authenticated_user(
    client, db, auth_headers, demo_models, buildings
):
    r = client.post("/model/predict", json={"building_id": 1}, headers=auth_headers)
    assert r.status_code == 200, r.text
    with db() as s:
        user = s.scalar(select(User).where(User.username == "johndoe"))
        row = s.scalar(
            select(ApiRequest).where(ApiRequest.request_id == r.headers["x-request-id"])
        )
        assert row.path == "/model/predict"
        assert row.user_id == user.id


def test_predict_by_id_and_year(client, db, auth_headers, demo_models, buildings):
    r = client.post(
        "/model/predict",
        json={"building_id": 1, "data_year": 2016},
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text
    pred = _prediction(db, r.json()["prediction_id"])
    assert pred.building_year_id == buildings["2016"]


def test_unknown_building_404(client, auth_headers, buildings):
    r = client.post("/model/predict", json={"building_id": 999}, headers=auth_headers)
    assert r.status_code == 404


def test_missing_year_404(client, auth_headers, buildings):
    r = client.post(
        "/model/predict",
        json={"building_id": 1, "data_year": 2017},
        headers=auth_headers,
    )
    assert r.status_code == 404


def test_residential_building_422(client, auth_headers, buildings):
    r = client.post("/model/predict", json={"building_id": 2}, headers=auth_headers)
    assert r.status_code == 422
    assert "hors périmètre" in r.json()["detail"]


def test_predict_rejects_extra_field(client, auth_headers, buildings):
    r = client.post(
        "/model/predict", json={"building_id": 1, "x": 1}, headers=auth_headers
    )
    assert r.status_code == 422


def test_predict_requires_token(client, buildings):
    assert client.post("/model/predict", json={"building_id": 1}).status_code == 401


def test_manual_features_prediction(client, db, auth_headers, demo_models):
    r = client.post(
        "/model/predict/features", json=MANUAL_PAYLOAD, headers=auth_headers
    )
    assert r.status_code == 200, r.text
    pred = _prediction(db, r.json()["prediction_id"])
    assert pred.building_year_id is None
    assert pred.api_request_id is not None
    assert pred.input_features["PropertyGFABuilding(s)"] == 15000


def test_manual_features_reject_extra_field(client, auth_headers):
    bad = dict(MANUAL_PAYLOAD, extra_field="nope")
    r = client.post("/model/predict/features", json=bad, headers=auth_headers)
    assert r.status_code == 422


def test_compare_two_predictions_share_request_and_year(
    client, db, auth_headers, demo_models, buildings
):
    r = client.post(
        "/model/predict/compare", json={"building_id": 1}, headers=auth_headers
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["kumo_prediction"]["model_name"] == "kumo-tabular-zero-shot"
    cb = _prediction(db, body["catboost_prediction"]["prediction_id"])
    km = _prediction(db, body["kumo_prediction"]["prediction_id"])
    assert cb.api_request_id == km.api_request_id
    assert cb.building_year_id == km.building_year_id == buildings["2018"]
    assert cb.model_id != km.model_id


def test_compare_building_with_null_secondary_gfa(
    client, db, auth_headers, demo_models
):
    """Bâtiment sans 2e/3e usage : Kumo doit répondre comme CatBoost (#62)."""
    with db() as s:
        year = add_year(s, 5, 2019)
        year.second_largest_property_use_type_gfa = None
        year.third_largest_property_use_type_gfa = None
        s.commit()
    r = client.post(
        "/model/predict/compare", json={"building_id": 5}, headers=auth_headers
    )
    assert r.status_code == 200, r.text
    assert r.json()["kumo_prediction"]["energy_use_kbtu"] > 0


def test_model_failure_leaves_no_prediction_but_traces_request(
    client, db, auth_headers, buildings, monkeypatch
):
    def boom(df):
        raise FileNotFoundError("modèle absent")

    monkeypatch.setattr(model_service, "predict_frame", boom)
    r = client.post("/model/predict", json={"building_id": 1}, headers=auth_headers)
    assert r.status_code == 503
    with db() as s:
        assert s.scalar(select(func.count()).select_from(Prediction)) == 0
        row = s.scalar(
            select(ApiRequest).where(ApiRequest.request_id == r.headers["x-request-id"])
        )
        assert row.status_code == 503
        assert row.request_body == {"building_id": 1}


def test_no_active_model_503(client, db, auth_headers, demo_models, buildings):
    with db() as s:
        s.execute(
            update(MlModel).where(MlModel.name == CATBOOST_NAME).values(is_active=False)
        )
        s.commit()
    r = client.post("/model/predict", json={"building_id": 1}, headers=auth_headers)
    assert r.status_code == 503
    assert "Aucun modèle actif" in r.json()["detail"]


def test_model_list_reads_registry(client, auth_headers):
    r = client.get("/model/list", headers=auth_headers)
    assert r.status_code == 200
    names = {m["name"]: m for m in r.json()}
    assert names[CATBOOST_NAME]["version"] == "baseline"
    assert names[CATBOOST_NAME]["is_active"] is True
    assert "kumo-tabular-zero-shot" in names


def test_metrics_with_token(client, auth_headers, demo_models):
    r = client.get("/model/metrics", headers=auth_headers)
    assert r.status_code == 200, r.text
    assert r.json()["targets"]["energy"]["unit"] == "kBtu/an"


def test_metrics_missing_file_message_in_french(
    client, auth_headers, tmp_path, monkeypatch
):
    from app.core import metrics_service

    monkeypatch.setattr(metrics_service, "METRICS_PATH", str(tmp_path / "absent.json"))
    monkeypatch.setattr(metrics_service, "_metrics", None)
    r = client.get("/model/metrics", headers=auth_headers)
    assert r.status_code == 404
    assert "introuvable" in r.json()["detail"]


@pytest.fixture
def no_trace(monkeypatch):
    """Simule un middleware qui laisse passer la requête sans trace."""
    from app.middleware import trace

    def fail(*args, **kwargs):
        from sqlalchemy.exc import DataError

        raise DataError("insert", {}, Exception("données invalides"))

    monkeypatch.setattr(trace, "_insert_request", fail)


@pytest.mark.parametrize(
    ("route", "payload"),
    [
        ("/model/predict", {"building_id": 1}),
        ("/model/predict/compare", {"building_id": 1}),
        ("/model/predict/features", MANUAL_PAYLOAD),
    ],
)
def test_untraced_request_refuses_prediction(
    client, db, auth_headers, demo_models, buildings, no_trace, route, payload
):
    with db() as s:
        before = s.scalar(select(func.count()).select_from(Prediction))
    r = client.post(route, json=payload, headers=auth_headers)
    assert r.status_code == 503
    assert r.json()["detail"] == "Traçabilité indisponible, prédiction refusée"
    with db() as s:
        assert s.scalar(select(func.count()).select_from(Prediction)) == before


def test_model_unexpected_error_503(client, db, auth_headers, buildings, monkeypatch):
    def boom(df):
        raise RuntimeError("secret /chemin/interne")

    monkeypatch.setattr(model_service, "predict_frame", boom)
    r = client.post("/model/predict", json={"building_id": 1}, headers=auth_headers)
    assert r.status_code == 503
    assert r.json()["detail"] == "Modèle CatBoost indisponible"
    with db() as s:
        assert s.scalar(select(func.count()).select_from(Prediction)) == 0


def test_compare_kumo_failure_503_keeps_catboost(
    client, db, auth_headers, demo_models, buildings, monkeypatch
):
    def boom(X, target):
        raise RuntimeError("kumo hors service")

    monkeypatch.setattr(kumo_service, "predict_batch", boom)
    r = client.post(
        "/model/predict/compare", json={"building_id": 1}, headers=auth_headers
    )
    assert r.status_code == 503
    assert r.json()["detail"] == "Modèle Kumo-Tabular indisponible"
    with db() as s:
        assert s.scalar(select(func.count()).select_from(Prediction)) == 1


def test_predict_database_error_returns_503(
    client, auth_headers, demo_models, buildings, monkeypatch
):
    """Erreur SQL pendant le modèle : relayée au handler « base indisponible »."""
    from sqlalchemy.exc import OperationalError

    from app.core import prediction_service

    def db_down(*args, **kwargs):
        raise OperationalError("INSERT", {}, Exception("connexion perdue"))

    monkeypatch.setattr(prediction_service, "run_model", db_down)
    r = client.post("/model/predict", json={"building_id": 1}, headers=auth_headers)
    assert r.status_code == 503
    assert r.json() == {"detail": "Base de données indisponible"}


def test_building_without_year_rows_422(client, db, auth_headers, buildings):
    with db() as s:
        add_building(s, 3)
        s.commit()
    r = client.post(
        "/model/predict",
        json={"building_id": 3, "data_year": 2018},
        headers=auth_headers,
    )
    assert r.status_code == 422
    assert "hors périmètre" in r.json()["detail"]


@pytest.mark.parametrize(
    "override",
    [
        {"BuildingType": "x" * 65},
        {"Neighborhood": "y" * 65},
        {"YearBuilt": 40000},
        {"NumberofFloors": -1},
        {"PropertyGFAParking": 2**31},
        {"PropertyGFABuilding": -5},
        {"Latitude": 91.0},
    ],
)
def test_manual_features_out_of_bounds_422(client, auth_headers, override):
    r = client.post(
        "/model/predict/features",
        json=dict(MANUAL_PAYLOAD, **override),
        headers=auth_headers,
    )
    assert r.status_code == 422, r.text


@pytest.mark.parametrize(
    "payload",
    [{"building_id": 2**40}, {"building_id": 1, "data_year": 70000}],
)
@pytest.mark.parametrize("route", ["/model/predict", "/model/predict/compare"])
def test_building_request_out_of_bounds_422(client, auth_headers, route, payload):
    r = client.post(route, json=payload, headers=auth_headers)
    assert r.status_code == 422, r.text


def _write_version(path, version: str) -> None:
    info = {"name": CATBOOST_NAME, "version": version, "mlflow_run_id": None}
    path.write_text(json.dumps(info))


def test_prediction_traces_loaded_version_not_active(
    client, db, auth_headers, demo_models, buildings, tmp_path, monkeypatch
):
    """Après un réentraînement, l'API sert encore la version chargée."""
    _write_version(tmp_path / "version.json", "v-loaded")
    monkeypatch.setattr(model_service, "VERSION_PATH", str(tmp_path / "version.json"))
    with db() as s:
        loaded = MlModel(name=CATBOOST_NAME, version="v-loaded", is_active=False)
        s.add(loaded)
        s.commit()
        loaded_id = loaded.id
    r = client.post("/model/predict", json={"building_id": 1}, headers=auth_headers)
    assert r.status_code == 200, r.text
    with db() as s:
        assert s.get(Prediction, r.json()["prediction_id"]).model_id == loaded_id


def test_loaded_version_unknown_in_registry_503(
    client, db, auth_headers, demo_models, buildings, tmp_path, monkeypatch
):
    _write_version(tmp_path / "version.json", "v-inconnue")
    monkeypatch.setattr(model_service, "VERSION_PATH", str(tmp_path / "version.json"))
    r = client.post("/model/predict", json={"building_id": 1}, headers=auth_headers)
    assert r.status_code == 503
    assert "Aucun modèle" in r.json()["detail"]
    with db() as s:
        assert s.scalar(select(func.count()).select_from(Prediction)) == 0


@pytest.mark.parametrize("building_id", [10, 11])
@pytest.mark.parametrize("payload_extra", [{}, {"data_year": 2018}])
@pytest.mark.parametrize("route", ["/model/predict", "/model/predict/compare"])
def test_seen_building_prediction_403(
    client,
    db,
    auth_headers,
    demo_models,
    seen_buildings,
    route,
    payload_extra,
    building_id,
):
    r = client.post(
        route, json={"building_id": building_id, **payload_extra}, headers=auth_headers
    )
    assert r.status_code == 403, r.text
    assert "entraînement" in r.json()["detail"]
    with db() as s:
        assert s.scalar(select(func.count()).select_from(Prediction)) == 0


def test_manual_features_unaffected_by_seen_buildings(
    client, auth_headers, demo_models, seen_buildings
):
    r = client.post(
        "/model/predict/features", json=MANUAL_PAYLOAD, headers=auth_headers
    )
    assert r.status_code == 200, r.text
