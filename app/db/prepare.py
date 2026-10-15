"""Préparation d'un fichier annuel : features nettoyées, exclusion et split.

Fonctions pures, sans accès base : l'écriture est faite par ``app.db.ingest``.
"""

from __future__ import annotations

import os

import pandas as pd

from app.lib.tools import get_logger
from app.schemas.api import FEATURE_COLUMNS
from app.training import data_processing as dp

log = get_logger(__name__)

TRAINING_YEAR = int(os.getenv("TRAINING_YEAR", "2016"))
PREP_VERSION = "1"
REQUIRED_FEATURES = (
    "Latitude",
    "Longitude",
    "YearBuilt",
    "NumberofFloors",
    "PropertyGFAParking",
    "PropertyGFABuilding(s)",
)


def build_feature_rows(
    df_raw: pd.DataFrame, *, training: bool, test_size: float = 0.2, seed: int = 42
) -> pd.DataFrame:
    """Features nettoyées + ``exclusion_reason`` + ``split`` (année d'entraînement).

    Index = celui de ``df_raw``. Le split ne concerne que les lignes éligibles de
    l'année d'entraînement ; les autres années n'en ont jamais.
    """
    scoped = dp.apply_common_corrections(dp.filter_scope(df_raw))
    missing = scoped[list(REQUIRED_FEATURES)].isna().any(axis=1)
    if missing.any():
        log.warning(
            "%d bâtiment(s) ignoré(s) : feature obligatoire manquante",
            int(missing.sum()),
        )
        scoped = scoped.loc[~missing]
    base = [c for c in FEATURE_COLUMNS if c not in ("Has_NaturalGas", "Has_Steam")]
    out = dp.prepare_catboost(scoped[base], dp.build_flags(df_raw, scoped))
    if training:
        eligibility = dp.flag_training_eligibility(scoped)
        out["exclusion_reason"] = eligibility["exclusion_reason"]
        eligible = out.index[eligibility["is_training_eligible"].to_numpy(dtype=bool)]
        if len(eligible):  # train_test_split refuse un échantillon vide
            split = dp.assign_split(eligible, test_size=test_size, seed=seed)
            out["split"] = split.reindex(out.index)
        else:
            out["split"] = None
    else:
        out["exclusion_reason"] = dp.flag_production_exclusion(scoped)
        out["split"] = None
    return out
