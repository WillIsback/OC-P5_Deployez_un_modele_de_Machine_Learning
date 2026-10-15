"""Données synthétiques et helpers partagés par les tests."""

import numpy as np
import pandas as pd
from sqlalchemy.orm import Session

from app.db import mapping
from app.db.models import Building, BuildingYear


def make_synth(n: int = 80, seed: int = 0) -> pd.DataFrame:
    """DataFrame brut synthétique au format du benchmark Seattle."""
    rng = np.random.default_rng(seed)
    n_multi = n // 8
    n_other = n - n_multi
    nonres_types = ["NonResidential", "Commercial", "Mixed Use"]
    building_type = (nonres_types * n_other)[:n_other] + [
        "Multifamily LR (1-4)"
    ] * n_multi
    outlier = ["None"] * n
    outlier[2] = "High outlier"
    outlier[3] = "Low outlier"
    compliance = ["Compliant"] * n
    compliance[4] = "NonCompliant"
    default_data = [False] * n
    default_data[5] = True
    return pd.DataFrame(
        {
            "BuildingType": building_type,
            "PrimaryPropertyType": rng.choice(
                ["Office", "Retail Store", "Warehouse"], n
            ),
            "Neighborhood": rng.choice(
                ["ballard", " Downtown ", "FREMONT", "Capitol Hill"], n
            ),
            "Latitude": rng.uniform(47.5, 47.7, n),
            "Longitude": rng.uniform(-122.4, -122.25, n),
            "YearBuilt": rng.integers(1930, 2020, n),
            "NumberofBuildings": rng.integers(0, 3, n).astype(float),
            "NumberofFloors": rng.integers(1, 8, n),
            "PropertyGFAParking": rng.integers(0, 20000, n),
            "PropertyGFABuilding(s)": rng.integers(500, 40000, n),
            "LargestPropertyUseType": rng.choice(["Office", "Retail"], n),
            "SecondLargestPropertyUseType": rng.choice(["Retail", "Service"], n),
            "SecondLargestPropertyUseTypeGFA": rng.uniform(0, 12000, n),
            "ThirdLargestPropertyUseType": rng.choice(["Parking", "Service"], n),
            "ThirdLargestPropertyUseTypeGFA": rng.uniform(0, 8000, n),
            "SiteEnergyUse(kBtu)": rng.uniform(1000, 500000, n),
            "TotalGHGEmissions": rng.uniform(1, 500, n),
            "NaturalGas(kBtu)": rng.uniform(0, 1000, n),
            "SteamUse(kBtu)": rng.uniform(0, 1000, n),
            "PropertyGFATotal": rng.integers(500, 40000, n),
            "LargestPropertyUseTypeGFA": rng.integers(0, 40000, n),
            "OSEBuildingID": np.arange(n),
            "DataYear": [2016] * n,
            "PropertyName": [f"b{i}" for i in range(n)],
            "Address": [f"{i} st" for i in range(n)],
            "TaxParcelIdentificationNumber": [f"t{i}" for i in range(n)],
            "ZipCode": rng.choice(["98101", "98102", "98103"], n),
            "CouncilDistrictCode": rng.integers(1, 8, n),
            "ListOfAllPropertyUseTypes": ["Office"] * n,
            "ComplianceStatus": compliance,
            "DefaultData": default_data,
            "Outlier": outlier,
            "YearsENERGYSTARCertified": [np.nan] * n,
            "ENERGYSTARScore": rng.uniform(0, 100, n),
            "GHGEmissionsIntensity": rng.uniform(0, 10, n),
        }
    )


EXAMPLE_FEATURES = {
    "BuildingType": "NonResidential",
    "PrimaryPropertyType": "Office",
    "Neighborhood": "BALLARD",
    "Latitude": 47.62,
    "Longitude": -122.35,
    "YearBuilt": 1990,
    "NumberofBuildings": 1.0,
    "NumberofFloors": 4,
    "PropertyGFAParking": 5000,
    "PropertyGFABuilding(s)": 15000,
    "LargestPropertyUseType": "Office",
    "SecondLargestPropertyUseType": "Retail",
    "SecondLargestPropertyUseTypeGFA": 3000.0,
    "ThirdLargestPropertyUseType": "Parking",
    "ThirdLargestPropertyUseTypeGFA": 2000.0,
    "Has_NaturalGas": 1,
    "Has_Steam": 0,
}


def add_building(
    session: Session, building_id: int, split: str | None = None, **identity
) -> Building:
    """Crée (si besoin) un bâtiment sans année : hors périmètre du modèle."""
    building = session.get(Building, building_id)
    if building is None:
        building = Building(id=building_id, split=split, **identity)
        session.add(building)
        session.flush()
    return building


def add_year(
    session: Session,
    building_id: int,
    year: int,
    *,
    split: str | None = None,
    exclusion_reason: str | None = None,
) -> BuildingYear:
    """Crée (si besoin) le bâtiment puis une ligne d'année aux features d'exemple."""
    add_building(session, building_id, split)
    row = BuildingYear(
        building_id=building_id,
        data_year=year,
        exclusion_reason=exclusion_reason,
        prep_version="t",
        **mapping.features_to_sql(EXAMPLE_FEATURES),
    )
    session.add(row)
    session.flush()
    return row
