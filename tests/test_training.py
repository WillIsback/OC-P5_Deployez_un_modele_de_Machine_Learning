"""Tests du pipeline d'entraînement multi-cible (app.training)."""

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.training import data_processing as dp
from app.training.pipeline import (
    COARSE_GRID,
    MAX_TREES_BUDGET,
    TrainPipeline,
    _candidate_sort_key,
)


def make_synth(n: int = 80, seed: int = 0) -> pd.DataFrame:
    """DataFrame brut synthétique au format du benchmark Seattle."""
    rng = np.random.default_rng(seed)
    n_multi = n // 8
    n_other = n - n_multi
    nonres_types = ["NonResidential", "Commercial", "Mixed Use"]
    building_type = (nonres_types * n_other)[:n_other] + [
        "Multifamily LR (1-4)"
    ] * n_multi
    outlier = ["None"] * n
    outlier[2] = "High outlier"
    outlier[3] = "Low outlier"
    compliance = ["Compliant"] * n
    compliance[4] = "NonCompliant"
    default_data = [False] * n
    default_data[5] = True
    return pd.DataFrame(
        {
            "BuildingType": building_type,
            "PrimaryPropertyType": rng.choice(
                ["Office", "Retail Store", "Warehouse"], n
            ),
            "Neighborhood": rng.choice(
                ["ballard", " Downtown ", "FREMONT", "Capitol Hill"], n
            ),
            "Latitude": rng.uniform(47.5, 47.7, n),
            "Longitude": rng.uniform(-122.4, -122.25, n),
            "YearBuilt": rng.integers(1930, 2020, n),
            "NumberofBuildings": rng.integers(0, 3, n).astype(float),
            "NumberofFloors": rng.integers(1, 8, n),
            "PropertyGFAParking": rng.integers(0, 20000, n),
            "PropertyGFABuilding(s)": rng.integers(500, 40000, n),
            "LargestPropertyUseType": rng.choice(["Office", "Retail"], n),
            "SecondLargestPropertyUseType": rng.choice(["Retail", "Service"], n),
            "SecondLargestPropertyUseTypeGFA": rng.uniform(0, 12000, n),
            "ThirdLargestPropertyUseType": rng.choice(["Parking", "Service"], n),
            "ThirdLargestPropertyUseTypeGFA": rng.uniform(0, 8000, n),
            "SiteEnergyUse(kBtu)": rng.uniform(1000, 500000, n),
            "TotalGHGEmissions": rng.uniform(1, 500, n),
            "NaturalGas(kBtu)": rng.uniform(0, 1000, n),
            "SteamUse(kBtu)": rng.uniform(0, 1000, n),
            "PropertyGFATotal": rng.integers(500, 40000, n),
            "LargestPropertyUseTypeGFA": rng.integers(0, 40000, n),
            "OSEBuildingID": np.arange(n),
            "PropertyName": [f"b{i}" for i in range(n)],
            "Address": [f"{i} st" for i in range(n)],
            "TaxParcelIdentificationNumber": [f"t{i}" for i in range(n)],
            "ZipCode": rng.choice(["98101", "98102", "98103"], n),
            "CouncilDistrictCode": rng.integers(1, 8, n),
            "ListOfAllPropertyUseTypes": ["Office"] * n,
            "ComplianceStatus": compliance,
            "DefaultData": default_data,
            "Outlier": outlier,
            "YearsENERGYSTARCertified": [np.nan] * n,
            "ENERGYSTARScore": rng.uniform(0, 100, n),
            "GHGEmissionsIntensity": rng.uniform(0, 10, n),
        }
    )


def test_build_clean_drops_multifamily_and_leakage():
    clean = dp.build_clean(make_synth())
    assert not clean["BuildingType"].str.startswith("Multifamily").any()
    assert "GHGEmissionsIntensity" not in clean.columns
    assert "SiteEnergyUse(kBtu)" in clean.columns
    assert "TotalGHGEmissions" in clean.columns


def test_build_clean_keeps_positive_targets_only():
    df = make_synth()
    df.loc[0, "SiteEnergyUse(kBtu)"] = 0
    df.loc[1, "TotalGHGEmissions"] = 0
    clean = dp.build_clean(df)
    assert (clean["SiteEnergyUse(kBtu)"] > 0).all()
    assert (clean["TotalGHGEmissions"] > 0).all()


