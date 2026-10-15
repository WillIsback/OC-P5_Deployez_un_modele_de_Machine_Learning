"""Comportement des fixtures quand PostgreSQL de test est injoignable."""

import pytest
from conftest import db_unavailable


def test_unavailable_db_skips_by_default(monkeypatch):
    monkeypatch.delenv("REQUIRE_TEST_DB", raising=False)
    with pytest.raises(pytest.skip.Exception, match="indisponible"):
        db_unavailable(OSError("refusé"))


def test_unavailable_db_fails_when_required(monkeypatch):
    monkeypatch.setenv("REQUIRE_TEST_DB", "1")
    with pytest.raises(pytest.fail.Exception, match="REQUIRE_TEST_DB"):
        db_unavailable(OSError("refusé"))
