"""Nettoyage (F0->F11), flags gaz/vapeur et préparation CatBoost multi-cible."""

from __future__ import annotations

import shutil
import urllib.request
from pathlib import Path

import pandas as pd

from app.schemas.api import CAT_FEATURES, FEATURE_COLUMNS, TARGETS

DATASET_URL = (
    "https://s3.eu-west-1.amazonaws.com/course.oc-static.com/projects/"
    "Data_Scientist_P4/2016_Building_Energy_Benchmarking.csv"
)
DEFAULT_DATASET_PATH = Path("data/2016_Building_Energy_Benchmarking.csv")

TARGET_COLUMNS = [t["column"] for t in TARGETS.values()]

PII_COLUMNS = [
    "OSEBuildingID",
    "PropertyName",
    "Address",
    "TaxParcelIdentificationNumber",
    "ZipCode",
    "CouncilDistrictCode",
]
DATA_LEAKAGE_COLUMNS = [
    "GHGEmissionsIntensity",
    "SourceEUIWN(kBtu/sf)",
    "SiteEUI(kBtu/sf)",
    "SiteEUIWN(kBtu/sf)",
    "SourceEUI(kBtu/sf)",
    "SiteEnergyUseWN(kBtu)",
    "SteamUse(kBtu)",
    "Electricity(kWh)",
    "Electricity(kBtu)",
    "NaturalGas(therms)",
    "NaturalGas(kBtu)",
]


def build_clean(df: pd.DataFrame) -> pd.DataFrame:
    """Applique la chaîne de nettoyage du notebook (F0 -> F11)."""
    habitation = df["BuildingType"].str.startswith("Multifamily", na=False)
    out = df.loc[~habitation].copy()

    out = out.loc[:, out.nunique() > 1]

    if "Outlier" in out.columns:
        out = out.drop(
            index=out[out["Outlier"].isin(["High outlier", "Low outlier"])].index
        )
        out = out.drop(columns=["Outlier"])

    out = out.drop(columns=DATA_LEAKAGE_COLUMNS, errors="ignore")
    out = out.drop(
        columns=["YearsENERGYSTARCertified", "ENERGYSTARScore"], errors="ignore"
    )
    out = out.drop(columns=PII_COLUMNS, errors="ignore")

    if "ComplianceStatus" in out.columns:
        out = out[out["ComplianceStatus"].eq("Compliant")].drop(
            columns=["ComplianceStatus", "DefaultData"], errors="ignore"
        )

    out = out.drop(
        columns=["PropertyGFATotal", "LargestPropertyUseTypeGFA"], errors="ignore"
    )

    if "Neighborhood" in out.columns:
        out["Neighborhood"] = out["Neighborhood"].str.upper().str.strip()

    out = out.drop(columns=["ListOfAllPropertyUseTypes"], errors="ignore")

    # F10 - les deux cibles strictement positives
    for target in TARGET_COLUMNS:
        out = out[out[target] > 0]

    if "NumberofBuildings" in out.columns:
        out.loc[out["NumberofBuildings"] == 0, "NumberofBuildings"] = 1

    out = out.dropna(subset=TARGET_COLUMNS)
    return out


def build_flags(df_raw: pd.DataFrame, df_clean: pd.DataFrame) -> pd.DataFrame:
    """Raccordement gaz/vapeur : consommation déclarée > 0."""
    return pd.DataFrame(
        {
            "Has_NaturalGas": (
                df_raw.loc[df_clean.index, "NaturalGas(kBtu)"] > 0
            ).astype(int),
            "Has_Steam": (df_raw.loc[df_clean.index, "SteamUse(kBtu)"] > 0).astype(int),
        },
        index=df_clean.index,
    )


def prepare_catboost(X: pd.DataFrame, flags: pd.DataFrame) -> pd.DataFrame:
    """Catégorielles brutes en str + marqueurs de raccordement."""
    d = X.copy()
    for col in CAT_FEATURES:
        d[col] = d[col].astype(str)
    return d.join(flags)[FEATURE_COLUMNS]


def prepare_dataset(df_raw: pd.DataFrame):
    """build_clean + flags + prepare_catboost -> (X, Y, df_clean)."""
    df_clean = build_clean(df_raw)
    features = [c for c in FEATURE_COLUMNS if c not in ("Has_NaturalGas", "Has_Steam")]
    missing = [c for c in features if c not in df_clean.columns]
    if missing:
        raise ValueError(f"Colonnes attendues absentes après nettoyage : {missing}")

    X_features = df_clean.drop(columns=TARGET_COLUMNS, errors="ignore")
    flags = build_flags(df_raw, df_clean)
    X = prepare_catboost(X_features, flags)
    Y = df_clean[TARGET_COLUMNS]
    return X, Y, df_clean


def ensure_dataset(
    path: str | Path = DEFAULT_DATASET_PATH,
    url: str = DATASET_URL,
    download: bool = False,
) -> Path:
    """Retourne le chemin du CSV ; le télécharge (idempotent) si demandé."""
    path = Path(path)
    if path.exists():
        return path
    if not download:
        raise FileNotFoundError(
            f"Dataset introuvable : {path}. Relancez avec --download."
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    urllib.request.urlretrieve(url, tmp)  # URL constante du projet
    shutil.move(str(tmp), str(path))
    return path
