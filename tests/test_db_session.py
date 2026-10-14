"""Tests unitaires du module de session (sans base)."""

import sys
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db import session as db_session


def test_get_session_yields_session_from_factory():
    gen = db_session.get_session()
    s = next(gen)
    assert isinstance(s, Session)
    gen.close()


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
