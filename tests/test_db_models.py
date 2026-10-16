"""Tests unitaires du schéma ORM et des correspondances (sans base)."""

import math
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db import mapping
from app.db.models import Base, Building, BuildingActual, BuildingYear
from app.schemas.api import FEATURE_COLUMNS


def test_all_tables_declared():
    assert set(Base.metadata.tables) == {
        "users",
        "api_requests",
        "buildings",
        "building_years",
        "building_actuals",
        "ml_models",
        "predictions",
    }


def test_feature_sql_covers_feature_columns_in_order():
    assert list(mapping.FEATURE_SQL) == FEATURE_COLUMNS


def test_feature_block_in_building_years():
    for col in mapping.FEATURE_SQL.values():
        assert col in BuildingYear.__table__.columns


def test_source_columns_are_unique_csv_names():
    assert len(mapping.SOURCE_COLUMNS) == 46
    assert len(set(mapping.SOURCE_COLUMNS)) == 46
    assert mapping.SOURCE_COLUMNS[0] == "OSEBuildingID"


def test_target_sql_targets_actuals():
    for col in mapping.TARGET_SQL.values():
        assert col in BuildingActual.__table__.columns


def test_to_python_handles_numpy_and_nan():
    assert mapping.to_python(np.int64(3)) == 3
    assert type(mapping.to_python(np.int64(3))) is int
    assert mapping.to_python(float("nan")) is None
    assert mapping.to_python(np.float64("nan")) is None
    assert mapping.to_python(None) is None


def test_coerce_row_by_column_type():
    years = mapping.coerce_row(
        BuildingYear,
        {
            "year_built": np.float64(1990.0),
            "has_steam": "False",
            "latitude": np.float64(47.6),
            "number_of_buildings": float("nan"),
        },
    )
    assert years == {
        "year_built": 1990,
        "has_steam": False,
        "latitude": 47.6,
        "number_of_buildings": None,
    }
    identity = mapping.coerce_row(
        Building, {"zip_code": 98101.0, "address": float("nan")}
    )
    assert identity == {"zip_code": "98101", "address": None}


def test_coerce_keeps_other_types_unchanged():
    from sqlalchemy import DateTime

    payload = {"a": [1, 2]}
    assert mapping._coerce(payload, DateTime()) is payload


def test_features_roundtrip():
    features = {
        "BuildingType": "NonResidential",
        "PrimaryPropertyType": "Office",
        "Neighborhood": "DOWNTOWN",
        "Latitude": 47.6,
        "Longitude": -122.3,
        "YearBuilt": 1990,
        "NumberofBuildings": 1.0,
        "NumberofFloors": 4,
        "PropertyGFAParking": 0,
        "PropertyGFABuilding(s)": 15000,
        "LargestPropertyUseType": "Office",
        "SecondLargestPropertyUseType": "UNKNOWN",
        "SecondLargestPropertyUseTypeGFA": float("nan"),
        "ThirdLargestPropertyUseType": "UNKNOWN",
        "ThirdLargestPropertyUseTypeGFA": float("nan"),
        "Has_NaturalGas": 1,
        "Has_Steam": 0,
    }
    sql = mapping.features_to_sql(features)
    assert sql["has_natural_gas"] is True
    assert sql["has_steam"] is False
    assert sql["second_largest_property_use_type_gfa"] is None
    obj = BuildingYear(**sql)
    back = mapping.features_from_sql(obj)
    assert list(back) == FEATURE_COLUMNS
    assert back["Has_NaturalGas"] == 1
    assert back["Has_Steam"] == 0
    assert back["SecondLargestPropertyUseTypeGFA"] is None
    assert not math.isnan(back["Latitude"])
