"""Réponses de la consultation des bâtiments : aucune valeur réelle exposée."""

from pydantic import BaseModel, ConfigDict


class BuildingIdentity(BaseModel):
    building_id: int
    property_name: str | None
    address: str | None
    zip_code: str | None
    neighborhood: str | None
    building_type: str | None
    primary_property_type: str | None


class BuildingSummary(BuildingIdentity):
    years: list[int]


class BuildingYearFeatures(BaseModel):
    """Les 17 features du modèle pour une année (noms des colonnes SQL)."""

    model_config = ConfigDict(from_attributes=True)

    data_year: int
    building_type: str
    primary_property_type: str
    neighborhood: str
    latitude: float
    longitude: float
    year_built: int
    number_of_buildings: float | None
    number_of_floors: int
    property_gfa_parking: int
    property_gfa_buildings: int
    largest_property_use_type: str
    second_largest_property_use_type: str
    second_largest_property_use_type_gfa: float | None
    third_largest_property_use_type: str
    third_largest_property_use_type_gfa: float | None
    has_natural_gas: bool
    has_steam: bool


class BuildingDetail(BuildingIdentity):
    years: list[BuildingYearFeatures]


class BuildingPage(BaseModel):
    items: list[BuildingSummary]
    total: int
    limit: int
    offset: int
