"""Correspondances CSV ↔ SQL et conversion des valeurs pandas/numpy."""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any

import numpy as np
import pandas as pd
from sqlalchemy import Boolean, Double, Integer, String

from app.db.models import BuildingYear
from app.schemas.api import TARGETS

# Ordre identique à FEATURE_COLUMNS (vérifié par les tests).
FEATURE_SQL: dict[str, str] = {
    "BuildingType": "building_type",
    "PrimaryPropertyType": "primary_property_type",
    "Neighborhood": "neighborhood",
    "Latitude": "latitude",
    "Longitude": "longitude",
    "YearBuilt": "year_built",
    "NumberofBuildings": "number_of_buildings",
    "NumberofFloors": "number_of_floors",
    "PropertyGFAParking": "property_gfa_parking",
    "PropertyGFABuilding(s)": "property_gfa_buildings",
    "LargestPropertyUseType": "largest_property_use_type",
    "SecondLargestPropertyUseType": "second_largest_property_use_type",
    "SecondLargestPropertyUseTypeGFA": "second_largest_property_use_type_gfa",
    "ThirdLargestPropertyUseType": "third_largest_property_use_type",
    "ThirdLargestPropertyUseTypeGFA": "third_largest_property_use_type_gfa",
    "Has_NaturalGas": "has_natural_gas",
    "Has_Steam": "has_steam",
}
FLAG_COLUMNS = ("Has_NaturalGas", "Has_Steam")

TARGET_SQL: dict[str, str] = {
    TARGETS["energy"]["column"]: "site_energy_use_kbtu",
    TARGETS["emissions"]["column"]: "total_ghg_emissions_tco2e",
}

# Colonnes du CSV 2016 conservées à l'ingestion (les autres sont ignorées).
SOURCE_COLUMNS: tuple[str, ...] = (
    "OSEBuildingID",
    "DataYear",
    "BuildingType",
    "PrimaryPropertyType",
    "PropertyName",
    "Address",
    "City",
    "State",
    "ZipCode",
    "TaxParcelIdentificationNumber",
    "CouncilDistrictCode",
    "Neighborhood",
    "Latitude",
    "Longitude",
    "YearBuilt",
    "NumberofBuildings",
    "NumberofFloors",
    "PropertyGFATotal",
    "PropertyGFAParking",
    "PropertyGFABuilding(s)",
    "ListOfAllPropertyUseTypes",
    "LargestPropertyUseType",
    "LargestPropertyUseTypeGFA",
    "SecondLargestPropertyUseType",
    "SecondLargestPropertyUseTypeGFA",
    "ThirdLargestPropertyUseType",
    "ThirdLargestPropertyUseTypeGFA",
    "YearsENERGYSTARCertified",
    "ENERGYSTARScore",
    "SiteEUI(kBtu/sf)",
    "SiteEUIWN(kBtu/sf)",
    "SourceEUI(kBtu/sf)",
    "SourceEUIWN(kBtu/sf)",
    "SiteEnergyUse(kBtu)",
    "SiteEnergyUseWN(kBtu)",
    "SteamUse(kBtu)",
    "Electricity(kWh)",
    "Electricity(kBtu)",
    "NaturalGas(therms)",
    "NaturalGas(kBtu)",
    "DefaultData",
    "Comments",
    "ComplianceStatus",
    "Outlier",
    "TotalGHGEmissions",
    "GHGEmissionsIntensity",
)

_TRUE_STRINGS = frozenset({"true", "t", "1", "yes", "y"})


def to_python(value: Any) -> Any:
    """Scalaire numpy/pandas → type Python natif ; NaN/NA → None."""
    if value is None or value is pd.NA:
        return None
    if isinstance(value, np.generic):
        value = value.item()
    if isinstance(value, float) and math.isnan(value):
        return None
    return value


def _coerce(value: Any, sqltype: Any) -> Any:
    value = to_python(value)
    if value is None:
        return None
    if isinstance(sqltype, Boolean):
        if isinstance(value, str):
            return value.strip().lower() in _TRUE_STRINGS
        return bool(value)
    if isinstance(sqltype, String):  # couvre aussi Text
        if isinstance(value, float) and value.is_integer():
            return str(int(value))  # ex. ZipCode lu en float : 98101.0 → "98101"
        return str(value)
    if isinstance(sqltype, Integer):  # couvre SmallInteger et BigInteger
        return int(value)
    if isinstance(sqltype, Double):
        return float(value)
    return value


def coerce_row(model_cls: Any, row: Mapping[str, Any]) -> dict[str, Any]:
    """Convertit chaque valeur selon le type SQL de la colonne cible."""
    columns = model_cls.__table__.columns
    return {key: _coerce(value, columns[key].type) for key, value in row.items()}


def features_to_sql(features: Mapping[str, Any]) -> dict[str, Any]:
    """Features nommées comme FEATURE_COLUMNS → colonnes SQL typées."""
    return coerce_row(
        BuildingYear, {col: features[name] for name, col in FEATURE_SQL.items()}
    )


def features_from_sql(obj: Any) -> dict[str, Any]:
    """Ligne ORM → dict FEATURE_COLUMNS prêt pour CatBoost (flags en int)."""
    out = {name: getattr(obj, col) for name, col in FEATURE_SQL.items()}
    for flag in FLAG_COLUMNS:
        out[flag] = int(out[flag])
    return out
