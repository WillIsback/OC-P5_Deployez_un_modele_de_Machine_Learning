"""Routes de bout en bout sous le rôle restreint `p5test_api` (régression de GRANT).

Les autres tests d'API tournent avec le rôle propriétaire : un droit manquant au
rôle API (spec §5.2) n'y serait pas détecté. Ici, la connexion superutilisateur
prépare les données en tant que propriétaire, puis bascule sur le rôle API
(`SET LOCAL ROLE`) : chaque requête de l'API et du middleware s'exécute avec les
seuls droits de `p5test_api`, et tout est annulé en fin de test.
"""

import pytest
from conftest import ADMIN_URL, TEST_DB, TEST_PREFIX, login
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker
from synth import add_building, add_year
from test_predict_api import MANUAL_PAYLOAD

from app.db import session as db_session

pytestmark = pytest.mark.db

API_ROLE = f"{TEST_PREFIX}_api"


@pytest.fixture
def api_client(provisioned_db, demo_models, monkeypatch):
    engine = create_engine(make_url(ADMIN_URL).set(database=TEST_DB))
    conn = engine.connect()
    trans = conn.begin()
    factory = sessionmaker(
        bind=conn, join_transaction_mode="create_savepoint", expire_on_commit=False
    )
    try:
        conn.execute(text(f"SET LOCAL ROLE {TEST_PREFIX}_owner"))
        with factory() as s:
            add_year(s, 1, 2018)
            add_building(s, 2)  # résidentiel : identité sans année
            s.commit()
        conn.execute(text(f"SET LOCAL ROLE {API_ROLE}"))
        assert conn.scalar(text("SELECT current_user")) == API_ROLE
        monkeypatch.setattr(db_session, "SessionLocal", factory)
        from app.main import app

        client = TestClient(app)
        token = login(client, "johndoe", "secret")
        assert token.status_code == 200, token.text
        client.headers["Authorization"] = f"Bearer {token.json()['access_token']}"
        yield client
    finally:
        trans.rollback()
        conn.close()
        engine.dispose()


@pytest.mark.parametrize(
    ("route", "payload", "status"),
    [
        ("/model/predict", {"building_id": 1}, 200),
        ("/model/predict", {"building_id": 1, "data_year": 2018}, 200),
        ("/model/predict", {"building_id": 999}, 404),
        ("/model/predict", {"building_id": 1, "data_year": 2017}, 404),
        ("/model/predict", {"building_id": 2}, 422),
        ("/model/predict/features", MANUAL_PAYLOAD, 200),
        ("/model/predict/compare", {"building_id": 1}, 200),
    ],
)
def test_prediction_routes_under_api_role(api_client, route, payload, status):
    r = api_client.post(route, json=payload)
    assert r.status_code == status, r.text


@pytest.mark.parametrize("route", ["/model/list", "/model/metrics"])
def test_read_routes_under_api_role(api_client, route):
    r = api_client.get(route)
    assert r.status_code == 200, r.text
