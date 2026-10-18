"""Fixtures PostgreSQL partagées (base `p5_test`, rôles `p5test_*`)."""

import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import NoReturn

import numpy as np
import pandas as pd
import psycopg
import pytest
from catboost import CatBoostRegressor
from fastapi.testclient import TestClient
from psycopg import sql
from sqlalchemy import Connection, create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# Avant tout import de l'app : clé de signature factice (aucune clé de repli
# dans le code).
os.environ.setdefault("SECRET_KEY", "cle-de-test-non-secrete-de-32-octets-minimum")
# Contexte Kumo réduit : la latence croît avec le nombre de lignes.
os.environ.setdefault("KUMO_CONTEXT_SIZE", "50")

from app.core import metrics_service, model_service
from app.db import create_db
from app.db import session as db_session
from app.schemas.api import CAT_FEATURES, FEATURE_COLUMNS

ADMIN_URL = os.getenv("TEST_DATABASE_ADMIN_URL") or (
    "postgresql+psycopg://postgres:"
    f"{os.getenv('POSTGRES_PASSWORD', 'postgres')}@localhost:5432/postgres"
)
TEST_DB = "p5_test"
TEST_MLFLOW_DB = "mlflow_test"
TEST_PREFIX = "p5test"
TEST_PASSWORDS = {
    "owner": "owner-test",
    "api": "api-test",
    "mlflow": "mlflow-test",
    "grafana": "grafana-test",
}


def db_unavailable(exc: Exception) -> NoReturn:
    """Base de test injoignable : skip en local, échec si REQUIRE_TEST_DB=1 (CI)."""
    message = (
        f"PostgreSQL de test indisponible ({exc}). Lancez `docker compose up -d db`."
    )
    if os.getenv("REQUIRE_TEST_DB") == "1":
        pytest.fail(f"{message} (REQUIRE_TEST_DB=1 : base obligatoire)")
    pytest.skip(message)


@pytest.fixture(scope="session")
def provisioned_db():
    try:
        conn = psycopg.connect(
            create_db.dsn(ADMIN_URL), autocommit=True, connect_timeout=3
        )
    except psycopg.OperationalError as exc:
        db_unavailable(exc)
    else:
        with conn:
            for name in (TEST_DB, TEST_MLFLOW_DB):
                conn.execute(
                    sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(
                        sql.Identifier(name)
                    )
                )
    owner_url = create_db.provision(
        ADMIN_URL,
        passwords=TEST_PASSWORDS,
        db_name=TEST_DB,
        mlflow_db=TEST_MLFLOW_DB,
        role_prefix=TEST_PREFIX,
        demo_users=True,  # johndoe/secret, utilisé par les tests d'API
    )
    api_url = (
        make_url(owner_url)
        .set(username=f"{TEST_PREFIX}_api", password=TEST_PASSWORDS["api"])
        .render_as_string(hide_password=False)
    )
    return {"owner_url": owner_url, "api_url": api_url}


@pytest.fixture(scope="session")
def owner_engine(provisioned_db):
    engine = create_engine(provisioned_db["owner_url"])
    yield engine
    engine.dispose()


@pytest.fixture
def db(owner_engine, monkeypatch):
    """Sessions liées à une transaction annulée en fin de test.

    Chaque ``commit()`` ne relâche qu'un savepoint : le test voit ses écritures,
    la base est intacte après. ``SessionLocal`` est patché pour que l'API et le
    middleware utilisent la même connexion.
    """
    conn = owner_engine.connect()
    trans = conn.begin()
    factory = sessionmaker(
        bind=conn, join_transaction_mode="create_savepoint", expire_on_commit=False
    )
    monkeypatch.setattr(db_session, "SessionLocal", factory)
    try:
        yield factory
    finally:
        trans.rollback()
        conn.close()


@dataclass
class GrafanaConn:
    """Connexion de test : peupler en propriétaire, puis lire en `p5test_grafana`."""

    conn: Connection
    owner: sessionmaker

    def as_grafana(self) -> Connection:
        self.conn.execute(text(f"SET LOCAL ROLE {TEST_PREFIX}_grafana"))
        return self.conn


@pytest.fixture
def grafana_conn(provisioned_db):
    """Transaction annulée en fin de test, sur la connexion superutilisateur.

    Les écritures passent par ``owner`` (rôle propriétaire) ; ``as_grafana()``
    bascule ensuite la connexion sur le rôle Grafana (`SET LOCAL ROLE`).
    """
    engine = create_engine(make_url(ADMIN_URL).set(database=TEST_DB))
    conn = engine.connect()
    trans = conn.begin()
    conn.execute(text(f"SET LOCAL ROLE {TEST_PREFIX}_owner"))
    owner = sessionmaker(
        bind=conn, join_transaction_mode="create_savepoint", expire_on_commit=False
    )
    try:
        yield GrafanaConn(conn, owner)
    finally:
        trans.rollback()
        conn.close()
        engine.dispose()


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


@pytest.fixture
def demo_models(tmp_path, monkeypatch):
    energy = tmp_path / "energy.cbm"
    emissions = tmp_path / "emissions.cbm"
    train_demo_model(str(energy), base=30000.0)
    train_demo_model(str(emissions), base=50.0)
    monkeypatch.setitem(model_service.MODEL_PATHS, "energy", str(energy))
    monkeypatch.setitem(model_service.MODEL_PATHS, "emissions", str(emissions))
    monkeypatch.setattr(model_service, "_models", {})
    # Pas de version.json : repli sur la version active du registre.
    monkeypatch.setattr(model_service, "VERSION_PATH", str(tmp_path / "version.json"))
    scores = tmp_path / "scores.json"
    scores.write_text(json.dumps(_SCORES))
    monkeypatch.setattr(metrics_service, "METRICS_PATH", str(scores))
    monkeypatch.setattr(metrics_service, "_metrics", None)
    yield


@pytest.fixture
def client(db):
    from app.main import app

    return TestClient(app)


def login(client, username: str, password: str):
    return client.post(
        "/token",
        data={"username": username, "password": password},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )


@pytest.fixture
def auth_headers(client):
    r = login(client, "johndoe", "secret")
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}
