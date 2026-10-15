"""Tests de l'harmonisation open data Seattle → schéma 2016."""

import pandas as pd
import pytest
from sqlalchemy import select
from synth import make_synth

from app.db import harmonize, ingest
from app.db.models import BuildingYear

OC_ONLY = [
    "PrimaryPropertyType",
    "ListOfAllPropertyUseTypes",
    "Outlier",
    "DefaultData",
    "YearsENERGYSTARCertified",
]


def make_open_data(n: int = 12, year: int = 2017) -> pd.DataFrame:
    """Synthétique au format de l'export open data (2015→aujourd'hui)."""
    df = make_synth(n).drop(columns=OC_ONLY)
    df = df.rename(columns={v: k for k, v in harmonize.OPEN_DATA_RENAMES.items()})
    df["DataYear"] = year
    df["BuildingType"] = "NonResidential"
    df["EPAPropertyType"] = "Office"
    df["Demolished"] = False
    return df


def test_is_open_data_detects_format():
    assert harmonize.is_open_data(make_open_data())
    assert not harmonize.is_open_data(make_synth(10))


def test_primary_property_type_mapping_and_office_split():
    df = pd.DataFrame(
        {
            "EPAPropertyType": [
                "Office",
                "Office",
                "Senior Living Community",
                "Bank Branch",
                "Non-Refrigerated Warehouse",
            ],
            "PropertyGFATotal": [150_000, 50_000, 80_000, 5_000, 30_000],
        }
    )
    assert harmonize.primary_property_type(df).tolist() == [
        "Large Office",
        "Small- and Mid-Sized Office",
        "Senior Care Community",
        "Other",
        "Warehouse",
    ]


def test_building_type_uses_reference_unless_residential_changes():
    df = pd.DataFrame(
        {
            "OSEBuildingID": [1, 2, 3, 4, 5],
            "BuildingType": [
                "NonResidential",
                "School",
                "School",
                "Multifamily LR (1-4)",
                "Hospital",
            ],
        }
    )
    reference = {
        1: "Nonresidential COS",
        2: "NonResidential",
        4: "NonResidential",
    }
    assert harmonize.building_type(df, reference).tolist() == [
        "Nonresidential COS",  # référence 2016
        "NonResidential",  # référence 2016 (école privée)
        "SPS-District K-12",  # inconnu en 2016 → repli
        "Multifamily LR (1-4)",  # devenu résidentiel : la source de l'année prime
        "NonResidential",  # repli
    ]


def test_from_open_data_matches_2016_schema():
    df = make_open_data()
    df.loc[0, "LargestPropertyUseType"] = "Vehicle Dealership"
    out = harmonize.from_open_data(df, {})
    assert "EPAPropertyType" not in out.columns
    assert "PropertyGFABuilding(s)" in out.columns
    assert "PropertyName" in out.columns
    assert out.loc[0, "LargestPropertyUseType"] == "Automobile Dealership"
    assert set(out["PrimaryPropertyType"]) <= {
        "Large Office",
        "Small- and Mid-Sized Office",
    }


def test_normalize_columns_accepts_open_data():
    out = ingest.normalize_columns(make_open_data(), 2017)
    assert list(out.columns) == list(ingest.SOURCE_COLUMNS)
    assert out["PrimaryPropertyType"].notna().all()


def test_download_filters_year(tmp_path, monkeypatch):
    export = pd.concat([make_open_data(6, 2017), make_open_data(7, 2018)])

    class _Resp:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def read(self):
            return export.to_csv(index=False).encode()

    monkeypatch.setattr(harmonize.urllib.request, "urlopen", lambda *a, **k: _Resp())
    path = harmonize.download_open_data_year(2018, tmp_path / "2018.csv")
    assert set(pd.read_csv(path)["DataYear"]) == {2018}
    assert len(pd.read_csv(path)) == 7


@pytest.mark.db
def test_ingest_open_data_reuses_2016_building_type(db):
    ref = make_synth(6)
    ref["BuildingType"] = "Nonresidential COS"
    with db() as s:
        ingest.ingest_frame(s, ref, year=2016)
        ingest.ingest_frame(s, make_open_data(6), year=2017)
        types = s.scalars(
            select(BuildingYear.building_type).where(BuildingYear.data_year == 2017)
        ).all()
    assert set(types) == {"Nonresidential COS"}
