"""Functional test of the Bearer-JWT authentication + CatBoost prediction."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


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
    test_token_endpoint_ok()
    test_wrong_password()
    test_model_list_requires_token()
    test_model_list_with_token()
    test_model_list_with_bare_token()
    test_model_predict_with_token()
    test_model_predict_requires_token()
    test_model_predict_rejects_extra_field()
    print("All Bearer-JWT + CatBoost tests passed.")
