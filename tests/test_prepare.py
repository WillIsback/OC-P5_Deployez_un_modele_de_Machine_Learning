"""Préparation d'un fichier annuel : features, exclusion et split (sans base)."""

import logging

import numpy as np
import pandas as pd
from synth import make_synth

from app.db import prepare
from app.training import data_processing as dp
from app.training.pipeline import TrainPipeline


def test_feature_rows_split_matches_legacy_pipeline():
    df = make_synth(200)
    rows = prepare.build_feature_rows(df, training=True)
    legacy = TrainPipeline(df_raw=df, seed=42, test_size=0.2).split()
    assert set(rows.index[rows["split"] == "train"]) == set(legacy.idx_train)
    assert set(rows.index[rows["split"] == "test"]) == set(legacy.idx_test)


def test_feature_rows_exclude_residential_keep_outliers():
    df = make_synth(80)
    rows = prepare.build_feature_rows(df, training=True)
    residential = df.index[df["BuildingType"].str.startswith("Multifamily")]
    assert not set(residential) & set(rows.index)
    assert rows.loc[2, "exclusion_reason"] == "outlier"
    assert pd.isna(rows.loc[2, "split"])


def test_feature_rows_production_rows_have_no_split():
    rows = prepare.build_feature_rows(make_synth(40), training=False)
    assert rows["split"].isna().all()
    assert rows.loc[4, "exclusion_reason"] == "non_compliant"
    assert set(rows["exclusion_reason"].dropna()) <= {
        "non_compliant",
        "aberrant_energy",
        "aberrant_emissions",
    }


def test_feature_rows_training_without_eligible_building_has_no_split():
    df = make_synth(40).assign(BuildingType="Multifamily LR (1-4)")
    rows = prepare.build_feature_rows(df, training=True)
    assert rows.empty
    assert "split" in rows.columns


def test_feature_rows_skip_missing_required_feature(caplog):
    df = make_synth(40)
    df.loc[0, "Latitude"] = np.nan
    with caplog.at_level(logging.WARNING):
        rows = prepare.build_feature_rows(df, training=False)
    assert 0 not in rows.index
    assert "feature obligatoire manquante" in caplog.text


def test_flag_production_exclusion_flags_non_compliant_and_aberrations():
    df = pd.DataFrame(
        {
            "ComplianceStatus": ["Compliant", "Not Compliant"] + ["Compliant"] * 4,
            "PropertyGFATotal": [10_000, 10_000, 10_000, 10_000, 10_000, 0],
            "SiteEnergyUse(kBtu)": [5e5, 5e5, 5e9, 5e3, 5e5, 5e5],
            "TotalGHGEmissions": [20.0, 20.0, 20.0, 20.0, 4_000.0, 20.0],
        }
    )
    assert dp.flag_production_exclusion(df).tolist() == [
        None,
        "non_compliant",
        "aberrant_energy",  # 500 000 kBtu/sf
        "aberrant_energy",  # 0,5 kBtu/sf
        "aberrant_emissions",  # 400 kg/sf
        None,  # surface inconnue : pas d'intensité calculable
    ]
