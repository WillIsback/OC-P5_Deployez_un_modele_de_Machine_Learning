"""Tests unitaires du pipeline d'entraînement CatBoost + logging MLflow."""

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from mlflow.tracking import MlflowClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts import train_model_seattle as train


def make_synth(n: int = 80, seed: int = 0) -> pd.DataFrame:
    """DataFrame brut synthétique au format du benchmark Seattle."""
    rng = np.random.default_rng(seed)
    n_multi = n // 8
    n_other = n - n_multi
    bt = ["Multifamily (4+ units)"] * n_multi + list(
        rng.choice(["Commercial", "Office", "Industrial", "Warehouse"], n_other)
    )
    df = pd.DataFrame(
        {
            "BuildingType": bt,
            "PrimaryPropertyType": rng.choice(
                ["Office", "Retail", "Warehouse/Storage", "Service"], n
            ),
            "Neighborhood": rng.choice(["ballard", "Downtown ", " Capitol Hill"], n),
            "Latitude": rng.uniform(47.48, 47.72, n),
            "Longitude": rng.uniform(-122.4, -122.25, n),
            "YearBuilt": rng.integers(1930, 2020, n),
            "NumberofBuildings": rng.integers(1, 3, n).astype(float),
            "NumberofFloors": rng.integers(1, 8, n),
            "PropertyGFAParking": rng.integers(0, 20000, n),
            "PropertyGFABuilding(s)": rng.integers(500, 40000, n),
            "LargestPropertyUseType": rng.choice(["Office", "Warehouse", "Retail"], n),
            "SecondLargestPropertyUseType": rng.choice(["Retail", "Service"], n),
            "SecondLargestPropertyUseTypeGFA": rng.uniform(0, 12000, n),
            "ThirdLargestPropertyUseType": rng.choice(["Parking", "Service"], n),
            "ThirdLargestPropertyUseTypeGFA": rng.uniform(0, 8000, n),
            "Outlier": [""] * n,
            "ComplianceStatus": ["Compliant"] * n,
            "DefaultData": [False] * n,
        }
    )
    gfa = df["PropertyGFABuilding(s)"]
    target = (3.0 * gfa + 5000 * df["NumberofFloors"] + 30000).clip(lower=1)
    # 10 % de cibles nulles -> doivent être filtrées par F10
    zero_idx = rng.choice(n, size=n // 10, replace=False)
    target.iloc[zero_idx] = 0.0
    df["SiteEnergyUse(kBtu)"] = target
    df["NaturalGas(kBtu)"] = np.where(
        rng.random(n) < 0.6, rng.uniform(0, 80000, n), 0
    ).round(0)
    df["SteamUse(kBtu)"] = np.where(
        rng.random(n) < 0.2, rng.uniform(0, 150000, n), 0
    ).round(0)
    return df


# --------------------------------------------------------------------------- #
# Pipeline de nettoyage / préparation
# --------------------------------------------------------------------------- #
def test_build_clean_excludes_multifamily():
    clean = train.build_clean(make_synth())
    assert "BuildingType" in clean.columns
    assert not clean["BuildingType"].str.contains("Multifamily").any()


def test_build_clean_keeps_positive_target_only():
    clean = train.build_clean(make_synth())
    assert (clean["SiteEnergyUse(kBtu)"] > 0).all()


def test_build_clean_drops_pii_and_leakage():
    clean = train.build_clean(make_synth())
    for col in train.PII_COLUMNS + train.DATA_LEAKAGE_COLUMNS:
        assert col not in clean.columns


def test_build_clean_normalizes_neighborhood():
    clean = train.build_clean(make_synth())
    assert (
        clean["Neighborhood"] == clean["Neighborhood"].str.strip().str.upper()
    ).all()


def test_build_flags():
    df = make_synth()
    clean = train.build_clean(df)
    flags = train.build_flags(df, clean)
    assert set(flags.columns) == {"Has_NaturalGas", "Has_Steam"}
    assert flags.index.equals(clean.index)
    assert set(flags["Has_NaturalGas"].unique()).issubset({0, 1})
    assert set(flags["Has_Steam"].unique()).issubset({0, 1})


def test_prepare_catboost_types_and_flags():
    df = make_synth()
    clean = train.build_clean(df)
    X_features = clean.drop(columns=["SiteEnergyUse(kBtu)"], errors="ignore")
    flags = train.build_flags(df, clean)
    X = train.prepare_catboost(X_features, flags)
    for col in train.CAT_FEATURES:
        assert pd.api.types.is_string_dtype(X[col])  # catégorielles forcées en str
    assert {"Has_NaturalGas", "Has_Steam"}.issubset(X.columns)


def test_prepare_dataset_layout():
    df = make_synth(60)
    X, y_log, clean = train.prepare_dataset(df)
    assert list(X.columns) == train.FEATURE_COLUMNS
    assert (y_log > 0).all()
    expected = np.log1p(clean["SiteEnergyUse(kBtu)"])
    np.testing.assert_allclose(y_log.values, expected.values)


# --------------------------------------------------------------------------- #
# Métriques
# --------------------------------------------------------------------------- #
def test_mlflow_key_sanitizes_percent():
    assert train._mlflow_key("MedAPE_%") == "MedAPE_pct"
    assert train._mlflow_key("R2") == "R2"


def test_metrics_reelles():
    y_true = np.array([100.0, 200.0, 100.0])
    y_pred = np.array([110.0, 200.0, 100.0])
    m = train.metrics_reelles(y_true, y_pred)
    assert m["MAE"] == pytest.approx(10 / 3)
    assert m["MedAE"] == 0.0


# --------------------------------------------------------------------------- #
# Entraînement : fit, CV, tune
# --------------------------------------------------------------------------- #
def test_train_with_early_stopping():
    df = make_synth(60)
    X, y_log, _ = train.prepare_dataset(df)
    params = {"iterations": 50, "learning_rate": 0.1, "depth": 4, "l2_leaf_reg": 3.0}
    model = train.train_with_early_stopping(
        X, y_log, X.iloc[:20], y_log.iloc[:20], params, train.CAT_FEATURES
    )
    assert model.tree_count_ > 0


def test_cross_validate_energy():
    df = make_synth(90)
    X, y_log, _ = train.prepare_dataset(df)
    params = {"iterations": 40, "learning_rate": 0.1, "depth": 4, "l2_leaf_reg": 3.0}
    cv = train.cross_validate_energy(X, y_log, params, train.CAT_FEATURES, n_splits=2)
    assert set(cv) == {"mean", "std", "per_fold"}
    assert len(cv["per_fold"]) == 2
    assert cv["mean"]["R2"] > 0
    assert cv["mean"]["MedAPE_%"] > 0


def test_tune_restricted_grid():
    df = make_synth(70)
    X, y_log, _ = train.prepare_dataset(df)
    grid = {"iterations": [40], "learning_rate": [0.1, 0.2], "depth": [4]}
    best_params, best = train.tune(X, y_log, train.CAT_FEATURES, grid=grid)
    assert set(best_params) == set(grid)
    assert {"train", "val"}.issubset(best)


# --------------------------------------------------------------------------- #
# MLflow
# --------------------------------------------------------------------------- #
def test_mlflow_log_metrics(tmp_path):
    import mlflow

    uri = f"sqlite:///{tmp_path / 'mlflow.db'}"
    mlflow.set_tracking_uri(uri)
    mlflow.set_experiment("unit-test")
    with mlflow.start_run():
        train.log_mlflow_metrics("cv_train", {"MedAPE_%": 3.2, "R2": 0.96})
        mlflow.log_metric("test_R2", 0.97)
    exp = MlflowClient(uri).get_experiment_by_name("unit-test")
    run = MlflowClient(uri).search_runs(experiment_ids=[exp.experiment_id])[0]
    metrics = run.data.metrics
    assert metrics["cv_train_MedAPE_pct"] == pytest.approx(3.2)
    assert metrics["cv_train_R2"] == pytest.approx(0.96)
    assert metrics["test_R2"] == pytest.approx(0.97)
