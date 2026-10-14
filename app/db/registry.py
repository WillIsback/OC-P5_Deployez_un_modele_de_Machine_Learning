"""Registre des modèles (`ml_models`) : version active et enregistrement."""

from __future__ import annotations

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.db.models import MlModel

CATBOOST_NAME = "catboost-multitarget"
KUMO_NAME = "kumo-tabular-zero-shot"


class NoActiveModel(LookupError):
    """Aucune version active pour ce nom de modèle."""


def active_model(session: Session, name: str) -> MlModel:
    model = session.scalar(
        select(MlModel).where(MlModel.name == name, MlModel.is_active)
    )
    if model is None:
        raise NoActiveModel(name)
    return model


def model_by_version(session: Session, name: str, version: str) -> MlModel:
    """Ligne du registre d'une version précise (active ou non)."""
    model = session.scalar(
        select(MlModel).where(MlModel.name == name, MlModel.version == version)
    )
    if model is None:
        raise NoActiveModel(f"{name} {version}")
    return model


def register_model(
    session: Session,
    *,
    name: str,
    version: str,
    mlflow_run_id: str | None,
    artifact_path: str | None,
) -> MlModel:
    """Insère une version et la rend active (l'ancienne est désactivée)."""
    session.execute(
        update(MlModel)
        .where(MlModel.name == name, MlModel.is_active)
        .values(is_active=False)
    )
    model = MlModel(
        name=name,
        version=version,
        mlflow_run_id=mlflow_run_id,
        artifact_path=artifact_path,
        is_active=True,
    )
    session.add(model)
    session.commit()
    return model
