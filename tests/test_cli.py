"""Tests du CLI d'entraînement (app.training.__main__)."""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.training import __main__ as cli


def test_build_parser_defaults():
    args = cli.build_parser().parse_args([])
    assert args.output_dir == "models"
    assert args.cv_splits == 5
    assert args.no_kumo is False


def test_build_parser_overrides():
    args = cli.build_parser().parse_args(
        ["--output-dir", "out", "--no-kumo", "--cv-splits", "3"]
    )
    assert args.output_dir == "out"
    assert args.no_kumo is True
    assert args.cv_splits == 3


@pytest.mark.db
def test_main_without_training_rows_exits(db, monkeypatch):
    from app.db import session as db_session

    monkeypatch.setattr(db_session, "owner_session_factory", lambda: db)
    with pytest.raises(SystemExit) as exc:
        cli.main([])
    assert exc.value.code == 2


@pytest.mark.db
def test_main_writes_version_file_of_registered_model(db, monkeypatch, tmp_path):
    from sqlalchemy import select

    from app.db import session as db_session
    from app.db.models import MlModel

    class FakePipeline:
        def __init__(self, **kwargs):
            self.mlflow_run_id = "run-123"

        def run(self, include_kumo=True):
            return {}

    monkeypatch.setattr(db_session, "owner_session_factory", lambda: db)
    monkeypatch.setattr(cli, "load_training_data", lambda session: object())
    monkeypatch.setattr(cli, "TrainPipeline", FakePipeline)
    cli.main(["--output-dir", str(tmp_path), "--no-kumo"])

    info = json.loads((tmp_path / "version.json").read_text())
    with db() as s:
        active = s.scalar(
            select(MlModel).where(MlModel.name == info["name"], MlModel.is_active)
        )
    assert info == {
        "name": "catboost-multitarget",
        "version": active.version,
        "mlflow_run_id": "run-123",
    }
