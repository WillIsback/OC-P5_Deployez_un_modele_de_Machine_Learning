"""Évaluation projetée : prédictions batch + métriques depuis la vue."""

import pandas as pd
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


def test_exclusion_reason_flags_non_compliant_and_aberrations():
    df = pd.DataFrame(
        {
            "compliance_status": ["Compliant", "Not Compliant", "Compliant"]
            + ["Compliant"] * 3,
            "property_gfa_total": [10_000, 10_000, 10_000, 10_000, 10_000, 0],
            "actual_energy_kbtu": [5e5, 5e5, 5e9, 5e3, 5e5, 5e5],
            "actual_ghg_tco2e": [20.0, 20.0, 20.0, 20.0, 4_000.0, 20.0],
        }
    )
    assert evaluate.exclusion_reason(df).tolist() == [
        None,
        "non_compliant",
        "aberrant_energy",  # 500 000 kBtu/sf
        "aberrant_energy",  # 0,5 kBtu/sf
        "aberrant_emissions",  # 400 kg/sf
        None,  # surface inconnue : pas d'intensité calculable
    ]


def test_evaluate_excludes_aberrant_building(db, demo_models):
    df = make_synth(40).assign(DataYear=2018, PropertyGFATotal=10_000)
    df["SiteEnergyUse(kBtu)"] = 5e5
    df["TotalGHGEmissions"] = 20.0
    df.loc[0, "SiteEnergyUse(kBtu)"] = 5e9
    with db() as s:
        ingest.ingest_frame(s, df, year=2018, source_file="2018.csv")
        prepare.prepare_year(s, 2018)
        metrics = evaluate.evaluate_years(s, [2018])
    # Ligne 4 non conforme + bâtiment 0 aberrant.
    assert (metrics["n_excluded"] == 2).all()
