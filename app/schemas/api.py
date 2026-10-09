from datetime import datetime

from pydantic import BaseModel, ConfigDict


class Model(BaseModel):
    id: int
    name: str
    created_at: datetime


CAT_FEATURES = [
    "BuildingType",
    "PrimaryPropertyType",
    "Neighborhood",
    "LargestPropertyUseType",
    "SecondLargestPropertyUseType",
    "ThirdLargestPropertyUseType",
]


class EnergyPredictionRequest(BaseModel):
    """Input features for the Seattle building energy consumption model."""

    model_config = ConfigDict(extra="forbid")

    BuildingType: str
    PrimaryPropertyType: str
    Neighborhood: str
    Latitude: float
    Longitude: float
    YearBuilt: int
    NumberofBuildings: float
    NumberofFloors: int
    PropertyGFAParking: int
    PropertyGFABuilding: int = 0
    LargestPropertyUseType: str
    SecondLargestPropertyUseType: str
    SecondLargestPropertyUseTypeGFA: float
    ThirdLargestPropertyUseType: str
    ThirdLargestPropertyUseTypeGFA: float = 0.0
    Has_NaturalGas: bool = False
    Has_Steam: bool = False


class EnergyPredictionResponse(BaseModel):
    """Energy consumption prediction for the Seattle building."""

    model_name: str
    energy_use_kbtu: float
    predicted_at: datetime
    units: str = "kBtu/an"
