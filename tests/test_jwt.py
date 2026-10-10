"""Functional test of the Bearer-JWT authentication + CatBoost prediction."""

import json
import os
import sys
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from catboost import CatBoostRegressor
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


from app.core import metrics_service, model_service
from app.main import app
from app.schemas.api import CAT_FEATURES, FEATURE_COLUMNS

client = TestClient(app)


def train_demo_model(path: str, base: float) -> None:
    """Entraîne un petit CatBoost sur données synthétiques (layout Seattle)."""
    rng = np.random.default_rng(0)
    n = 120
    df = pd.DataFrame(
        {
            "BuildingType": rng.choice(
                ["Commercial", "Office", "Warehouse", "Industrial"], n
            ),
            "PrimaryPropertyType": rng.choice(
                ["Office", "Retail", "Warehouse/Storage", "Service"], n
            ),
            "Neighborhood": rng.choice(["BALLARD", "DOWNTOWN", "FREMONT"], n),
            "Latitude": rng.uniform(47.5, 47.7, n),
            "Longitude": rng.uniform(-122.4, -122.25, n),
            "YearBuilt": rng.integers(1930, 2020, n),
            "NumberofBuildings": rng.integers(1, 3, n).astype(float),
            "NumberofFloors": rng.integers(1, 8, n),
            "PropertyGFAParking": rng.integers(0, 20000, n),
            "PropertyGFABuilding(s)": rng.integers(500, 40000, n),
            "LargestPropertyUseType": rng.choice(
                ["Office", "Retail", "Warehouse", "Parking"], n
            ),
            "SecondLargestPropertyUseType": rng.choice(["Retail", "Service"], n),
            "SecondLargestPropertyUseTypeGFA": rng.uniform(0, 12000, n),
            "ThirdLargestPropertyUseType": rng.choice(["Parking", "Service"], n),
            "ThirdLargestPropertyUseTypeGFA": rng.uniform(0, 8000, n),
            "Has_NaturalGas": rng.integers(0, 2, n),
            "Has_Steam": rng.integers(0, 2, n),
        }
    )
    for col in CAT_FEATURES:
        df[col] = df[col].astype(str)
    X = df[FEATURE_COLUMNS]
    y_log = np.log1p(base + 3.0 * df["PropertyGFABuilding(s)"])
    model = CatBoostRegressor(iterations=60, depth=4, random_seed=42, verbose=0)
    model.fit(X, y_log, cat_features=CAT_FEATURES)
    model.save_model(path)


_DEMO_DIR = Path(tempfile.gettempdir()) / "p5_demo_models"
_DEMO_ENERGY = _DEMO_DIR / "energy.cbm"
_DEMO_EMISSIONS = _DEMO_DIR / "emissions.cbm"

_SCORES_PATH = os.path.join(tempfile.gettempdir(), "p5_scores.json")
_SCORES = {
    "targets": {
        "energy": {
            "unit": "kBtu/an",
            "models": {
                "catboost": {
                    "R2": 0.91,
                    "MAE": 1200.0,
                    "MedAE": 800.0,
                    "MedAPE_pct": 5.2,
                },
                "kumo": {
                    "R2": 0.55,
                    "MAE": 3400.0,
                    "MedAE": 2100.0,
                    "MedAPE_pct": 14.7,
                },
            },
        },
        "emissions": {
            "unit": "t CO2e/an",
            "models": {
                "catboost": {
                    "R2": 0.86,
                    "MAE": 2.4,
                    "MedAE": 1.6,
                    "MedAPE_pct": 6.1,
                },
                "kumo": {
                    "R2": 0.42,
                    "MAE": 5.8,
                    "MedAE": 4.1,
                    "MedAPE_pct": 19.3,
                },
            },
        },
    }
}


def ensure_demo_models() -> None:
    """Garantit deux modèles disponibles et pointe le service dessus."""
    _DEMO_DIR.mkdir(parents=True, exist_ok=True)
    if not _DEMO_ENERGY.exists():
        train_demo_model(str(_DEMO_ENERGY), base=30000.0)
    if not _DEMO_EMISSIONS.exists():
        train_demo_model(str(_DEMO_EMISSIONS), base=50.0)
    model_service.MODEL_PATHS["energy"] = str(_DEMO_ENERGY)
    model_service.MODEL_PATHS["emissions"] = str(_DEMO_EMISSIONS)
    model_service._models = {}


