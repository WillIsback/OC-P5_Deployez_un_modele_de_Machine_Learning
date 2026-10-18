"""Mise en forme française de l'interface (app.ui.format)."""

import pytest

from app.ui.format import building_card, fr_number, prediction_card

NBSP = " "


def _year(year, **overrides):
    return {
        "data_year": year,
        "building_type": "SPS-District K-12",
        "primary_property_type": "K-12 School",
        "neighborhood": "SOUTHEAST",
        "year_built": 1961,
        "property_gfa_buildings": 56228,
        **overrides,
    }


DETAIL = {
    "building_id": 28,
    "property_name": "GRAHAM HILL ELEMENTARY SCHOOL (SPS-DISTRICT)",
    "address": "5101 S GRAHAM ST",
    "zip_code": "98118",
    "neighborhood": "SOUTHEAST",
    "building_type": "SPS-District K-12",
    "primary_property_type": "K-12 School",
    "years": [_year(2016, year_built=1960), _year(2019)],
}


@pytest.mark.parametrize(
    ("value", "decimals", "expected"),
    [
        (3088219.81, 0, f"3{NBSP}088{NBSP}220"),
        (99.238, 1, "99,2"),
        (1234.5, 1, f"1{NBSP}234,5"),
        (0, 0, "0"),
        (None, 0, "—"),
    ],
)
def test_fr_number(value, decimals, expected):
    assert fr_number(value, decimals) == expected


def test_building_card():
    card = building_card(DETAIL)
    for text in (
        "GRAHAM HILL ELEMENTARY SCHOOL (SPS-DISTRICT)",
        "5101 S GRAHAM ST",
        "98118",
        "SOUTHEAST",
        "K-12 School",
        "1961",
        f"56{NBSP}228 pi²",
    ):
        assert text in card
    assert "1960" not in card  # données de la dernière année (2019)


def test_building_card_missing_values():
    detail = {
        **DETAIL,
        "address": None,
        "zip_code": None,
        "years": [_year(2019, property_gfa_buildings=None)],
    }
    card = building_card(detail)
    assert "None" not in card
    assert "—" in card


def test_prediction_card():
    card = prediction_card(
        {
            "energy_use_kbtu": 3088219.81,
            "ghg_emissions_tco2e": 99.238,
            "prediction_id": 42,
        },
        "CatBoost",
    )
    assert f"3{NBSP}088{NBSP}220 kBtu/an" in card
    assert "99,2 t CO2e/an" in card
    assert "CatBoost · prédiction n° 42" in card
