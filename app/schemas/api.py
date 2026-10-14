from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

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


# Bornes alignées sur les types SQL (app/db/models.py) : une saisie hors bornes
# est refusée en 422 au lieu d'échouer en 500 à l'insertion.
SMALLINT_MAX = 32_767
INTEGER_MAX = 2_147_483_647

Category = Annotated[str, Field(max_length=64)]  # VARCHAR(64)
NonNegativeSmallInt = Annotated[int, Field(ge=0, le=SMALLINT_MAX)]  # SMALLINT
NonNegativeInt = Annotated[int, Field(ge=0, le=INTEGER_MAX)]  # INTEGER
NonNegativeFloat = Annotated[float, Field(ge=0)]  # DOUBLE PRECISION


class Model(BaseModel):
    id: int
    name: str
    version: str
    is_active: bool
    created_at: datetime


class EnergyPredictionRequest(BaseModel):
    """Input features for the Seattle building energy consumption model."""

    model_config = ConfigDict(extra="forbid")

    BuildingType: Category
    PrimaryPropertyType: Category
    Neighborhood: Category
    Latitude: Annotated[float, Field(ge=-90, le=90)]
    Longitude: Annotated[float, Field(ge=-180, le=180)]
    YearBuilt: NonNegativeSmallInt
    NumberofBuildings: NonNegativeFloat
    NumberofFloors: NonNegativeSmallInt
    PropertyGFAParking: NonNegativeInt
    PropertyGFABuilding: NonNegativeInt = 0
    LargestPropertyUseType: Category
    SecondLargestPropertyUseType: Category
    SecondLargestPropertyUseTypeGFA: NonNegativeFloat
    ThirdLargestPropertyUseType: Category
    ThirdLargestPropertyUseTypeGFA: NonNegativeFloat = 0.0
    Has_NaturalGas: bool = False
    Has_Steam: bool = False


class BuildingPredictionRequest(BaseModel):
    """Prédiction d'un bâtiment connu ; année la plus récente si absente."""

    model_config = ConfigDict(extra="forbid")

    building_id: NonNegativeInt  # INTEGER
    data_year: NonNegativeSmallInt | None = None  # SMALLINT


class EnergyPredictionResponse(BaseModel):
    """Prédictions pour les deux cibles du modèle."""

    model_name: str
    energy_use_kbtu: float
    ghg_emissions_tco2e: float = 0.0
    predicted_at: datetime
    units: str = "kBtu/an"
    emissions_units: str = "t CO2e/an"
    prediction_id: int | None = None
    request_id: str | None = None


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
    catboost_model_name: str = "catboost-multitarget"
    kumo_model_name: str = "kumo-tabular-zero-shot"
