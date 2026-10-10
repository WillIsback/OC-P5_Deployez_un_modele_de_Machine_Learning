"""Tests du pipeline d'entraînement multi-cible (app.training)."""

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.training import data_processing as dp


def make_synth(n: int = 80, seed: int = 0) -> pd.DataFrame:
    """DataFrame brut synthétique au format du benchmark Seattle."""
    rng = np.random.default_rng(seed)
    n_multi = n // 8
    n_other = n - n_multi
    nonres_types = ["NonResidential", "Commercial", "Mixed Use"]
    building_type = (nonres_types * n_other)[:n_other] + [
        "Multifamily LR (1-4)"
    ] * n_multi
    return pd.DataFrame(
        {
            "BuildingType": building_type,
            "PrimaryPropertyType": rng.choice(
                ["Office", "Retail Store", "Warehouse"], n
            ),
            "Neighborhood": rng.choice(["BALLARD", "Downtown", "Fremont"], n),
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
            "ZipCode": ["98101"] * n,
            "CouncilDistrictCode": [1] * n,
            "ListOfAllPropertyUseTypes": ["Office"] * n,
            "ComplianceStatus": ["Compliant"] * n,
            "DefaultData": [False] * n,
            "Outlier": ["None"] * n,
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
