"""Routes de prédiction : écriture input → prédiction → trace (spec §4.3)."""

import pytest
from sqlalchemy import func, select, update
from synth import EXAMPLE_FEATURES, add_record

from app.core import model_service
from app.db import mapping
from app.db.models import (
    ApiRequest,
    BuildingFeatures,
    MlModel,
    Prediction,
    PredictionInput,
    User,
)
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
    """Bâtiment 1 (2016, 2018) dans le périmètre ; bâtiment 2 résidentiel."""
    with db() as s:
        r16 = add_record(s, 1, 2016)
        r18 = add_record(s, 1, 2018)
        add_record(s, 2, 2018, building_type="Multifamily LR (1-4)")
        for rec in (r16, r18):
            s.add(
                BuildingFeatures(
                    record_id=rec.id,
                    dataset_role="production",
                    is_training_eligible=False,
                    prep_version="t",
                    **mapping.features_to_sql(EXAMPLE_FEATURES),
                )
            )
        s.commit()
        return {"2016": r16.id, "2018": r18.id}


def _input(db, prediction_id) -> PredictionInput:
    with db() as s:
        pred = s.get(Prediction, prediction_id)
        return s.get(PredictionInput, pred.prediction_input_id)


def test_predict_by_id_uses_latest_year(
    client, db, auth_headers, demo_models, buildings
):
    r = client.post("/model/predict", json={"building_id": 1}, headers=auth_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["energy_use_kbtu"] > 0
    assert body["request_id"] == r.headers["x-request-id"]
    inp = _input(db, body["prediction_id"])
    assert inp.input_source == "building_id"
    assert inp.building_record_id == buildings["2018"]
    assert inp.api_request_id is not None


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
    assert _input(db, r.json()["prediction_id"]).building_record_id == buildings["2016"]


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
    inp = _input(db, r.json()["prediction_id"])
    assert inp.input_source == "manual"
    assert inp.building_record_id is None
    assert inp.property_gfa_buildings == 15000


def test_manual_features_reject_extra_field(client, auth_headers):
    bad = dict(MANUAL_PAYLOAD, extra_field="nope")
    r = client.post("/model/predict/features", json=bad, headers=auth_headers)
    assert r.status_code == 422


def test_compare_one_input_two_predictions(
    client, db, auth_headers, demo_models, buildings
):
    r = client.post(
        "/model/predict/compare", json={"building_id": 1}, headers=auth_headers
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["kumo_prediction"]["model_name"] == "kumo-tabular-zero-shot"
    cb_input = _input(db, body["catboost_prediction"]["prediction_id"])
    km_input = _input(db, body["kumo_prediction"]["prediction_id"])
    assert cb_input.id == km_input.id


def test_model_failure_keeps_input_without_prediction(
    client, db, auth_headers, buildings, monkeypatch
):
    def boom(df):
        raise FileNotFoundError("modèle absent")

    monkeypatch.setattr(model_service, "predict_frame", boom)
    with db() as s:
        before = s.scalar(select(func.count()).select_from(PredictionInput))
    r = client.post("/model/predict", json={"building_id": 1}, headers=auth_headers)
    assert r.status_code == 503
    with db() as s:
        assert s.scalar(select(func.count()).select_from(PredictionInput)) == before + 1
        assert s.scalar(select(func.count()).select_from(Prediction)) == 0


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
        before = s.scalar(select(func.count()).select_from(PredictionInput))
    r = client.post(route, json=payload, headers=auth_headers)
    assert r.status_code == 503
    assert r.json()["detail"] == "Traçabilité indisponible, prédiction refusée"
    with db() as s:
        assert s.scalar(select(func.count()).select_from(PredictionInput)) == before
        assert s.scalar(select(func.count()).select_from(Prediction)) == 0
