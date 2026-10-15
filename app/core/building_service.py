"""Consultation des bâtiments jamais vus par l'entraînement (ni train ni test)."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from sqlalchemy import exists, func, or_, select
from sqlalchemy.orm import Session

from app.db.models import Building, BuildingYear

MAX_PAGE_SIZE = 100


@dataclass(frozen=True)
class BuildingFilters:
    q: str | None = None
    year: int | None = None
    neighborhood: str | None = None
    building_type: str | None = None


def unseen_conditions() -> list:
    """Seule définition de « consultable » : jamais vu, avec au moins une année."""
    return [
        Building.split.is_(None),
        exists().where(BuildingYear.building_id == Building.id),
    ]


def _escape_like(term: str) -> str:
    return term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _conditions(filters: BuildingFilters) -> list:
    conditions = unseen_conditions()
    if filters.q and filters.q.strip():
        pattern = f"%{_escape_like(filters.q.strip())}%"
        conditions.append(
            or_(
                Building.property_name.ilike(pattern, escape="\\"),
                Building.address.ilike(pattern, escape="\\"),
            )
        )
    if filters.year is not None:
        conditions.append(
            exists().where(
                BuildingYear.building_id == Building.id,
                BuildingYear.data_year == filters.year,
            )
        )
    if filters.neighborhood:
        conditions.append(
            func.upper(Building.neighborhood) == filters.neighborhood.strip().upper()
        )
    if filters.building_type:
        conditions.append(
            func.lower(Building.building_type) == filters.building_type.strip().lower()
        )
    return conditions


def _years_by_building(session: Session, ids: list[int]) -> dict[int, list[int]]:
    rows = session.execute(
        select(BuildingYear.building_id, BuildingYear.data_year)
        .where(BuildingYear.building_id.in_(ids))
        .order_by(BuildingYear.data_year)
    ).all()
    years: dict[int, list[int]] = defaultdict(list)
    for building_id, year in rows:
        years[building_id].append(year)
    return years


def search_buildings(
    session: Session, filters: BuildingFilters, *, limit: int, offset: int
) -> tuple[list[tuple[Building, list[int]]], int]:
    """Page de bâtiments consultables avec leurs années, et le total filtré."""
    conditions = _conditions(filters)
    total = session.scalar(
        select(func.count()).select_from(Building).where(*conditions)
    )
    buildings = session.scalars(
        select(Building)
        .where(*conditions)
        .order_by(Building.id)
        .limit(limit)
        .offset(offset)
    ).all()
    years = _years_by_building(session, [b.id for b in buildings])
    return [(b, years[b.id]) for b in buildings], total


def get_building(
    session: Session, building_id: int
) -> tuple[Building, list[BuildingYear]] | None:
    """Bâtiment consultable et ses lignes d'année ; None s'il est vu ou inconnu."""
    building = session.scalar(
        select(Building).where(Building.id == building_id, *unseen_conditions())
    )
    if building is None:
        return None
    years = session.scalars(
        select(BuildingYear)
        .where(BuildingYear.building_id == building_id)
        .order_by(BuildingYear.data_year)
    ).all()
    return building, list(years)
