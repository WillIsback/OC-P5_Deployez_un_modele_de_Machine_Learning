"""Tests d'intégration : migration, contraintes, rôles, provisionnement."""

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, delete, func, inspect, select, text
from sqlalchemy.exc import IntegrityError, ProgrammingError
from sqlalchemy.orm import Session
from synth import EXAMPLE_FEATURES, add_record

from app.db import create_db, mapping
from app.db.models import Base, BuildingFeatures, MlModel, PredictionInput, User
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

    for var in ("P5_OWNER_PASSWORD", "P5_API_PASSWORD", "P5_MLFLOW_PASSWORD"):
        monkeypatch.setenv(var, "x")
    monkeypatch.setenv("DATABASE_ADMIN_URL", "postgresql+psycopg://u:p@h/db")
    if env is None:
        monkeypatch.delenv("P5_SEED_DEMO_USERS", raising=False)
    else:
        monkeypatch.setenv("P5_SEED_DEMO_USERS", env)
    monkeypatch.setattr(create_db, "provision", fake_provision)
    create_db.main(argv)
    assert calls["demo_users"] is expected


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


def _features(**overrides):
    return BuildingFeatures(
        **mapping.features_to_sql(EXAMPLE_FEATURES), prep_version="t", **overrides
    )


def test_split_requires_eligibility(db):
    with db() as s:
        rec = add_record(s, 1, 2016)
        s.add(
            _features(
                record_id=rec.id,
                dataset_role="training",
                is_training_eligible=False,
                exclusion_reason="outlier",
                split="train",
            )
        )
        with pytest.raises(IntegrityError):
            s.commit()


def test_production_rows_cannot_be_eligible(db):
    with db() as s:
        rec = add_record(s, 1, 2018)
        s.add(
            _features(
                record_id=rec.id,
                dataset_role="production",
                is_training_eligible=True,
                split="train",
            )
        )
        with pytest.raises(IntegrityError):
            s.commit()


def test_batch_input_requires_record(db):
    with db() as s:
        s.add(
            PredictionInput(
                input_source="batch",
                building_record_id=None,
                **mapping.features_to_sql(EXAMPLE_FEATURES),
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


def test_api_role_cannot_read_pii_or_actuals(provisioned_db):
    engine = create_engine(provisioned_db["api_url"])
    try:
        with engine.connect() as conn:
            conn.execute(
                text("SELECT id, building_id, data_year FROM building_records_raw")
            )
        for forbidden in (
            "SELECT address FROM building_records_raw",
            "SELECT * FROM building_actuals",
        ):
            with engine.connect() as conn, pytest.raises(ProgrammingError):
                conn.execute(text(forbidden))
    finally:
        engine.dispose()