def test_prepare_dataset_shapes_and_targets():
    X, Y, df_clean = dp.prepare_dataset(make_synth(120))
    assert list(X.columns) == dp.FEATURE_COLUMNS
    assert set(Y.columns) == {"SiteEnergyUse(kBtu)", "TotalGHGEmissions"}
    assert len(X) == len(Y) == len(df_clean)
    for col in dp.CAT_FEATURES:
        assert pd.api.types.is_string_dtype(X[col])


def test_build_flags_from_raw_columns():
    df = make_synth(40)
    df["NaturalGas(kBtu)"] = 0.0
    df["SteamUse(kBtu)"] = 0.0
    df.loc[df.index[0], "NaturalGas(kBtu)"] = 500.0
    clean = dp.build_clean(df)
    flags = dp.build_flags(df, clean)
    assert set(flags.columns) == {"Has_NaturalGas", "Has_Steam"}
    assert flags["Has_NaturalGas"].sum() >= 1
    assert flags["Has_Steam"].sum() == 0


def test_build_clean_removes_outliers_and_drops_column():
    clean = dp.build_clean(make_synth(80))
    assert "Outlier" not in clean.columns
    assert 2 not in clean.index
    assert 3 not in clean.index


def test_build_clean_removes_non_compliant_rows():
    clean = dp.build_clean(make_synth(80))
    assert "ComplianceStatus" not in clean.columns
    assert "DefaultData" not in clean.columns
    assert 4 not in clean.index


def test_build_clean_normalizes_neighborhood():
    clean = dp.build_clean(make_synth(80))
    assert (
        clean["Neighborhood"] == clean["Neighborhood"].str.upper().str.strip()
    ).all()
    assert "Downtown" not in clean["Neighborhood"].values


def test_build_clean_sets_min_one_building():
    df = make_synth(80)
    df.loc[0, "NumberofBuildings"] = 0
    clean = dp.build_clean(df)
    assert 0 in clean.index
    assert clean.loc[0, "NumberofBuildings"] == 1


def test_build_clean_drops_pii_columns():
    clean = dp.build_clean(make_synth(80))
    for col in dp.PII_COLUMNS:
        assert col not in clean.columns


def test_ensure_dataset_returns_existing_without_download(tmp_path):
    dest = tmp_path / "data.csv"
    dest.write_text("a,b\n1,2\n")
    result = dp.ensure_dataset(dest, url="file:///nonexistent/bogus.csv")
    assert result == dest
    assert dest.read_text() == "a,b\n1,2\n"


def test_ensure_dataset_missing_without_download_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        dp.ensure_dataset(tmp_path / "missing.csv")


def test_ensure_dataset_downloads_from_file_url(tmp_path):
    source = tmp_path / "source.csv"
    source.write_text("col\n1\n")
    dest = tmp_path / "nested" / "data.csv"
    result = dp.ensure_dataset(dest, url=source.as_uri(), download=True)
    assert result == dest
    assert dest.exists()
    assert dest.read_text() == source.read_text()


def test_ensure_dataset_download_failure_cleans_tmp(tmp_path):
    source = tmp_path / "does_not_exist.csv"
    dest = tmp_path / "nested" / "data.csv"
    with pytest.raises(RuntimeError):
        dp.ensure_dataset(dest, url=source.as_uri(), download=True)
    tmp = dest.with_suffix(dest.suffix + ".tmp")
    assert not tmp.exists()
    assert not dest.exists()


def test_pipeline_split_then_feature_engineering():
    pipe = TrainPipeline(df_raw=make_synth(200), seed=42, test_size=0.25)
    pipe.split()
    pipe.feature_engineering()
    assert len(pipe.idx_train) + len(pipe.idx_test) == len(pipe.df_clean)
    assert len(pipe.X_train) == len(pipe.Y_train) == len(pipe.idx_train)
    assert list(pipe.X_train.columns) == dp.FEATURE_COLUMNS
    assert set(pipe.Y_train.columns) == {"SiteEnergyUse(kBtu)", "TotalGHGEmissions"}
    # pas de fuite : le test n'a pas été vu à l'ajustement
    assert set(pipe.idx_train).isdisjoint(set(pipe.idx_test))


