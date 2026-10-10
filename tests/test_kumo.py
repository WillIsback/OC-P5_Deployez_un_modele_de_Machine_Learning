"""Tests du service Kumo-Tabular (zero-shot, multi-cible, par lots)."""

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core import kumo_service
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
