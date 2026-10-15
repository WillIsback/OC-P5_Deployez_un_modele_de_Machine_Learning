"""Lecture du jeu d'entraînement : building_features ⋈ building_actuals."""

from __future__ import annotations

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.mapping import TARGET_SQL, features_from_sql
from app.db.models import BuildingActual, BuildingFeatures
from app.schemas.api import FEATURE_COLUMNS
from app.training.pipeline import TrainingData


def load_training_data(session: Session) -> TrainingData:
    rows = session.execute(
        select(BuildingFeatures, BuildingActual)
        .join(BuildingActual, BuildingActual.record_id == BuildingFeatures.record_id)
        .where(
            BuildingFeatures.dataset_role == "training",
            BuildingFeatures.is_training_eligible,
        )
        .order_by(BuildingFeatures.record_id)
    ).all()
    if not rows:
        raise RuntimeError(
            "Aucune ligne d'entraînement : lancez `python -m app.db.ingest` "
            "puis `python -m app.db.prepare`."
        )
    index = pd.Index([f.record_id for f, _ in rows], name="record_id")
    X = pd.DataFrame([features_from_sql(f) for f, _ in rows], index=index)
    Y = pd.DataFrame(
        [{csv: getattr(a, col) for csv, col in TARGET_SQL.items()} for _, a in rows],
        index=index,
    )
    split = pd.Series([f.split for f, _ in rows], index=index)
    return TrainingData(X=X[FEATURE_COLUMNS], Y=Y, split=split)
