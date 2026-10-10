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
    kumo_service.load_model()
    kumo_service.load_model()
    assert kumo_service._model is not None


def test_predict_all_targets():
    preds = kumo_service.predict_all(SAMPLE_INPUT)
    assert set(preds) == set(TARGETS)


def test_predict_batch_returns_array():
    rows = []
    for _ in range(3):
        data = SAMPLE_INPUT.model_dump()
        data["PropertyGFABuilding(s)"] = data.pop("PropertyGFABuilding")
        rows.append(data)
    df = pd.DataFrame(rows)[FEATURE_COLUMNS]
    preds = kumo_service.predict_batch(df, "energy")
    assert isinstance(preds, np.ndarray)
    assert preds.shape == (3,)
    assert (preds > 0).all()