@pytest.fixture(autouse=True)
def _demo_models_autouse(monkeypatch):
    ensure_demo_models()
    if not os.path.exists(_SCORES_PATH):
        with open(_SCORES_PATH, "w", encoding="utf-8") as f:
            json.dump(_SCORES, f)
    monkeypatch.setattr(metrics_service, "METRICS_PATH", _SCORES_PATH)
    monkeypatch.setattr(metrics_service, "_metrics", None)
    yield


def login(username: str, password: str) -> str:
    r = client.post(
        "/token",
        data={"username": username, "password": password},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def test_token_endpoint_ok() -> str:
    token = login("johndoe", "secret")
    assert token
    return token


def test_wrong_password():
    r = client.post(
        "/token",
        data={"username": "johndoe", "password": "wrong"},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert r.status_code == 400, r.text


EXAMPLE_PAYLOAD = {
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


def test_model_list_requires_token():
    r = client.get("/model/list")
    assert r.status_code == 401, r.text


def test_model_list_with_token():
    token = test_token_endpoint_ok()
    r = client.get("/model/list", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200, r.text
    models = r.json()
    assert len(models) == 3
    assert models[0]["name"] == "catboost-energy-seattle"
    assert models[1]["name"] == "catboost-emissions-seattle"
    assert models[2]["name"] == "kumo-tabular-zero-shot"


def test_model_predict_with_token():
    token = test_token_endpoint_ok()
    r = client.post(
        "/model/predict",
        json=EXAMPLE_PAYLOAD,
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["energy_use_kbtu"] > 0
    assert body["ghg_emissions_tco2e"] > 0
    assert body["units"] == "kBtu/an"
    assert "model_name" in body


def test_model_list_with_bare_token():
    # Tolerates a token pasted with no "Bearer " prefix (some Swagger UI
    # versions do not add it automatically).
    token = test_token_endpoint_ok()
    r = client.get("/model/list", headers={"Authorization": token})
    assert r.status_code == 200, r.text


def test_model_predict_requires_token():
    r = client.post("/model/predict", json=EXAMPLE_PAYLOAD)
    assert r.status_code == 401, r.text


def test_model_predict_rejects_extra_field():
    token = test_token_endpoint_ok()
    bad = dict(EXAMPLE_PAYLOAD, extra_field="nope")
    r = client.post(
        "/model/predict",
        json=bad,
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 422, r.text


def test_metrics_requires_token():
    r = client.get("/model/metrics")
    assert r.status_code == 401, r.text


def test_metrics_with_token():
    token = test_token_endpoint_ok()
    r = client.get(
        "/model/metrics",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert "targets" in body
    energy = body["targets"]["energy"]
    assert energy["unit"] == "kBtu/an"
    cb = energy["models"]["catboost"]
    assert isinstance(cb["R2"], float)
    assert cb["MAE"] > 0
    assert cb["MedAE"] > 0
    assert cb["MedAPE_pct"] > 0
    assert "kumo" in energy["models"]
    assert body["targets"]["emissions"]["unit"] == "t CO2e/an"


def test_compare_requires_token():
    r = client.post("/model/predict/compare", json=EXAMPLE_PAYLOAD)
    assert r.status_code == 401, r.text


def test_compare_with_token():
    token = test_token_endpoint_ok()
    r = client.post(
        "/model/predict/compare",
        json=EXAMPLE_PAYLOAD,
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert "catboost_prediction" in body
    assert "kumo_prediction" in body
    assert "comparison_note" in body
    # CatBoost prediction
    cb = body["catboost_prediction"]
    assert cb["energy_use_kbtu"] > 0
    assert cb["ghg_emissions_tco2e"] > 0
    assert "model_name" in cb
    # Kumo-Tabular prediction
    km = body["kumo_prediction"]
    assert km["energy_use_kbtu"] > 0
    assert km["ghg_emissions_tco2e"] > 0
    assert km["model_name"] == "kumo-tabular-zero-shot"


def test_compare_rejects_extra_field():
    token = test_token_endpoint_ok()
    bad = dict(EXAMPLE_PAYLOAD, extra_field="nope")
    r = client.post(
        "/model/predict/compare",
        json=bad,
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 422, r.text


if __name__ == "__main__":
    ensure_demo_models()
    test_token_endpoint_ok()
    test_wrong_password()
    test_model_list_requires_token()
    test_model_list_with_token()
    test_model_list_with_bare_token()
    test_model_predict_with_token()
    test_model_predict_requires_token()
    test_model_predict_rejects_extra_field()
    test_compare_requires_token()
    test_compare_with_token()
    test_compare_rejects_extra_field()
    test_metrics_requires_token()
    test_metrics_with_token()
    print("All Bearer-JWT + CatBoost + Kumo-Tabular tests passed.")
