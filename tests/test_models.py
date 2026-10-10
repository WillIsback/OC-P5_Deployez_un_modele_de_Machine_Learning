"""Tests des services de modèles (CatBoost multi-cible)."""

import sys
from pathlib import Path

import numpy as np
import pandas as pd
from catboost import CatBoostRegressor

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core import model_service
from app.schemas.api import CAT_FEATURES, FEATURE_COLUMNS, EnergyPredictionRequest


def _train(path, value=1000.0):
    rng = np.random.default_rng(0)
    n = 60
    df = pd.DataFrame({c: rng.uniform(1, 10, n) for c in FEATURE_COLUMNS})
    for c in CAT_FEATURES:
        df[c] = "x"
    y = np.log1p(value + rng.uniform(0, 100, n))
    m = CatBoostRegressor(iterations=20, depth=3, verbose=0)
    m.fit(df[FEATURE_COLUMNS], y, cat_features=CAT_FEATURES)
    m.save_model(str(path))


def test_model_service_loads_per_target(tmp_path, monkeypatch):
    p_energy = tmp_path / "energy.cbm"
    p_emiss = tmp_path / "emissions.cbm"
    _train(p_energy, 1000.0)
    _train(p_emiss, 50.0)
    monkeypatch.setitem(model_service.MODEL_PATHS, "energy", str(p_energy))
    monkeypatch.setitem(model_service.MODEL_PATHS, "emissions", str(p_emiss))
    model_service._models.clear()

    req = EnergyPredictionRequest(
        BuildingType="Office",
        PrimaryPropertyType="Office",
        Neighborhood="BALLARD",
        Latitude=47.6,
        Longitude=-122.3,
        YearBuilt=1990,
        NumberofBuildings=1,
        NumberofFloors=4,
        PropertyGFAParking=100,
        PropertyGFABuilding=1000,
        LargestPropertyUseType="Office",
        SecondLargestPropertyUseType="Retail",
        SecondLargestPropertyUseTypeGFA=10.0,
        ThirdLargestPropertyUseType="Parking",
        ThirdLargestPropertyUseTypeGFA=5.0,
        Has_NaturalGas=True,
        Has_Steam=False,
    )
    preds = model_service.predict_all(req)
    assert set(preds) == {"energy", "emissions"}
    assert preds["energy"] > 0 and preds["emissions"] > 0
