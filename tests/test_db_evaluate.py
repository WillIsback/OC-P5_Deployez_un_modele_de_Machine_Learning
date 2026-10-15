"""Évaluation projetée : prédictions batch + métriques depuis la vue."""

import pytest
from sqlalchemy import func, select
from synth import make_synth

from app.db import evaluate, ingest, prepare
from app.db import session as db_session
from app.db.models import Prediction, PredictionInput

pytestmark = pytest.mark.db


def _production_year(db, year=2018, n=40):
    df = make_synth(n).assign(DataYear=year)
    with db() as s:
        ingest.ingest_frame(s, df, year=year, source_file=f"{year}.csv")
        return prepare.prepare_year(s, year)


def test_evaluate_creates_batch_predictions_once(db, demo_models):
    n = _production_year(db)
    with db() as s:
        metrics = evaluate.evaluate_years(s, [2018], batch_size=7)
        assert s.scalar(select(func.count()).select_from(Prediction)) == n
        inputs = s.scalars(select(PredictionInput)).all()
        assert {i.input_source for i in inputs} == {"batch"}
        assert all(i.api_request_id is None for i in inputs)
        evaluate.evaluate_years(s, [2018])
        assert s.scalar(select(func.count()).select_from(Prediction)) == n
    assert set(metrics["target"]) == {"energy", "emissions"}
    assert (metrics["data_year"] == 2018).all()
    assert (metrics["n"] > 0).all()


def test_evaluate_without_data_returns_empty(db, demo_models):
    with db() as s:
        assert evaluate.evaluate_years(s, [2019]).empty


def test_evaluate_main(db, demo_models, monkeypatch, capsys):
    _production_year(db, year=2017, n=20)
    monkeypatch.setattr(db_session, "owner_session_factory", lambda: db)
    evaluate.main(["--years", "2017"])
    assert "2017" in capsys.readouterr().out
