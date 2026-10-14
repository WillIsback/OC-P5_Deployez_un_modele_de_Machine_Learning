"""Correspondances CSV ↔ SQL et conversion des valeurs pandas/numpy."""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any

import numpy as np
import pandas as pd
from sqlalchemy import Boolean, Double, Integer, String

from app.db.models import BuildingFeatures
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

# Colonnes du CSV 2016 → colonnes de building_records_raw.
RAW_SQL: dict[str, str] = {
    "OSEBuildingID": "building_id",
    "DataYear": "data_year",
    "BuildingType": "building_type",
    "PrimaryPropertyType": "primary_property_type",
    "PropertyName": "property_name",
    "Address": "address",
    "City": "city",
    "State": "state",
    "ZipCode": "zip_code",
    "TaxParcelIdentificationNumber": "tax_parcel_identification_number",
    "CouncilDistrictCode": "council_district_code",
    "Neighborhood": "neighborhood",
    "Latitude": "latitude",
    "Longitude": "longitude",
    "YearBuilt": "year_built",
    "NumberofBuildings": "number_of_buildings",
    "NumberofFloors": "number_of_floors",
    "PropertyGFATotal": "property_gfa_total",
    "PropertyGFAParking": "property_gfa_parking",
    "PropertyGFABuilding(s)": "property_gfa_buildings",
    "ListOfAllPropertyUseTypes": "list_of_all_property_use_types",
    "LargestPropertyUseType": "largest_property_use_type",
    "LargestPropertyUseTypeGFA": "largest_property_use_type_gfa",
    "SecondLargestPropertyUseType": "second_largest_property_use_type",
    "SecondLargestPropertyUseTypeGFA": "second_largest_property_use_type_gfa",
    "ThirdLargestPropertyUseType": "third_largest_property_use_type",
    "ThirdLargestPropertyUseTypeGFA": "third_largest_property_use_type_gfa",
    "YearsENERGYSTARCertified": "years_energy_star_certified",
    "ENERGYSTARScore": "energy_star_score",
    "SiteEUI(kBtu/sf)": "site_eui_kbtu_sf",
    "SiteEUIWN(kBtu/sf)": "site_eui_wn_kbtu_sf",
    "SourceEUI(kBtu/sf)": "source_eui_kbtu_sf",
    "SourceEUIWN(kBtu/sf)": "source_eui_wn_kbtu_sf",
    "SiteEnergyUse(kBtu)": "site_energy_use_kbtu",
    "SiteEnergyUseWN(kBtu)": "site_energy_use_wn_kbtu",
    "SteamUse(kBtu)": "steam_use_kbtu",
    "Electricity(kWh)": "electricity_kwh",
    "Electricity(kBtu)": "electricity_kbtu",
    "NaturalGas(therms)": "natural_gas_therms",
    "NaturalGas(kBtu)": "natural_gas_kbtu",
    "DefaultData": "default_data",
    "Comments": "comments",
    "ComplianceStatus": "compliance_status",
    "Outlier": "outlier",
    "TotalGHGEmissions": "total_ghg_emissions",
    "GHGEmissionsIntensity": "ghg_emissions_intensity",
}

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
        BuildingFeatures, {col: features[name] for name, col in FEATURE_SQL.items()}
    )


def feature_values(obj: Any) -> dict[str, Any]:
    """Bloc de features d'une ligne ORM, clés SQL (pour copier un snapshot)."""
    return {col: getattr(obj, col) for col in FEATURE_SQL.values()}


def features_from_sql(obj: Any) -> dict[str, Any]:
    """Ligne ORM → dict FEATURE_COLUMNS prêt pour CatBoost (flags en int)."""
    out = {name: getattr(obj, col) for name, col in FEATURE_SQL.items()}
    for flag in FLAG_COLUMNS:
        out[flag] = int(out[flag])
    return out
