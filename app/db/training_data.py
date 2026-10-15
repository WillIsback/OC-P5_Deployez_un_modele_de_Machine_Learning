"""Lecture du jeu d'entraînement : building_years ⋈ buildings.split ⋈ building_actuals."""

from __future__ import annotations

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.mapping import TARGET_SQL, features_from_sql
from app.db.models import Building, BuildingActual, BuildingYear
from app.db.prepare import TRAINING_YEAR
from app.schemas.api import FEATURE_COLUMNS
from app.training.pipeline import TrainingData


def load_training_data(session: Session) -> TrainingData:
    """Seuls les bâtiments portant un split, de l'année d'entraînement, sans exclusion."""
    rows = session.execute(
        select(BuildingYear, BuildingActual, Building.split)
        .join(Building, Building.id == BuildingYear.building_id)
        .join(BuildingActual, BuildingActual.building_year_id == BuildingYear.id)
        .where(
            Building.split.is_not(None),
            BuildingYear.exclusion_reason.is_(None),
            BuildingYear.data_year == TRAINING_YEAR,
        )
        .order_by(BuildingYear.building_id)
    ).all()
    if not rows:
        raise RuntimeError(
            "Aucune ligne d'entraînement : lancez `python -m app.db.ingest` "
            "pour l'année d'entraînement."
        )
    index = pd.Index([y.building_id for y, _, _ in rows], name="building_id")
    X = pd.DataFrame([features_from_sql(y) for y, _, _ in rows], index=index)
    Y = pd.DataFrame(
        [{csv: getattr(a, col) for csv, col in TARGET_SQL.items()} for _, a, _ in rows],
        index=index,
    )
    split = pd.Series([s for _, _, s in rows], index=index)
    return TrainingData(X=X[FEATURE_COLUMNS], Y=Y, split=split)
