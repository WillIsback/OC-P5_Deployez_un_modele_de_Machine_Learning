"""Tests de la préparation brut → building_features."""

import logging

import numpy as np
import pytest
from sqlalchemy import func, select
from synth import make_synth

from app.db import ingest, prepare
from app.db import session as db_session
from app.db.models import BuildingFeatures, BuildingRecordRaw
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
    assert rows.loc[2, "dataset_role"] == "training"


def test_feature_rows_production_has_no_eligibility():
    rows = prepare.build_feature_rows(make_synth(40), training=False)
    assert (rows["dataset_role"] == "production").all()
    assert not rows["is_training_eligible"].any()
    assert rows["split"].isna().all()
    assert rows["exclusion_reason"].isna().all()


def test_feature_rows_skip_missing_required_feature(caplog):
    df = make_synth(40)
    df.loc[0, "Latitude"] = np.nan
    with caplog.at_level(logging.WARNING):
        rows = prepare.build_feature_rows(df, training=False)
    assert 0 not in rows.index
    assert "feature obligatoire manquante" in caplog.text


@pytest.mark.db
def test_prepare_year_writes_features_idempotently(db):
    df = make_synth(80)
    with db() as s:
        ingest.ingest_frame(s, df, year=2016, source_file="s.csv")
        n = prepare.prepare_year(s, 2016)
        assert n == prepare.prepare_year(s, 2016)
        assert s.scalar(select(func.count()).select_from(BuildingFeatures)) == n
        residential = s.scalar(
            select(func.count())
            .select_from(BuildingFeatures)
            .join(BuildingRecordRaw, BuildingRecordRaw.id == BuildingFeatures.record_id)
            .where(BuildingRecordRaw.building_type.like("Multifamily%"))
        )
        assert residential == 0


@pytest.mark.db
def test_prepare_year_without_raw_data_fails(db):
    with db() as s, pytest.raises(RuntimeError, match="ingest"):
        prepare.prepare_year(s, 2018)


@pytest.mark.db
def test_prepare_main(db, monkeypatch):
    with db() as s:
        ingest.ingest_frame(s, make_synth(30), year=2016, source_file="s.csv")
    monkeypatch.setattr(db_session, "owner_session_factory", lambda: db)
    prepare.main(["--year", "2016"])
    with db() as s:
        assert s.scalar(select(func.count()).select_from(BuildingFeatures)) > 0
