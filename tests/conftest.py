"""Fixtures PostgreSQL partagées (base `p5_test`, rôles `p5test_*`)."""

import os
import sys
from pathlib import Path

import psycopg
import pytest
from psycopg import sql
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db import create_db
from app.db import session as db_session

ADMIN_URL = os.getenv("TEST_DATABASE_ADMIN_URL") or (
    "postgresql+psycopg://postgres:"
    f"{os.getenv('POSTGRES_PASSWORD', 'postgres')}@localhost:5432/postgres"
)
TEST_DB = "p5_test"
TEST_MLFLOW_DB = "mlflow_test"
TEST_PREFIX = "p5test"
TEST_PASSWORDS = {"owner": "owner-test", "api": "api-test", "mlflow": "mlflow-test"}


@pytest.fixture(scope="session")
def provisioned_db():
    try:
        conn = psycopg.connect(
            create_db.dsn(ADMIN_URL), autocommit=True, connect_timeout=3
        )
    except psycopg.OperationalError as exc:
        pytest.skip(
            f"PostgreSQL de test indisponible ({exc}). "
            "Lancez `docker compose up -d db`."
        )
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
