"""Évaluation projetée : prédictions batch + métriques depuis la vue."""

import pytest
from sqlalchemy import func, select
from synth import make_synth

from app.db import evaluate, ingest
from app.db import session as db_session
from app.db.models import Prediction

pytestmark = pytest.mark.db


def _production_year(db, year=2018, n=40):
    df = make_synth(n).assign(DataYear=year)
    with db() as s:
        return ingest.ingest_frame(s, df, year=year)


def test_evaluate_creates_batch_predictions_once(db, demo_models):
    n = _production_year(db)
    with db() as s:
        metrics = evaluate.evaluate_years(s, [2018], batch_size=7)
        assert s.scalar(select(func.count()).select_from(Prediction)) == n
        preds = s.scalars(select(Prediction)).all()
        assert all(p.api_request_id is None for p in preds)
        assert all(p.building_year_id is not None for p in preds)
        evaluate.evaluate_years(s, [2018])
        assert s.scalar(select(func.count()).select_from(Prediction)) == n
    assert set(metrics["target"]) == {"energy", "emissions"}
    assert (metrics["data_year"] == 2018).all()
    assert (metrics["n"] > 0).all()


def test_evaluate_without_data_returns_empty(db, demo_models):
    with db() as s:
        assert evaluate.evaluate_years(s, [2019]).empty


def test_evaluate_skips_training_year(db, demo_models):
    with db() as s:
        ingest.ingest_frame(s, make_synth(40), year=2016)
        assert evaluate.evaluate_years(s, [2016]).empty
        assert s.scalar(select(func.count()).select_from(Prediction)) == 0


def test_evaluate_main(db, demo_models, monkeypatch, capsys):
    _production_year(db, year=2017, n=20)
    monkeypatch.setattr(db_session, "owner_session_factory", lambda: db)
    evaluate.main(["--years", "2017"])
    assert "2017" in capsys.readouterr().out


def test_evaluate_excludes_aberrant_building(db, demo_models):
    df = make_synth(40).assign(DataYear=2018, PropertyGFATotal=10_000)
    df["SiteEnergyUse(kBtu)"] = 5e5
    df["TotalGHGEmissions"] = 20.0
    df.loc[0, "SiteEnergyUse(kBtu)"] = 5e9
    with db() as s:
        ingest.ingest_frame(s, df, year=2018)
        metrics = evaluate.evaluate_years(s, [2018])
    # Ligne 4 non conforme + bâtiment 0 aberrant.
    assert (metrics["n_excluded"] == 2).all()
