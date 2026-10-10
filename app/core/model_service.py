"""CatBoost multi-cible (consommation + émissions) — chargement paresseux."""

from __future__ import annotations

import os
import threading

import numpy as np
import pandas as pd
from catboost import CatBoostRegressor, Pool

from ..schemas.api import (
    CAT_FEATURES,
    FEATURE_COLUMNS,
    TARGETS,
    EnergyPredictionRequest,
)

MODEL_PATHS = {
    "energy": os.getenv("MODEL_PATH_ENERGY", "models/energy.cbm"),
    "emissions": os.getenv("MODEL_PATH_EMISSIONS", "models/emissions.cbm"),
}

_models: dict[str, CatBoostRegressor] = {}
_lock = threading.Lock()


def load_model(target: str) -> CatBoostRegressor:
    """Charge (une fois) le CatBoost de la cible ``target``."""
    if target not in MODEL_PATHS:
        raise KeyError(f"Cible inconnue : {target}")
    model = _models.get(target)
    if model is None:
        with _lock:
            model = _models.get(target)
            if model is None:
                path = MODEL_PATHS[target]
                if not os.path.exists(path):
                    raise FileNotFoundError(
                        f"Modèle {target} introuvable à {path}. "
                        "Entraînez-le avec `uv run python -m app.training`."
                    )
                model = CatBoostRegressor()
                model.load_model(path)
                _models[target] = model
    return model


def _to_dataframe(request: EnergyPredictionRequest) -> pd.DataFrame:
    data = request.model_dump()
    data["PropertyGFABuilding(s)"] = data.pop("PropertyGFABuilding")
    data["Has_NaturalGas"] = int(data["Has_NaturalGas"])
    data["Has_Steam"] = int(data["Has_Steam"])
    df = pd.DataFrame([data])[FEATURE_COLUMNS]
    for col in CAT_FEATURES:
        df[col] = df[col].astype(str)
    return df


def predict(request: EnergyPredictionRequest, target: str) -> float:
    """Prédiction pour une cible (unités réelles via expm1)."""
    model = load_model(target)
    pool = Pool(_to_dataframe(request), cat_features=CAT_FEATURES)
    return float(np.expm1(model.predict(pool))[0])


def predict_all(request: EnergyPredictionRequest) -> dict[str, float]:
    """Prédiction pour toutes les cibles."""
    return {target: predict(request, target) for target in TARGETS}
