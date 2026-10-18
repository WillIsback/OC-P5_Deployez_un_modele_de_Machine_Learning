"""Documentation OpenAPI : métadonnées affichées par Swagger (/docs)."""

import importlib

from fastapi.testclient import TestClient

import app.main


def test_openapi_metadata():
    spec = TestClient(app.main.app).get("/openapi.json").json()
    info = spec["info"]
    assert info["title"] == "API de prédiction énergétique — Seattle"
    assert "Authorization: Bearer" in info["description"]
    assert info["license"]["name"] == "MIT"
    assert [t["name"] for t in spec["tags"]] == ["auth", "buildings", "model"]


def test_version_from_environment(monkeypatch):
    monkeypatch.setenv("APP_VERSION", "v9.9.9")
    try:
        assert importlib.reload(app.main).app.version == "v9.9.9"
    finally:
        monkeypatch.delenv("APP_VERSION")
        importlib.reload(app.main)


def test_version_defaults_to_dev(monkeypatch):
    monkeypatch.delenv("APP_VERSION", raising=False)
    assert importlib.reload(app.main).app.version == "dev"
