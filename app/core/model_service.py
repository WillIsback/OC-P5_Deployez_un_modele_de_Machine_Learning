"""CatBoost service for predicting the energy consumption of Seattle buildings.

The trained model is a ``CatBoostRegressor`` trained on the log1p-transformed
target ``SiteEnergyUse(kBtu)`` (as in the reference notebook OC-Ai-Engineer-P3).
At prediction time the log1p output is converted back to real units with
``expm1``.
"""

import os
import threading

import numpy as np
import pandas as pd
from catboost import CatBoostRegressor, Pool

from ..schemas.api import CAT_FEATURES, EnergyPredictionRequest

MODEL_PATH = os.getenv("MODEL_PATH", "models/energy_use_catboost.cbm")

# Order must match the columns used at training time (df_clean minus the
# targets, then stacked with the connection flags).
FEATURE_COLUMNS = [
    "BuildingType",
    "PrimaryPropertyType",
    "Neighborhood",
    "Latitude",
    "Longitude",
    "YearBuilt",
    "NumberofBuildings",
    "NumberofFloors",
    "PropertyGFAParking",
    "PropertyGFABuilding(s)",
    "LargestPropertyUseType",
    "SecondLargestPropertyUseType",
    "SecondLargestPropertyUseTypeGFA",
    "ThirdLargestPropertyUseType",
    "ThirdLargestPropertyUseTypeGFA",
    "Has_NaturalGas",
    "Has_Steam",
]

_model: CatBoostRegressor | None = None
_lock = threading.Lock()


def load_model() -> CatBoostRegressor:
    """Load the CatBoost model once (lazy singleton)."""
    global _model
    if _model is None:
        with _lock:
            if _model is None:
                if not os.path.exists(MODEL_PATH):
                    raise FileNotFoundError(
                        f"Model not found at {MODEL_PATH}. "
                        "Train it first with `uv run python scripts/train_model.py` "
                        "or set the MODEL_PATH environment variable."
                    )
                _model = CatBoostRegressor()
                _model.load_model(MODEL_PATH)
    return _model


def _to_dataframe(request: EnergyPredictionRequest) -> pd.DataFrame:
    data = request.model_dump()
    # Alias the Pydantic-safe field name back to the real dataset column name.
    data["PropertyGFABuilding(s)"] = data.pop("PropertyGFABuilding")
    data["Has_NaturalGas"] = int(data["Has_NaturalGas"])
    data["Has_Steam"] = int(data["Has_Steam"])
    df = pd.DataFrame([data])[FEATURE_COLUMNS]
    for col in CAT_FEATURES:
        df[col] = df[col].astype(str)
    return df


def predict_energy(request: EnergyPredictionRequest) -> float:
    """Return the predicted energy consumption in kBtu/year."""
    model = load_model()
    df = _to_dataframe(request)
    pool = Pool(df, cat_features=CAT_FEATURES)
    pred_log = model.predict(pool)
    return float(np.expm1(pred_log)[0])
