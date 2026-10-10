"""Tests du gate de performance (app.training.score_validation)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.training import score_validation as sv
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


def _write(path: Path, obj) -> None:
    path.write_text(json.dumps(obj), encoding="utf-8")


def test_main_ok_returns_zero(tmp_path, monkeypatch):
    scores = tmp_path / "scores.json"
    baseline = tmp_path / "baseline.json"
    _write(scores, _scores())
    _write(baseline, _scores())
    monkeypatch.setattr(sv, "DEFAULT_SCORES_PATH", scores)
    monkeypatch.setattr(sv, "DEFAULT_BASELINE_PATH", baseline)
    assert sv.main() == 0


def test_main_missing_files_returns_one(tmp_path, monkeypatch):
    monkeypatch.setattr(sv, "DEFAULT_SCORES_PATH", tmp_path / "nope.json")
    monkeypatch.setattr(sv, "DEFAULT_BASELINE_PATH", tmp_path / "nope2.json")
    assert sv.main() == 1


def test_main_regression_returns_one(tmp_path, monkeypatch):
    scores = tmp_path / "scores.json"
    baseline = tmp_path / "baseline.json"
    _write(scores, _scores(energy=(0.30, 60.0)))
    _write(baseline, _scores(energy=(0.30, 40.0)))
    monkeypatch.setattr(sv, "DEFAULT_SCORES_PATH", scores)
    monkeypatch.setattr(sv, "DEFAULT_BASELINE_PATH", baseline)
    assert sv.main() == 1
