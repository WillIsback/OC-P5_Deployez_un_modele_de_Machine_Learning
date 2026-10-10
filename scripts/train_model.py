"""Generate a demo CatBoost model for the Seattle building energy API.

This script trains a ``CatBoostRegressor`` on **synthetic** data that reproduces
the feature layout of the reference notebook ``OC-Ai-Engineer-P3`` so the API can
run end-to-end without the real dataset.

Replace this with your real training pipeline (see the notebook: filters F0->F11,
``df_clean`` columns, ``preparer_catboost``, ``TransformedTargetRegressor`` with
``func=np.log1p, inverse_func=np.expm1``). Keep the same feature layout and the
log1p target transform so ``app/core/model.service.py`` stays valid.
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd
from catboost import CatBoostRegressor

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core import model_service

ROWS = 2000
rng = np.random.default_rng(42)

BUILDING_TYPES = ["Commercial", "Office", "Warehouse", "Retail"]
PROPERTY_TYPES = ["Office", "Warehouse/Storage", "Retail", "Service", "Parking"]
NEIGHBORHOODS = ["Ballard", "Capitol Hill", "Downtown", "Fremont", "Queen Anne"]
USE_TYPES = ["Office", "Warehouse", "Retail", "Service", "Parking", "Food Service"]

data = {
    "BuildingType": rng.choice(BUILDING_TYPES, ROWS),
    "PrimaryPropertyType": rng.choice(PROPERTY_TYPES, ROWS),
    "Neighborhood": rng.choice(NEIGHBORHOODS, ROWS),
    "Latitude": rng.uniform(47.48, 47.72, ROWS),
    "Longitude": rng.uniform(-122.4, -122.25, ROWS),
    "YearBuilt": rng.integers(1900, 2020, ROWS),
    "NumberofBuildings": rng.integers(1, 4, ROWS).astype(float),
    "NumberofFloors": rng.integers(1, 15, ROWS),
    "PropertyGFAParking": rng.integers(0, 50000, ROWS),
    "PropertyGFABuilding(s)": rng.integers(500, 100000, ROWS),
    "LargestPropertyUseType": rng.choice(NEIGHBORHOODS, ROWS),  # placeholder name reuse
    "SecondLargestPropertyUseType": rng.choice(USE_TYPES, ROWS),
    "SecondLargestPropertyUseTypeGFA": rng.uniform(0, 30000, ROWS),
    "ThirdLargestPropertyUseType": rng.choice(USE_TYPES, ROWS),
    "ThirdLargestPropertyUseTypeGFA": rng.uniform(0, 20000, ROWS),
    "Has_NaturalGas": rng.integers(0, 2, ROWS),
    "Has_Steam": rng.integers(0, 2, ROWS),
}
df = pd.DataFrame(data)
# Correct the placeholder column to realistic building-use values.
df["LargestPropertyUseType"] = rng.choice(USE_TYPES[:3], ROWS)

# Synthetic target: plausible energy consumption (kBtu/year).
gfa = df["PropertyGFABuilding(s)"]
df["SiteEnergyUse(kBtu)"] = (
    3.0 * gfa
    + 8000.0 * df["NumberofFloors"]
    + (df["Has_NaturalGas"] > 0) * 120000.0
    + (df["Has_Steam"] > 0) * 200000.0
    + rng.normal(0, 30000, ROWS)
).clip(lower=1.0)

X = df[model_service.FEATURE_COLUMNS]
y = df["SiteEnergyUse(kBtu)"]
y_log = np.log1p(y)

model = CatBoostRegressor(
    iterations=500,
    learning_rate=0.1,
    depth=6,
    loss_function="RMSE",
    random_seed=42,
    verbose=100,
)
model.fit(X, y_log, cat_features=model_service.CAT_FEATURES)

import os

os.makedirs(os.path.dirname(model_service.MODEL_PATH), exist_ok=True)
model.save_model(model_service.MODEL_PATH)
print(f"Demo model saved to {model_service.MODEL_PATH}")
print(f"Trained on {len(df)} rows, log1p target, cat_features={model_service.CAT_FEATURES}.")
