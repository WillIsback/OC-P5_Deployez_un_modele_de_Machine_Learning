"""Tests d'intégration : migration, contraintes, rôles, provisionnement."""

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, delete, func, inspect, select, text
from sqlalchemy.exc import IntegrityError, ProgrammingError
from sqlalchemy.orm import Session
from synth import add_year

from app.db import create_db
from app.db.models import Base, Building, MlModel, Prediction, User
from app.db.registry import CATBOOST_NAME, active_model, register_model

pytestmark = pytest.mark.db


def test_migrations_match_models(owner_engine):
    with owner_engine.connect() as conn:
        diff = compare_metadata(MigrationContext.configure(conn), Base.metadata)
    assert diff == []


def test_view_exists(owner_engine):
    columns = {
        c["name"] for c in inspect(owner_engine).get_columns("v_projected_evaluation")
    }
    assert {
        "model_name",
        "model_version",
        "data_year",
        "building_id",
        "exclusion_reason",
        "predicted_energy_kbtu",
        "actual_energy_kbtu",
        "predicted_ghg_tco2e",
        "actual_ghg_tco2e",
        "abs_err_energy_kbtu",
        "rel_err_energy",
        "abs_err_ghg_tco2e",
        "rel_err_ghg",
    } <= columns
    with owner_engine.connect() as conn:
        conn.execute(text("SELECT * FROM v_projected_evaluation LIMIT 0"))


def test_seed_users_and_models(db):
    with db() as s:
        users = {u.username: u.is_active for u in s.scalars(select(User))}
        assert users == {"johndoe": True, "alice": False}
        assert active_model(s, CATBOOST_NAME).version == "baseline"


def test_seed_without_demo_users_keeps_models(db):
    with db() as s:
        s.execute(delete(User))
        create_db.seed(s, demo_users=False)
        assert s.scalar(select(func.count()).select_from(User)) == 0
        assert active_model(s, CATBOOST_NAME) is not None


@pytest.mark.parametrize(
    ("argv", "env", "expected"),
    [
        ([], None, False),
        ([], "0", False),
        ([], "1", True),
        (["--demo-users"], None, True),
    ],
)
def test_create_db_main_demo_users_opt_in(monkeypatch, argv, env, expected):
    calls = {}

    def fake_provision(admin_url, **kwargs):
        calls.update(kwargs)
        return admin_url

    for var in (
        "P5_OWNER_PASSWORD",
        "P5_API_PASSWORD",
        "P5_MLFLOW_PASSWORD",
        "P5_GRAFANA_PASSWORD",
    ):
        monkeypatch.setenv(var, var.lower())
    monkeypatch.setenv("DATABASE_ADMIN_URL", "postgresql+psycopg://u:p@h/db")
    if env is None:
        monkeypatch.delenv("P5_SEED_DEMO_USERS", raising=False)
    else:
        monkeypatch.setenv("P5_SEED_DEMO_USERS", env)
    monkeypatch.setattr(create_db, "provision", fake_provision)
    create_db.main(argv)
    assert calls["demo_users"] is expected
    assert calls["passwords"]["grafana"] == "p5_grafana_password"


def test_provision_is_idempotent(provisioned_db):
    from conftest import ADMIN_URL, TEST_DB, TEST_MLFLOW_DB, TEST_PASSWORDS, TEST_PREFIX

    create_db.provision(
        ADMIN_URL,
        passwords=TEST_PASSWORDS,
        db_name=TEST_DB,
        mlflow_db=TEST_MLFLOW_DB,
        role_prefix=TEST_PREFIX,
        demo_users=True,
    )
    engine = create_engine(provisioned_db["owner_url"])
    with Session(engine) as s:
        assert s.scalar(select(func.count()).select_from(User)) == 2
    engine.dispose()


def test_split_values_checked(db):
    with db() as s:
        s.add(Building(id=1, split="invalid"))
        with pytest.raises(IntegrityError):
            s.commit()


def test_exclusion_reason_values_checked(db):
    with db() as s, pytest.raises(IntegrityError):
        add_year(s, 1, 2016, exclusion_reason="mauvaise-raison")


def test_prediction_requires_an_origin(db):
    with db() as s:
        model = active_model(s, CATBOOST_NAME)
        s.add(
            Prediction(
                model_id=model.id,
                input_features={},
                energy_use_kbtu=1.0,
                ghg_emissions_tco2e=1.0,
            )
        )
        with pytest.raises(IntegrityError):
            s.commit()


def test_batch_prediction_unique_per_year_and_model(db):
    with db() as s:
        year = add_year(s, 1, 2018)
        model = active_model(s, CATBOOST_NAME)
        for _ in range(2):
            s.add(
                Prediction(
                    building_year_id=year.id,
                    model_id=model.id,
                    input_features={},
                    energy_use_kbtu=1.0,
                    ghg_emissions_tco2e=1.0,
                )
            )
        with pytest.raises(IntegrityError):
            s.commit()


def test_single_active_version_per_model(db):
    with db() as s:
        s.add(MlModel(name=CATBOOST_NAME, version="dup", is_active=True))
        with pytest.raises(IntegrityError):
            s.commit()


def test_register_model_switches_active_version(db):
    with db() as s:
        new = register_model(
            s,
            name=CATBOOST_NAME,
            version="20261014120000",
            mlflow_run_id="abc",
            artifact_path="models",
        )
        assert active_model(s, CATBOOST_NAME).id == new.id
        assert (
            s.scalar(
                select(func.count())
                .select_from(MlModel)
                .where(MlModel.name == CATBOOST_NAME, MlModel.is_active)
            )
            == 1
        )


def test_api_role_reads_dataset_but_not_actuals(provisioned_db):
    engine = create_engine(provisioned_db["api_url"])
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT id, property_name, split FROM buildings LIMIT 0"))
            conn.execute(text("SELECT id, data_year FROM building_years LIMIT 0"))
        with engine.connect() as conn, pytest.raises(ProgrammingError):
            conn.execute(text("SELECT * FROM building_actuals"))
    finally:
        engine.dispose()
