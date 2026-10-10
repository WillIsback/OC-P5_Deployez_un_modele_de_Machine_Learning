from datetime import datetime

from pydantic import BaseModel, ConfigDict

CAT_FEATURES = [
    "BuildingType",
    "PrimaryPropertyType",
    "Neighborhood",
    "LargestPropertyUseType",
    "SecondLargestPropertyUseType",
    "ThirdLargestPropertyUseType",
]

FEATURE_COLUMNS = [
    "BuildingType",
    "PrimaryPropertyType",
    "Neighborhood",
    "Latitude",
    "Longitude",
    "YearBuilt",
    "NumberofBuildings",
    "NumberofFloors",
    "PropertyGFAParking",
    "PropertyGFABuilding(s)",
    "LargestPropertyUseType",
    "SecondLargestPropertyUseType",
    "SecondLargestPropertyUseTypeGFA",
    "ThirdLargestPropertyUseType",
    "ThirdLargestPropertyUseTypeGFA",
    "Has_NaturalGas",
    "Has_Steam",
]

TARGETS = {
    "energy": {"column": "SiteEnergyUse(kBtu)", "unit": "kBtu/an"},
    "emissions": {"column": "TotalGHGEmissions", "unit": "t CO2e/an"},
}


class Model(BaseModel):
    id: int
    name: str
    created_at: datetime


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
    """Prédictions pour les deux cibles du modèle."""

    model_name: str
    energy_use_kbtu: float
    ghg_emissions_tco2e: float = 0.0
    predicted_at: datetime
    units: str = "kBtu/an"
    emissions_units: str = "t CO2e/an"


class ModelScores(BaseModel):
    R2: float
    MAE: float
    MedAE: float
    MedAPE_pct: float


class TargetScores(BaseModel):
    unit: str
    models: dict[str, ModelScores]


class MetricsResponse(BaseModel):
    """Table de scores regroupée par cible (modèles CatBoost et Kumo)."""

    targets: dict[str, TargetScores]


class ComparisonPredictionResponse(BaseModel):
    """Predictions from both CatBoost (trained) and Kumo-Tabular (zero-shot)."""

    catboost_prediction: EnergyPredictionResponse
    kumo_prediction: EnergyPredictionResponse
    comparison_note: str = (
        "Comparaison entre CatBoost (modèle entraîné sur les données Seattle) "
        "et Kumo-Tabular (modèle zero-shot / few-shot sans entraînement préalable)"
    )
    catboost_model_name: str = "catboost-energy-seattle"
    kumo_model_name: str = "kumo-tabular-zero-shot"
