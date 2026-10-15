from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Path, Query

from ..core import building_service as bs
from ..core.security import get_current_user
from ..db.models import Building
from ..db.session import SessionDep
from ..schemas.api import INTEGER_MAX
from ..schemas.buildings import (
    BuildingDetail,
    BuildingPage,
    BuildingSummary,
    BuildingYearFeatures,
)

router = APIRouter(
    prefix="/buildings",
    tags=["buildings"],
    dependencies=[Depends(get_current_user)],
)


def _identity(building: Building) -> dict[str, Any]:
    return {
        "building_id": building.id,
        "property_name": building.property_name,
        "address": building.address,
        "zip_code": building.zip_code,
        "neighborhood": building.neighborhood,
        "building_type": building.building_type,
        "primary_property_type": building.primary_property_type,
    }


@router.get("", response_model=BuildingPage)
def read_buildings(
    session: SessionDep,
    q: Annotated[
        str | None,
        Query(min_length=2, max_length=100, description="Nom ou adresse"),
    ] = None,
    year: Annotated[int | None, Query(ge=2015, le=2100)] = None,
    neighborhood: Annotated[str | None, Query(max_length=64)] = None,
    building_type: Annotated[str | None, Query(max_length=64)] = None,
    limit: Annotated[int, Query(ge=1, le=bs.MAX_PAGE_SIZE)] = 20,
    offset: Annotated[int, Query(ge=0, le=100_000)] = 0,
) -> BuildingPage:
    """Bâtiments jamais vus par l'entraînement, seuls prédictibles par identifiant."""
    filters = bs.BuildingFilters(
        q=q, year=year, neighborhood=neighborhood, building_type=building_type
    )
    found, total = bs.search_buildings(session, filters, limit=limit, offset=offset)
    return BuildingPage(
        items=[
            BuildingSummary(**_identity(building), years=years)
            for building, years in found
        ],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/{building_id}",
    response_model=BuildingDetail,
    responses={404: {"description": "Bâtiment inconnu ou déjà vu par l'entraînement"}},
)
def read_building(
    building_id: Annotated[int, Path(ge=0, le=INTEGER_MAX)], session: SessionDep
) -> BuildingDetail:
    found = bs.get_building(session, building_id)
    if found is None:
        raise HTTPException(404, f"Bâtiment {building_id} introuvable")
    building, years = found
    return BuildingDetail(
        **_identity(building),
        years=[BuildingYearFeatures.model_validate(year) for year in years],
    )
