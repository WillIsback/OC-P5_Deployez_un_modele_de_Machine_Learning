"""Tests du gate de performance (app.training.score_validation)."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.training.score_validation import validate_scores


def _scores(energy=(0.30, 40.0), emissions=(0.15, 45.0)):
    def block(r2, medape):
        return {"catboost": {"R2": r2, "MAE": 2.0, "MedAE": 1.0, "MedAPE_pct": medape}}

    return {
        "targets": {
            "energy": {"unit": "kBtu/an", "models": block(*energy)},
            "emissions": {"unit": "t CO2e/an", "models": block(*emissions)},
        }
    }


def test_validate_passes_when_no_regression():
    s = _scores()
    assert validate_scores(s, s) == []


def test_validate_fails_on_medape_increase():
    cur = _scores(energy=(0.30, 46.0))
    base = _scores(energy=(0.30, 40.0))
    violations = validate_scores(cur, base)
    assert any("energy" in v and "MedAPE_pct" in v for v in violations)


def test_validate_fails_on_r2_drop():
    cur = _scores(emissions=(0.10, 45.0))
    base = _scores(emissions=(0.20, 45.0))
    violations = validate_scores(cur, base)
    assert any("emissions" in v and "R2" in v for v in violations)


def test_validate_within_margins_passes():
    base = _scores()
    cur = _scores(energy=(0.30, 44.9), emissions=(0.11, 49.9))
    assert validate_scores(cur, base) == []


def test_validate_missing_target_fails():
    cur = _scores()
    del cur["targets"]["emissions"]
    violations = validate_scores(cur, _scores())
    assert any("emissions" in v for v in violations)


def test_validate_missing_metric_fails():
    cur = _scores()
    del cur["targets"]["energy"]["models"]["catboost"]["R2"]
    violations = validate_scores(cur, _scores())
    assert any("energy" in v and "R2" in v for v in violations)


def test_validate_missing_model_fails():
    cur = _scores()
    del cur["targets"]["energy"]["models"]["catboost"]
    violations = validate_scores(cur, _scores())
    assert any("energy" in v for v in violations)
