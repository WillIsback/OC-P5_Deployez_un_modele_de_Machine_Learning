"""Client HTTP de l'interface, de bout en bout à travers la vraie API."""

import httpx
import pytest
from sqlalchemy import select
from synth import add_year

from app.db.models import ApiRequest, User
from app.ui.client import ApiClient, ApiError, SessionExpired, default_client

pytestmark = pytest.mark.db


@pytest.fixture
def ui_client(client, db, demo_models):
    """`ApiClient` sur le TestClient de l'application (un `httpx.Client`)."""
    with db() as s:
        add_year(s, 1, 2018)
        s.commit()
    return ApiClient(client)


@pytest.fixture
def token(ui_client):
    return ui_client.login("johndoe", "secret")


def test_login_returns_token(token):
    assert isinstance(token, str) and token


def test_login_wrong_password(ui_client):
    with pytest.raises(ApiError) as err:
        ui_client.login("johndoe", "faux")
    assert err.value.status == 400
    assert str(err.value) == "Identifiants incorrects ou compte inactif"


def test_login_inactive_user(ui_client):
    with pytest.raises(ApiError) as err:
        ui_client.login("alice", "secret")
    assert err.value.status == 400


def test_search_and_paginate(ui_client, token):
    page = ui_client.search_buildings(token, limit=1, offset=0)
    assert page["total"] == 1
    assert [b["building_id"] for b in page["items"]] == [1]
    neighborhood = page["items"][0]["neighborhood"]
    assert ui_client.search_buildings(token, neighborhood=neighborhood)["total"] == 1
    assert ui_client.search_buildings(token, neighborhood="NULLE PART")["total"] == 0


def test_get_building(ui_client, token):
    detail = ui_client.get_building(token, 1)
    assert detail["building_id"] == 1
    assert [y["data_year"] for y in detail["years"]] == [2018]


def test_predict(ui_client, token):
    result = ui_client.predict(token, 1, 2018)
    assert result["energy_use_kbtu"] > 0
    assert result["prediction_id"]


def test_compare(ui_client, token):
    result = ui_client.compare(token, 1)
    assert result["catboost_prediction"]["energy_use_kbtu"] > 0
    assert result["kumo_prediction"]["energy_use_kbtu"] > 0


def test_unknown_building(ui_client, token):
    with pytest.raises(ApiError) as err:
        ui_client.predict(token, 999_999)
    assert err.value.status == 404
    assert "inconnu" in str(err.value)


def test_invalid_token_is_session_expired(ui_client):
    with pytest.raises(SessionExpired) as err:
        ui_client.search_buildings("faux")
    assert err.value.status == 401
    assert str(err.value) == "Session expirée, reconnectez-vous"


def test_validation_error_message(ui_client, token):
    with pytest.raises(ApiError) as err:
        ui_client.search_buildings(token, q="x")
    assert (err.value.status, str(err.value)) == (422, "Requête invalide")


def test_transport_error():
    client = ApiClient(httpx.Client(base_url="http://127.0.0.1:1", timeout=1))
    with pytest.raises(ApiError) as err:
        client.login("johndoe", "secret")
    assert (err.value.status, str(err.value)) == (None, "API indisponible")


def test_prediction_traced_with_user(ui_client, token, db):
    ui_client.predict(token, 1)
    with db() as s:
        johndoe = s.scalar(select(User.id).where(User.username == "johndoe"))
        users = s.scalars(
            select(ApiRequest.user_id).where(ApiRequest.path == "/model/predict")
        ).all()
    assert users == [johndoe]


def test_default_client_reads_env(monkeypatch):
    monkeypatch.setenv("P5_API_URL", "http://api:8080")
    assert str(default_client().http.base_url) == "http://api:8080"


@pytest.mark.parametrize("body", [b"<html>Bad Gateway</html>", b"[1, 2]"])
def test_error_without_json_detail(body):
    """Erreur renvoyée par un proxy (HTML) ou corps inattendu : message générique."""
    transport = httpx.MockTransport(lambda request: httpx.Response(502, content=body))
    client = ApiClient(httpx.Client(base_url="http://api", transport=transport))
    with pytest.raises(ApiError) as err:
        client.get_building("jeton", 1)
    assert (err.value.status, str(err.value)) == (502, "Requête invalide")
