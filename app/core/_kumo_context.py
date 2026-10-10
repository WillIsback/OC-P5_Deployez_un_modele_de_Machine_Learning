"""Données de contexte synthétiques pour l'inférence zero-shot Kumo-Tabular.

Ces 30 lignes déterministes (seed 42) servent d'exemples *in-context* au
modèle Kumo-Tabular.  Les caractéristiques sont tirées aléatoirement de façon
reproductible ; la cible énergie suit un heuristique simple (proportionnelle à
la surface), et la cible émissions en dérive.
"""

import numpy as np
import pandas as pd

from ..schemas.api import FEATURE_COLUMNS, TARGETS

_N_CONTEXT = 30
_RNG = np.random.default_rng(42)

_GFA = _RNG.integers(500, 40_000, _N_CONTEXT)  # sq.ft gross floor area

_CONTEXT_ENERGY: np.ndarray = (
    10.0 * _GFA + _RNG.normal(0, 20_000, _N_CONTEXT) + 30_000
).clip(10_000)

_ENERGY_COLUMN = TARGETS["energy"]["column"]

_CONTEXT_DATA: dict[str, list] = {
    "BuildingType": _RNG.choice(
        ["Commercial", "Office", "Warehouse", "Industrial"], _N_CONTEXT
    ).tolist(),
    "PrimaryPropertyType": _RNG.choice(
        ["Office", "Retail", "Warehouse/Storage", "Service"], _N_CONTEXT
    ).tolist(),
    "Neighborhood": _RNG.choice(
        ["BALLARD", "DOWNTOWN", "FREMONT", "CAPITOL HILL", "QUEEN ANNE"],
        _N_CONTEXT,
    ).tolist(),
    "Latitude": np.round(_RNG.uniform(47.5, 47.7, _N_CONTEXT), 4).tolist(),
    "Longitude": np.round(_RNG.uniform(-122.4, -122.25, _N_CONTEXT), 4).tolist(),
    "YearBuilt": _RNG.integers(1920, 2022, _N_CONTEXT).tolist(),
    "NumberofBuildings": _RNG.integers(1, 3, _N_CONTEXT).astype(float).tolist(),
    "NumberofFloors": _RNG.integers(1, 8, _N_CONTEXT).tolist(),
    "PropertyGFAParking": _RNG.integers(0, 20_000, _N_CONTEXT).tolist(),
    "PropertyGFABuilding(s)": _GFA.tolist(),
    "LargestPropertyUseType": _RNG.choice(
        ["Office", "Retail", "Warehouse", "Parking"], _N_CONTEXT
    ).tolist(),
    "SecondLargestPropertyUseType": _RNG.choice(
        ["Retail", "Service", "Office", "Parking"], _N_CONTEXT
    ).tolist(),
    "SecondLargestPropertyUseTypeGFA": np.round(
        _RNG.uniform(0, 12_000, _N_CONTEXT), 0
    ).tolist(),
    "ThirdLargestPropertyUseType": _RNG.choice(
        ["Parking", "Service", "Vacant", "Office"], _N_CONTEXT
    ).tolist(),
    "ThirdLargestPropertyUseTypeGFA": np.round(
        _RNG.uniform(0, 8_000, _N_CONTEXT), 0
    ).tolist(),
    "Has_NaturalGas": _RNG.integers(0, 2, _N_CONTEXT).astype(float).tolist(),
    "Has_Steam": _RNG.integers(0, 2, _N_CONTEXT).astype(float).tolist(),
    _ENERGY_COLUMN: _CONTEXT_ENERGY.tolist(),
}


def build_context_df(target: str) -> pd.DataFrame:
    """Retourne les lignes de contexte pour ``target`` (features + cible)."""
    if target not in TARGETS:
        raise KeyError(f"Cible inconnue : {target}")

    target_column = TARGETS[target]["column"]
    df = pd.DataFrame(_CONTEXT_DATA)
    if target_column not in df.columns:
        df[target_column] = 0.1 * df[_ENERGY_COLUMN]

    return df[FEATURE_COLUMNS + [target_column]]