def test_pipeline_cross_validate_and_pre_tune_restrict_grid():
    pipe = TrainPipeline(df_raw=make_synth(160), seed=42, cv_splits=3)
    pipe.split().feature_engineering().cross_validate().pre_tune()
    for target in dp.TARGETS:
        assert target in pipe.cv_results
        assert pipe.cv_results[target]  # au moins une config évaluée
        assert len(pipe.cv_results[target][0]["per_fold"]) == pipe.cv_splits
        assert set(pipe.cv_results[target][0]["mean"]) == {
            "R2",
            "MAE",
            "MedAE",
            "MedAPE_%",
        }
        grid = pipe.pre_tuned_grid[target]
        # grille restreinte : pas plus de 2 valeurs par axe
        assert all(len(v) <= 2 for v in grid.values())
        # le budget "overkill" doit pouvoir mordre : cap > seuil souple
        assert grid["iterations"][0] == COARSE_GRID["iterations"][0]
        assert MAX_TREES_BUDGET < grid["iterations"][0]


def test_pipeline_fine_tune_penalizes_overkill_and_trains_final(tmp_path):
    pipe = TrainPipeline(
        df_raw=make_synth(160), seed=42, cv_splits=3, output_dir=tmp_path
    )
    pipe.split().feature_engineering().cross_validate().pre_tune()
    pipe.fine_tune().train_final()
    for target in dp.TARGETS:
        assert "depth" in pipe.best_params[target]
        assert "overfit_gap" in pipe.best_params[target]
        cbm = tmp_path / f"{target}.cbm"
        assert cbm.exists()
        assert pipe.models[target] is not None


def _cand(medape, r2, gap, overkill, n_trees, depth):
    return {
        "MedAPE_val": medape,
        "R2_val": r2,
        "overfit_gap": gap,
        "overkill": overkill,
        "n_trees": n_trees,
        "depth": depth,
    }


def test_candidate_sort_key_prefers_metrics_then_complexity():
    base = _cand(10.0, 0.8, 0.1, 0, 500, 5)
    lower_medape = _cand(5.0, 0.8, 0.1, 0, 500, 5)
    higher_r2 = _cand(10.0, 0.9, 0.1, 0, 500, 5)
    no_overkill = _cand(10.0, 0.8, 0.1, 0, 500, 5)
    overkill = _cand(10.0, 0.8, 0.1, 1, 500, 5)
    fewer_trees = _cand(10.0, 0.8, 0.1, 0, 100, 5)

    assert _candidate_sort_key(lower_medape) < _candidate_sort_key(base)
    assert _candidate_sort_key(higher_r2) < _candidate_sort_key(base)
    assert _candidate_sort_key(no_overkill) < _candidate_sort_key(overkill)
    assert _candidate_sort_key(fewer_trees) < _candidate_sort_key(base)


def test_candidate_sort_key_metric_priority_beats_overkill():
    # Meilleur MedAPE gagne même s'il est overkill (la métrique prime)
    better_medape_overkill = _cand(5.0, 0.5, -0.1, 1, 1500, 6)
    worse_medape_clean = _cand(10.0, 0.9, 0.0, 0, 400, 4)
    assert (
        min([worse_medape_clean, better_medape_overkill], key=_candidate_sort_key)
        is better_medape_overkill
    )

    # MedAPE prime sur R2 (et sur overkill/complexité)
    low_medape_ugly = _cand(5.0, 0.1, 0.0, 1, 900, 6)
    high_medape_pretty = _cand(9.0, 0.99, 0.0, 0, 200, 3)
    assert (
        min([high_medape_pretty, low_medape_ugly], key=_candidate_sort_key)
        is low_medape_ugly
    )

    # R2 prime sur overkill/complexité à MedAPE égal
    better_r2_overkill = _cand(7.0, 0.9, 0.0, 1, 1500, 8)
    worse_r2_clean = _cand(7.0, 0.2, 0.0, 0, 100, 3)
    assert (
        min([worse_r2_clean, better_r2_overkill], key=_candidate_sort_key)
        is better_r2_overkill
    )
