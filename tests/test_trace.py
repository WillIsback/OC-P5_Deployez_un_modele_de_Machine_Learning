"""Traçabilité : une ligne api_requests par appel (spec §4.3)."""

import uuid

import pytest
from conftest import login
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from app.db import session as db_session
from app.db.models import ApiRequest, User
from app.middleware.trace import TraceMiddleware

pytestmark = pytest.mark.db


def _trace(db, response) -> ApiRequest:
    rid = uuid.UUID(response.headers["x-request-id"])
    with db() as s:
        return s.scalar(select(ApiRequest).where(ApiRequest.request_id == rid))


def test_token_call_traced_without_secrets(client, db):
    r = login(client, "johndoe", "secret")
    row = _trace(db, r)
    assert row.path == "/token"
    assert row.method == "POST"
    assert row.status_code == 200
    assert row.request_body["password"] == "***"
    assert row.request_body["username"] == "johndoe"
    assert row.response_body["access_token"] == "***"
    assert row.duration_ms is not None
    assert row.client_ip is None  # "testclient" n'est pas une IP


def test_authenticated_call_records_user(client, db, auth_headers):
    r = client.get("/model/list", headers=auth_headers)
    with db() as s:
        johndoe = s.scalar(select(User.id).where(User.username == "johndoe"))
    row = _trace(db, r)
    assert row.user_id == johndoe
    assert row.status_code == 200
    assert isinstance(row.response_body, list)


def test_unauthenticated_call_traced_with_null_user(client, db):
    r = client.get("/model/list")
    row = _trace(db, r)
    assert row.status_code == 401
    assert row.user_id is None


def test_long_path_truncated(client, db):
    r = client.get("/" + "x" * 400)
    row = _trace(db, r)
    assert r.status_code == 404
    assert len(row.path) == 255


def test_nul_in_path_sanitized(client, db):
    r = client.get("/a%00b")
    assert r.status_code == 404
    row = _trace(db, r)
    assert "\x00" not in row.path
    assert row.path == "/a\ufffdb"


def test_long_method_truncated(client, db):
    r = client.request("VERSION-CONTROL", "/model/list")
    assert r.status_code == 405
    row = _trace(db, r)
    assert row.method == "VERSION-CO"


def test_docs_not_traced(client, db):
    with db() as s:
        before = s.scalar(select(func.count()).select_from(ApiRequest))
    r = client.get("/openapi.json")
    assert r.status_code == 200
    assert "x-request-id" not in r.headers
    with db() as s:
        assert s.scalar(select(func.count()).select_from(ApiRequest)) == before


def test_unusual_body_traced_with_raw_marker(client, db):
    r = client.post(
        "/token",
        content=b"\xff\xfe\x00binaire",
        headers={"Content-Type": "application/json"},
    )
    assert r.status_code == 422
    row = _trace(db, r)
    assert "_raw" in row.request_body


def test_unhandled_exception_traced_as_500(db):
    mini = FastAPI()
    mini.add_middleware(TraceMiddleware)

    @mini.get("/boom")
    def boom():
        raise RuntimeError("boom")

    r = TestClient(mini, raise_server_exceptions=False).get("/boom")
    assert r.status_code == 500
    with db() as s:
        row = s.scalar(select(ApiRequest).where(ApiRequest.path == "/boom"))
    assert row.status_code == 500


def test_database_down_returns_503(monkeypatch):
    from app.main import app

    dead = create_engine(
        "postgresql+psycopg://x:y@127.0.0.1:1/none",
        connect_args={"connect_timeout": 1},
    )
    monkeypatch.setattr(db_session, "SessionLocal", sessionmaker(bind=dead))
    r = TestClient(app).get("/model/list")
    assert r.status_code == 503
    assert r.json() == {"detail": "Base de données indisponible"}


def test_pool_timeout_in_trace_returns_503(client, monkeypatch):
    """Pool de connexions épuisé : indisponibilité (503), pas requête sans trace."""
    from sqlalchemy.exc import TimeoutError as PoolTimeout

    from app.middleware import trace

    def exhausted(*args, **kwargs):
        raise PoolTimeout("QueuePool limit reached")

    monkeypatch.setattr(trace, "_insert_request", exhausted)
    r = client.get("/model/list")
    assert r.status_code == 503
    assert r.json() == {"detail": "Base de données indisponible"}


def test_pool_timeout_in_route_returns_503(client, auth_headers, monkeypatch):
    from sqlalchemy.exc import TimeoutError as PoolTimeout

    from app.core import prediction_service

    def exhausted(*args, **kwargs):
        raise PoolTimeout("QueuePool limit reached")

    monkeypatch.setattr(prediction_service, "resolve_features", exhausted)
    r = client.post("/model/predict", json={"building_id": 1}, headers=auth_headers)
    assert r.status_code == 503
    assert r.json() == {"detail": "Base de données indisponible"}


def test_finalize_failure_keeps_response(client, monkeypatch, caplog):
    """Échec de la finalisation : la réponse part quand même, l'erreur est journalisée."""
    from sqlalchemy.exc import DataError

    from app.middleware import trace

    def broken(*args, **kwargs):
        raise DataError("UPDATE", {}, Exception("valeur refusée"))

    monkeypatch.setattr(trace, "_finalize_request", broken)
    r = client.get("/model/list")
    assert r.status_code == 401
    assert "Échec de la finalisation de la trace" in caplog.text


@pytest.mark.parametrize(
    ("scope", "expected"),
    [
        ({}, None),
        ({"client": ("pas-une-ip", 1)}, None),
        ({"client": ("::1", 1)}, "::1"),
    ],
)
def test_client_ip(scope, expected):
    from app.middleware.trace import _client_ip

    assert _client_ip(scope) == expected


def test_buffer_body_replays_then_delegates():
    """Corps en plusieurs morceaux, puis déconnexion : rejoué puis délégué."""
    import asyncio

    from app.middleware.trace import _buffer_body

    incoming = [
        {"type": "http.request", "body": b"ab", "more_body": True},
        {"type": "http.disconnect"},
        {"type": "http.disconnect"},
    ]

    async def receive():
        return incoming.pop(0)

    async def scenario():
        body, replay = await _buffer_body(receive)
        replayed = [await replay(), await replay(), await replay()]
        return body, replayed

    body, replayed = asyncio.run(scenario())
    assert body == b"ab"
    assert [m["type"] for m in replayed] == [
        "http.request",
        "http.disconnect",
        "http.disconnect",
    ]
