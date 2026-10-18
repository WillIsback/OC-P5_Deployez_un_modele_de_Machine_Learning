"""Rôle `p5test_grafana` : lecture seule, droits par colonne (spec Grafana §3.3)."""

import pytest
from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError

from app.db import create_db

pytestmark = pytest.mark.db

ALLOWED = [
    (
        "SELECT id, user_id, method, path, status_code, duration_ms, created_at "
        "FROM api_requests"
    ),
    (
        "SELECT id, api_request_id, building_year_id, model_id, energy_use_kbtu, "
        "ghg_emissions_tco2e, predicted_at FROM predictions"
    ),
    "SELECT * FROM ml_models",
    "SELECT * FROM v_projected_evaluation",
]
DENIED = [
    "SELECT request_body FROM api_requests",
    "SELECT response_body FROM api_requests",
    "SELECT client_ip FROM api_requests",
    "SELECT input_features FROM predictions",
    "SELECT * FROM users",
    "SELECT * FROM buildings",
    "SELECT * FROM building_years",
    "SELECT * FROM building_actuals",
    "INSERT INTO ml_models (name, version) VALUES ('x', 'y')",
]


@pytest.mark.parametrize("query", ALLOWED)
def test_grafana_role_reads_allowed_columns(grafana_conn, query):
    grafana_conn.as_grafana().execute(text(query)).all()


@pytest.mark.parametrize("query", DENIED)
def test_grafana_role_denied(grafana_conn, query):
    conn = grafana_conn.as_grafana()
    with pytest.raises(ProgrammingError, match="permission denied"):
        conn.execute(text(query))


@pytest.mark.parametrize(("prefix", "expected"), [("p5", "p5_grafana")])
def test_roles_with_prefix_includes_grafana(prefix, expected):
    assert create_db.Roles.with_prefix(prefix).grafana == expected
