"""Open data Seattle (2015 → aujourd'hui) → schéma du CSV 2016 d'entraînement.

Le jeu « Building Energy Benchmarking Data, 2015-Present » (data.seattle.gov,
``teqw-tu6e``) ne reprend pas le schéma du CSV 2016 sur lequel le modèle est
entraîné : ``PrimaryPropertyType`` est remplacé par ``EPAPropertyType``, les
``BuildingType`` sont regroupés autrement et certains libellés d'usage ont été
renommés. Les correspondances ci-dessous ont été établies en croisant les
lignes 2016 des deux sources (3 194 bâtiments communs).
"""

from __future__ import annotations

import io
import urllib.request
from collections.abc import Mapping
from pathlib import Path

import pandas as pd

from app.lib.tools import get_logger

log = get_logger(__name__)

OPEN_DATA_URL = (
    "https://data.seattle.gov/api/views/teqw-tu6e/rows.csv?accessType=DOWNLOAD"
)
OPEN_DATA_MARKER = "EPAPropertyType"  # colonne propre au format open data

OPEN_DATA_RENAMES: dict[str, str] = {
    "BuildingName": "PropertyName",
    "PropertyGFABuildings": "PropertyGFABuilding(s)",
}

# EPAPropertyType → PrimaryPropertyType (valeurs de 2016) ; le reste → "Other".
EPA_TO_PRIMARY: dict[str, str] = {
    "College/University": "University",
    "Distribution Center": "Distribution Center",
    "Hospital (General Medical & Surgical)": "Hospital",
    "Hotel": "Hotel",
    "K-12 School": "K-12 School",
    "Laboratory": "Laboratory",
    "Medical Office": "Medical Office",
    "Mixed Use Property": "Mixed Use Property",
    "Multifamily HR (10+)": "High-Rise Multifamily",
    "Multifamily LR (1-4)": "Low-Rise Multifamily",
    "Multifamily MR (5-9)": "Mid-Rise Multifamily",
    "Non-Refrigerated Warehouse": "Warehouse",
    "Other - Restaurant/Bar": "Restaurant",
    "Refrigerated Warehouse": "Refrigerated Warehouse",
    "Residence Hall/Dormitory": "Residence Hall",
    "Residential Care Facility": "Senior Care Community",
    "Restaurant": "Restaurant",
    "Retail Store": "Retail Store",
    "Self-Storage Facility": "Self-Storage Facility",
    "Senior Living Community": "Senior Care Community",
    "Supermarket/Grocery Store": "Supermarket / Grocery Store",
    "Worship Facility": "Worship Facility",
}
PRIMARY_FALLBACK = "Other"
# En 2016, « Office » est scindé sur la surface totale (seuil sans recouvrement :
# Small max 99 440 sf, Large min 100 734 sf).
LARGE_OFFICE_MIN_GFA = 100_000

# Libellés d'usage renommés depuis 2016 (Largest/Second/Third).
USE_TYPE_LABELS: dict[str, str] = {
    "Senior Living Community": "Senior Care Community",
    "Vehicle Dealership": "Automobile Dealership",
    "Vehicle Repair Services": "Repair Services (Vehicle, Shoe, Locksmith, etc)",
}
USE_TYPE_COLUMNS = (
    "LargestPropertyUseType",
    "SecondLargestPropertyUseType",
    "ThirdLargestPropertyUseType",
)

# BuildingType des bâtiments absents de l'année d'entraînement (classe
# majoritaire observée en 2016 pour chaque nouvelle catégorie).
BUILDING_TYPE_FALLBACK: dict[str, str] = {
    "Hospital": "NonResidential",
    "School": "SPS-District K-12",
    "University": "NonResidential",
}


def is_open_data(df: pd.DataFrame) -> bool:
    return OPEN_DATA_MARKER in df.columns


def _residential(series: pd.Series) -> pd.Series:
    return series.str.startswith("Multifamily", na=False)


def primary_property_type(df: pd.DataFrame) -> pd.Series:
    """Reconstitue PrimaryPropertyType depuis EPAPropertyType et la surface."""
    out = df["EPAPropertyType"].map(EPA_TO_PRIMARY).fillna(PRIMARY_FALLBACK)
    office = df["EPAPropertyType"].eq("Office")
    large = pd.to_numeric(df["PropertyGFATotal"], errors="coerce").ge(
        LARGE_OFFICE_MIN_GFA
    )
    out[office & large] = "Large Office"
    out[office & ~large] = "Small- and Mid-Sized Office"
    return out


def building_type(df: pd.DataFrame, reference: Mapping[int, str]) -> pd.Series:
    """BuildingType au format 2016.

    La valeur 2016 du bâtiment est reprise quand elle existe (elle seule porte
    les catégories ``Nonresidential COS`` / ``Campus`` disparues du nouveau
    jeu), à condition que le caractère résidentiel n'ait pas changé : le
    périmètre du modèle reste ainsi décidé par la source de l'année.
    """
    current = df["BuildingType"]
    ref = df["OSEBuildingID"].map(reference).astype("string")
    usable = ref.notna() & (_residential(ref) == _residential(current))
    fallback = current.map(BUILDING_TYPE_FALLBACK).fillna(current)
    return ref.where(usable, fallback)


def from_open_data(
    df: pd.DataFrame, reference_building_types: Mapping[int, str] | None = None
) -> pd.DataFrame:
    """Ramène un extrait open data au schéma (colonnes et modalités) de 2016."""
    out = df.rename(columns=OPEN_DATA_RENAMES)
    out["PrimaryPropertyType"] = primary_property_type(out)
    out["BuildingType"] = building_type(out, reference_building_types or {})
    for col in USE_TYPE_COLUMNS:
        out[col] = out[col].replace(USE_TYPE_LABELS)
    if not reference_building_types:
        log.warning(
            "Aucun BuildingType de référence : catégories 2016 déduites "
            "uniquement de BUILDING_TYPE_FALLBACK"
        )
    return out.drop(columns=[OPEN_DATA_MARKER])


def download_open_data_year(year: int, path: str | Path) -> Path:
    """Télécharge l'export open data et n'en garde que l'année demandée."""
    path = Path(path)
    if path.exists():
        return path
    try:
        # URL constante du projet, pas d'entrée utilisateur.
        with urllib.request.urlopen(OPEN_DATA_URL, timeout=120) as resp:
            raw = resp.read()
    except Exception as exc:
        raise RuntimeError(
            f"Échec du téléchargement depuis {OPEN_DATA_URL}: {exc}"
        ) from exc
    df = pd.read_csv(io.BytesIO(raw), low_memory=False)
    subset = df.loc[pd.to_numeric(df["DataYear"], errors="coerce") == year]
    if subset.empty:
        raise RuntimeError(f"Aucune ligne {year} dans l'export open data")
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    subset.to_csv(tmp, index=False)
    tmp.replace(path)
    return path
