"""Prédictions tracées : une ligne `predictions` par modèle appelé, entrée figée."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pandas as pd
from sqlalchemy import exists, select
from sqlalchemy.orm import Session

from app.core import kumo_service, model_service
from app.db.mapping import FLAG_COLUMNS
from app.db.models import Building, BuildingYear, MlModel, Prediction
from app.db.registry import KUMO_NAME, active_model, model_by_version
from app.schemas.api import FEATURE_COLUMNS, TARGETS, EnergyPredictionRequest


class BuildingNotFound(LookupError):
    """Aucun bâtiment avec cet identifiant."""


class YearNotFound(LookupError):
    """Le bâtiment existe mais pas pour l'année demandée."""


class BuildingOutOfScope(LookupError):
    """Le bâtiment n'a aucune feature exploitable (résidentiel, données incomplètes)."""


class BuildingSeen(LookupError):
    """Le bâtiment a servi à l'entraînement ou à son évaluation (train ou test)."""


@dataclass(frozen=True)
class ModelInput:
    """Entrée du modèle et origine : requête API, ligne d'année si bâtiment connu."""

    features: dict[str, Any]
    api_request_id: int
    building_year_id: int | None = None


def resolve_features(
    session: Session, building_id: int, data_year: int | None = None
) -> BuildingYear:
    """Features du bâtiment pour l'année demandée (ou la plus récente)."""
    building = session.get(Building, building_id)
    if building is None:
        raise BuildingNotFound(building_id)
    if building.split is not None:
        raise BuildingSeen(building_id)
    base = select(BuildingYear).where(BuildingYear.building_id == building_id)
    if data_year is None:
        row = session.scalars(
            base.order_by(BuildingYear.data_year.desc()).limit(1)
        ).first()
        if row is None:
            raise BuildingOutOfScope(building_id)
        return row
    row = session.scalars(base.where(BuildingYear.data_year == data_year)).first()
    if row is not None:
        return row
    # Aucune année du tout : hors périmètre ; d'autres années existent : introuvable.
    has_years = session.scalar(
        select(exists().where(BuildingYear.building_id == building_id))
    )
    if has_years:
        raise YearNotFound(data_year)
    raise BuildingOutOfScope(building_id)


def features_from_request(request: EnergyPredictionRequest) -> dict[str, Any]:
    """Saisie libre → features nommées comme FEATURE_COLUMNS (flags en int)."""
    data = request.model_dump()
    data["PropertyGFABuilding(s)"] = data.pop("PropertyGFABuilding")
    for flag in FLAG_COLUMNS:
        data[flag] = int(data[flag])
    return {name: data[name] for name in FEATURE_COLUMNS}


def _served_catboost(session: Session, model_name: str) -> MlModel:
    """Ligne du registre de la version CatBoost réellement chargée en mémoire.

    Repli sur la version active si aucun ``version.json`` n'accompagne les .cbm.
    """
    version = model_service.loaded_version()
    if version is None:
        return active_model(session, model_name)
    return model_by_version(
        session, version.get("name", model_name), version["version"]
    )


def run_model(session: Session, inp: ModelInput, model_name: str) -> Prediction:
    """Prédit depuis l'entrée figée et enregistre la prédiction avec elle."""
    frame = pd.DataFrame([inp.features])[FEATURE_COLUMNS]
    if model_name == KUMO_NAME:
        # Prédire d'abord : aucune connexion tenue pendant l'inférence (~20 s/cible).
        values = {t: float(kumo_service.predict_batch(frame, t)[0]) for t in TARGETS}
        model = active_model(session, model_name)
    else:
        # Prédire d'abord : le chargement des .cbm fige la version à tracer.
        values = {t: float(v[0]) for t, v in model_service.predict_frame(frame).items()}
        model = _served_catboost(session, model_name)
    prediction = Prediction(
        api_request_id=inp.api_request_id,
        building_year_id=inp.building_year_id,
        model_id=model.id,
        input_features=inp.features,
        energy_use_kbtu=values["energy"],
        ghg_emissions_tco2e=values["emissions"],
    )
    session.add(prediction)
    session.commit()
    return prediction
