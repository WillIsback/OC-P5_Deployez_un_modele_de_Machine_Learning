"""Tests unitaires du module de session (sans base)."""

import sys
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db import session as db_session


def test_get_session_yields_session_from_factory(monkeypatch):
    monkeypatch.setattr(db_session, "_engine", None)
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://u:p@localhost:5432/p5")
    gen = db_session.get_session()
    s = next(gen)
    assert isinstance(s, Session)
    assert s.get_bind() is db_session.get_engine()
    gen.close()


def test_database_url_required_at_first_use(monkeypatch):
    monkeypatch.setattr(db_session, "_engine", None)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with pytest.raises(RuntimeError, match="DATABASE_URL"):
        db_session.get_engine()
    with pytest.raises(RuntimeError, match="DATABASE_URL"):
        next(db_session.get_session())


def test_owner_session_factory_requires_env(monkeypatch):
    monkeypatch.delenv("DATABASE_OWNER_URL", raising=False)
    with pytest.raises(RuntimeError, match="DATABASE_OWNER_URL"):
        db_session.owner_session_factory()


def test_owner_session_factory_uses_env(monkeypatch):
    monkeypatch.setenv(
        "DATABASE_OWNER_URL", "postgresql+psycopg://u:p@localhost:5432/p5"
    )
    factory = db_session.owner_session_factory()
    assert factory.kw["bind"].url.database == "p5"
