"""Nettoyage (F0->F11), flags gaz/vapeur et préparation CatBoost multi-cible."""

from __future__ import annotations

import shutil
import urllib.request
from pathlib import Path

import pandas as pd
from sklearn.model_selection import train_test_split

from app.schemas.api import CAT_FEATURES, FEATURE_COLUMNS, TARGETS

DATASET_URL = (
    "https://s3.eu-west-1.amazonaws.com/course.oc-static.com/projects/"
    "Data_Scientist_P4/2016_Building_Energy_Benchmarking.csv"
)
DEFAULT_DATASET_PATH = Path("data/2016_Building_Energy_Benchmarking.csv")

TARGET_COLUMNS = [t["column"] for t in TARGETS.values()]

PII_COLUMNS = [
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


def filter_scope(df: pd.DataFrame) -> pd.DataFrame:
    """Périmètre du modèle : exclut le résidentiel (Multifamily*)."""
    residential = df["BuildingType"].str.startswith("Multifamily", na=False)
    return df.loc[~residential].copy()


def apply_common_corrections(df: pd.DataFrame) -> pd.DataFrame:
    """Corrections valables pour toutes les années (entraînement et production)."""
    out = df.copy()
    if "Neighborhood" in out.columns:
        out["Neighborhood"] = out["Neighborhood"].str.upper().str.strip()
    if "NumberofBuildings" in out.columns:
        out.loc[out["NumberofBuildings"] == 0, "NumberofBuildings"] = 1
    return out


def flag_training_eligibility(df: pd.DataFrame) -> pd.DataFrame:
    """Filtres qualité de l'entraînement ; la première raison rencontrée l'emporte."""
    reason = pd.Series([None] * len(df), index=df.index, dtype=object)

    def mark(mask: pd.Series, label: str) -> None:
        reason[mask & reason.isna()] = label

    if "Outlier" in df.columns:
        mark(df["Outlier"].isin(["High outlier", "Low outlier"]), "outlier")
    if "ComplianceStatus" in df.columns:
        mark(df["ComplianceStatus"].ne("Compliant"), "non_compliant")
    targets = df[TARGET_COLUMNS]
    mark(targets.isna().any(axis=1), "missing_target")
    mark((targets <= 0).any(axis=1), "non_positive_target")
    return pd.DataFrame(
        {"is_training_eligible": reason.isna(), "exclusion_reason": reason},
        index=df.index,
    )


# Plages plausibles d'intensité (cible réelle / PropertyGFATotal), arrondies à
# partir des bâtiments éligibles de 2016 (EUI 1,4–906 kBtu/sf ; émissions
# ≤ 34 kg CO2e/sf). L'open data n'a plus la colonne Outlier de 2016 : sans ce
# garde-fou, une seule déclaration erronée suffit à écraser le R² d'une année.
SITE_EUI_RANGE = (1.0, 1000.0)  # kBtu/sf
GHG_INTENSITY_MAX = 0.05  # t CO2e/sf


def flag_production_exclusion(df: pd.DataFrame) -> pd.Series:
    """Raison d'exclure un bâtiment de l'évaluation des années de production.

    Conformité, puis intensités d'énergie et d'émissions hors plages (None =
    conservé). Ne sert qu'à l'évaluation : la prédiction par identifiant l'ignore.
    """
    reason = pd.Series([None] * len(df), index=df.index, dtype=object)
    gfa = df["PropertyGFATotal"].where(df["PropertyGFATotal"] > 0)
    eui = df["SiteEnergyUse(kBtu)"] / gfa
    ghg = df["TotalGHGEmissions"] / gfa
    low, high = SITE_EUI_RANGE
    checks = [
        (df["ComplianceStatus"].ne("Compliant"), "non_compliant"),
        ((eui < low) | (eui > high), "aberrant_energy"),
        (ghg > GHG_INTENSITY_MAX, "aberrant_emissions"),
    ]
    for mask, label in checks:
        reason[mask & reason.isna()] = label
    return reason


def assign_split(
    eligible_index: pd.Index, test_size: float = 0.2, seed: int = 42
) -> pd.Series:
    """Split train/test reproductible (identique à l'ancien TrainPipeline.split)."""
    _, idx_test = train_test_split(
        eligible_index, test_size=test_size, random_state=seed
    )
    split = pd.Series("train", index=eligible_index, dtype=object)
    split.loc[idx_test] = "test"
    return split


def build_clean(df: pd.DataFrame) -> pd.DataFrame:
    """Applique la chaîne de nettoyage du notebook (F0 -> F11)."""
    out = filter_scope(df)
    out = out.loc[:, out.nunique() > 1]
    out = out.loc[flag_training_eligibility(out)["is_training_eligible"]]
    out = out.drop(
        columns=[
            "Outlier",
            "ComplianceStatus",
            "DefaultData",
            "YearsENERGYSTARCertified",
            "ENERGYSTARScore",
            "PropertyGFATotal",
            "LargestPropertyUseTypeGFA",
            "ListOfAllPropertyUseTypes",
            *DATA_LEAKAGE_COLUMNS,
            *PII_COLUMNS,
        ],
        errors="ignore",
    )
    return apply_common_corrections(out)


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
    """Catégorielles brutes en str + marqueurs de raccordement.

    Les valeurs manquantes sont remplacées par ``"UNKNOWN"`` : sans cela,
    pandas 3.0 conserve les NA et CatBoost refuse les catégorielles non-str.
    """
    d = X.copy()
    for col in CAT_FEATURES:
        d[col] = d[col].astype("string").fillna("UNKNOWN").astype(str)
    return d.join(flags)[FEATURE_COLUMNS]


def prepare_dataset(df_raw: pd.DataFrame):
    """build_clean + flags + prepare_catboost -> (X, Y, df_clean)."""
    df_clean = build_clean(df_raw)
    features = [c for c in FEATURE_COLUMNS if c not in ("Has_NaturalGas", "Has_Steam")]
    missing = [c for c in features if c not in df_clean.columns]
    if missing:
        raise ValueError(f"Colonnes attendues absentes après nettoyage : {missing}")

    x_features = df_clean.drop(columns=TARGET_COLUMNS, errors="ignore")
    flags = build_flags(df_raw, df_clean)
    X = prepare_catboost(x_features, flags)
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
    try:
        urllib.request.urlretrieve(url, tmp)  # URL constante du projet
    except Exception as exc:
        tmp.unlink(missing_ok=True)
        raise RuntimeError(
            f"Échec du téléchargement du dataset depuis {url}: {exc}"
        ) from exc
    shutil.move(str(tmp), str(path))
    return path
