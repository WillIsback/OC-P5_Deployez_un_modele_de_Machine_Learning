"""Functional test of the Bearer-JWT authentication + CatBoost prediction."""

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


from app.core import model_service
from app.core.model_service import CAT_FEATURES, FEATURE_COLUMNS
from app.main import app

client = TestClient(app)


def train_demo_model(path: str) -> None:
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
    y_log = np.log1p(3.0 * df["PropertyGFABuilding(s)"] + 30000)
    model = CatBoostRegressor(iterations=120, depth=4, random_seed=42, verbose=0)
    model.fit(X, y_log, cat_features=CAT_FEATURES)
    model.save_model(path)


_DEMO_MODEL = os.path.join(tempfile.gettempdir(), "energy_demo.cbm")


def ensure_demo_model() -> None:
    """Garantit un modèle disponible et pointe le service dessus (reset singleton)."""
    if not os.path.exists(_DEMO_MODEL):
        train_demo_model(_DEMO_MODEL)
    model_service.MODEL_PATH = _DEMO_MODEL
    model_service._model = None


@pytest.fixture(autouse=True)
def _demo_model_autouse():
    ensure_demo_model()
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
    assert r.json()[0]["name"] == "catboost-energy-seattle"


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


if __name__ == "__main__":
    ensure_demo_model()
    test_token_endpoint_ok()
    test_wrong_password()
    test_model_list_requires_token()
    test_model_list_with_token()
    test_model_list_with_bare_token()
    test_model_predict_with_token()
    test_model_predict_requires_token()
    test_model_predict_rejects_extra_field()
    print("All Bearer-JWT + CatBoost tests passed.")
    test_token_endpoint_ok()
    test_wrong_password()
    test_model_list_requires_token()
    test_model_list_with_token()
    test_model_list_with_bare_token()
    test_model_predict_with_token()
    test_model_predict_requires_token()
    test_model_predict_rejects_extra_field()
    print("All Bearer-JWT + CatBoost tests passed.")
