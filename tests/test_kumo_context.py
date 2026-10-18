"""Tests du contexte Kumo-Tabular : le jeu d'entraînement de CatBoost."""

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core import _kumo_context as kc
from app.schemas.api import FEATURE_COLUMNS, TARGETS

TARGET_COLUMNS = [t["column"] for t in TARGETS.values()]


def _training_set(n: int = 40) -> tuple[pd.DataFrame, pd.DataFrame]:
    rng = np.random.default_rng(0)
    X = pd.DataFrame(
        {c: rng.integers(1, 100, n) for c in FEATURE_COLUMNS},
        index=pd.Index(range(100, 100 + n), name="building_id"),
    )
    Y = pd.DataFrame(
        {c: rng.uniform(1, 1000, n) for c in TARGET_COLUMNS}, index=X.index
    )
    return X, Y


@pytest.fixture
def context_file(tmp_path):
    X, Y = _training_set()
    path = tmp_path / "kumo_context.csv"
    kc.write_context(X, Y, path)
    return path


def test_write_context_keeps_features_and_both_targets(context_file):
    df = pd.read_csv(context_file)
    assert list(df.columns) == FEATURE_COLUMNS + TARGET_COLUMNS
    assert len(df) == 40


def test_write_context_creates_parent_dir(tmp_path):
    X, Y = _training_set(3)
    path = tmp_path / "absent" / "kumo_context.csv"
    kc.write_context(X, Y, path)
    assert path.exists()


@pytest.mark.parametrize("target", list(TARGETS))
def test_build_context_df_uses_every_row_by_default(context_file, target, monkeypatch):
    monkeypatch.delenv("KUMO_CONTEXT_SIZE", raising=False)
    df = kc.build_context_df(target, path=context_file)
    assert list(df.columns) == FEATURE_COLUMNS + [TARGETS[target]["column"]]
    assert len(df) == 40


def test_build_context_df_samples_reproducibly(context_file):
    a = kc.build_context_df("energy", path=context_file, size=10)
    b = kc.build_context_df("emissions", path=context_file, size=10)
    assert len(a) == 10
    # Même échantillon pour les deux cibles et d'un appel à l'autre.
    pd.testing.assert_frame_equal(a[FEATURE_COLUMNS], b[FEATURE_COLUMNS])
    pd.testing.assert_frame_equal(
        a, kc.build_context_df("energy", path=context_file, size=10)
    )


def test_build_context_df_size_above_rows_keeps_all(context_file):
    assert len(kc.build_context_df("energy", path=context_file, size=500)) == 40


def test_build_context_df_rejects_unknown_target(context_file):
    with pytest.raises(KeyError):
        kc.build_context_df("water", path=context_file)


def test_build_context_df_missing_file_explains(tmp_path):
    with pytest.raises(FileNotFoundError, match="python -m app.training"):
        kc.build_context_df("energy", path=tmp_path / "absent.csv")


def test_default_path_and_size_read_from_env(context_file, monkeypatch):
    monkeypatch.setenv("KUMO_CONTEXT_PATH", str(context_file))
    monkeypatch.setenv("KUMO_CONTEXT_SIZE", "7")
    assert len(kc.build_context_df("energy")) == 7


@pytest.mark.parametrize("raw, expected", [("", None), ("0", None), ("25", 25)])
def test_context_size_from_env(monkeypatch, raw, expected):
    monkeypatch.setenv("KUMO_CONTEXT_SIZE", raw)
    assert kc.context_size() == expected


def test_context_size_unset_means_all(monkeypatch):
    monkeypatch.delenv("KUMO_CONTEXT_SIZE", raising=False)
    assert kc.context_size() is None


@pytest.mark.parametrize("raw", ["abc", "-3"])
def test_context_size_rejects_invalid(monkeypatch, raw):
    monkeypatch.setenv("KUMO_CONTEXT_SIZE", raw)
    with pytest.raises(ValueError, match="KUMO_CONTEXT_SIZE"):
        kc.context_size()
