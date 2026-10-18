"""Tests du service Kumo-Tabular (zero-shot, multi-cible, par lots)."""

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core import _kumo_context, kumo_service
from app.schemas.api import FEATURE_COLUMNS, TARGETS, EnergyPredictionRequest

SAMPLE_INPUT = EnergyPredictionRequest(
    BuildingType="Commercial",
    PrimaryPropertyType="Office",
    Neighborhood="Ballard",
    Latitude=47.62,
    Longitude=-122.35,
    YearBuilt=1990,
    NumberofBuildings=1,
    NumberofFloors=4,
    PropertyGFAParking=5000,
    PropertyGFABuilding=15000,
    LargestPropertyUseType="Office",
    SecondLargestPropertyUseType="Retail",
    SecondLargestPropertyUseTypeGFA=3000.0,
    ThirdLargestPropertyUseType="Parking",
    ThirdLargestPropertyUseTypeGFA=2000.0,
    Has_NaturalGas=True,
    Has_Steam=False,
)


def test_is_available():
    assert kumo_service.is_available()


@pytest.mark.parametrize("target", list(TARGETS))
def test_predict_positive_per_target(target):
    value = kumo_service.predict(SAMPLE_INPUT, target)
    assert isinstance(value, float)
    assert value > 0


def test_single_shared_model_instance():
    assert kumo_service.load_model() is kumo_service.load_model()


def test_predict_all_targets():
    preds = kumo_service.predict_all(SAMPLE_INPUT)
    assert set(preds) == set(TARGETS)


def test_context_is_target_specific():
    assert kumo_service._context_table("energy") is not kumo_service._context_table(
        "emissions"
    )


def test_predict_batch_distinct_rows():
    rows = []
    for gfa in (500, 15_000, 60_000):
        data = SAMPLE_INPUT.model_dump()
        data["PropertyGFABuilding(s)"] = data.pop("PropertyGFABuilding")
        data["PropertyGFABuilding(s)"] = gfa
        rows.append(data)
    df = pd.DataFrame(rows)[FEATURE_COLUMNS]
    preds = kumo_service.predict_batch(df, "energy")
    assert isinstance(preds, np.ndarray)
    assert preds.shape == (3,)
    assert (preds > 0).all()
    assert len(set(preds.tolist())) > 1
    assert preds[2] > preds[0]


def test_predict_batch_rejects_1d():
    with pytest.raises(ValueError):
        kumo_service.predict_batch(np.array([1.0, 2.0, 3.0]), "energy")


def test_explicit_context_is_not_cached(tmp_path):
    path = tmp_path / "ctx.csv"
    pd.read_csv(_kumo_context.DEFAULT_CONTEXT_PATH).iloc[:20].to_csv(path, index=False)
    cached = dict(kumo_service._context_tables)
    first = kumo_service._context_table("energy", path)
    assert first is not kumo_service._context_table("energy", path)
    assert kumo_service._context_tables == cached


def test_real_context_gives_realistic_magnitudes(tmp_path):
    """Non-régression #68 : un contexte synthétique donnait des émissions ×500."""
    full = pd.read_csv(_kumo_context.DEFAULT_CONTEXT_PATH)
    path = tmp_path / "ctx.csv"
    full.iloc[:200].to_csv(path, index=False)
    query = full.iloc[200:230]  # bâtiments absents du contexte
    for target, meta in TARGETS.items():
        pred = kumo_service.predict_batch(
            query[FEATURE_COLUMNS], target, context_path=path
        )
        ratio = np.median(pred / query[meta["column"]].to_numpy())
        assert 0.2 < ratio < 5, f"{target} : prédit/réel médian = {ratio:.2f}"


def test_missing_context_file_raises(monkeypatch, tmp_path):
    with pytest.raises(FileNotFoundError):
        kumo_service.predict_batch(
            pd.DataFrame(columns=FEATURE_COLUMNS),
            "energy",
            context_path=tmp_path / "absent.csv",
        )


def test_unknown_target_rejected():
    with pytest.raises(KeyError):
        _kumo_context.build_context_df("water")
    with pytest.raises(KeyError):
        kumo_service._context_table("water")
    with pytest.raises(KeyError):
        kumo_service.predict_batch(pd.DataFrame(columns=FEATURE_COLUMNS), "water")


def test_predict_batch_accepts_array():
    data = SAMPLE_INPUT.model_dump()
    data["PropertyGFABuilding(s)"] = data.pop("PropertyGFABuilding")
    X = pd.DataFrame([data])[FEATURE_COLUMNS].to_numpy(dtype=object)
    preds = kumo_service.predict_batch(X, "energy")
    assert preds.shape == (1,)
    assert preds[0] > 0


def test_is_available_false_when_load_fails(monkeypatch):
    def boom():
        raise ImportError("sdm absent")

    monkeypatch.setattr(kumo_service, "load_model", boom)
    assert kumo_service.is_available() is False


def test_predict_batch_accepts_missing_secondary_gfa():
    """Une ligne sans 2e/3e usage (GFA à None, cas de 83 % des bâtiments 2019)."""
    data = SAMPLE_INPUT.model_dump()
    data["PropertyGFABuilding(s)"] = data.pop("PropertyGFABuilding")
    data["SecondLargestPropertyUseTypeGFA"] = None
    data["ThirdLargestPropertyUseTypeGFA"] = None
    preds = kumo_service.predict_batch(pd.DataFrame([data])[FEATURE_COLUMNS], "energy")
    assert preds.shape == (1,)
    assert np.isfinite(preds[0])
