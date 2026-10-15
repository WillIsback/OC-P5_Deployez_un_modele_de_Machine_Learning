"""Tests du chargement du jeu d'entraînement depuis Postgres."""

import pytest
from synth import make_synth

from app.db import ingest, prepare
from app.db.training_data import load_training_data
from app.schemas.api import FEATURE_COLUMNS
from app.training.pipeline import TrainPipeline

pytestmark = pytest.mark.db


def test_load_training_data_matches_prepared_split(db):
    df = make_synth(200)
    with db() as s:
        ingest.ingest_frame(s, df, year=2016, source_file="s.csv")
        prepare.prepare_year(s, 2016)
        data = load_training_data(s)
    assert list(data.X.columns) == FEATURE_COLUMNS
    assert list(data.Y.columns) == ["SiteEnergyUse(kBtu)", "TotalGHGEmissions"]
    assert set(data.split.unique()) == {"train", "test"}
    legacy = TrainPipeline(df_raw=df, seed=42, test_size=0.2).split()
    assert (data.split == "train").sum() == len(legacy.idx_train)


def test_load_training_data_empty_raises(db):
    with db() as s, pytest.raises(RuntimeError, match="app.db.prepare"):
        load_training_data(s)


def test_pipeline_accepts_training_data(db):
    with db() as s:
        ingest.ingest_frame(s, make_synth(160), year=2016, source_file="s.csv")
        prepare.prepare_year(s, 2016)
        data = load_training_data(s)
    pipe = TrainPipeline(training_data=data).split().feature_engineering()
    assert len(pipe.X_train) == (data.split == "train").sum()
    assert list(pipe.X_test.columns) == FEATURE_COLUMNS
    assert pipe.Y_train.index.equals(pipe.X_train.index)
