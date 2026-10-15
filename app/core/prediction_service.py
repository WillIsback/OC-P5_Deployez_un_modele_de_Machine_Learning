"""Prédictions tracées : snapshot de l'input en base, puis appel du modèle."""

from __future__ import annotations

from typing import Any

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import kumo_service, model_service
from app.db.mapping import features_from_sql, features_to_sql
from app.db.models import (
    Building,
    BuildingFeatures,
    BuildingRecordRaw,
    MlModel,
    Prediction,
    PredictionInput,
)
from app.db.registry import KUMO_NAME, active_model, model_by_version
from app.schemas.api import FEATURE_COLUMNS, TARGETS, EnergyPredictionRequest


class BuildingNotFound(LookupError):
    """Aucun bâtiment avec cet identifiant."""


class YearNotFound(LookupError):
    """Le bâtiment existe mais pas pour l'année demandée."""


class BuildingOutOfScope(LookupError):
    """Le bâtiment n'a aucune feature exploitable (résidentiel, données incomplètes)."""


def resolve_features(
    session: Session, building_id: int, data_year: int | None = None
) -> BuildingFeatures:
    """Features du bâtiment pour l'année demandée (ou la plus récente).

    Ne lit que id/building_id/data_year de building_records_raw (droit par
    colonne du rôle API, aucune PII).
    """
    if session.get(Building, building_id) is None:
        raise BuildingNotFound(building_id)
    base = (
        select(BuildingFeatures)
        .join(BuildingRecordRaw, BuildingRecordRaw.id == BuildingFeatures.record_id)
        .where(BuildingRecordRaw.building_id == building_id)
    )
    if data_year is None:
        row = session.scalars(
            base.order_by(BuildingRecordRaw.data_year.desc()).limit(1)
        ).first()
        if row is None:
            raise BuildingOutOfScope(building_id)
        return row
    row = session.scalars(base.where(BuildingRecordRaw.data_year == data_year)).first()
    if row is None:
        # Enregistrement brut présent sans features (exclu par prepare) : hors
        # périmètre ; année absente du brut : introuvable.
        raw_id = session.scalar(
            select(BuildingRecordRaw.id).where(
                BuildingRecordRaw.building_id == building_id,
                BuildingRecordRaw.data_year == data_year,
            )
        )
        if raw_id is not None:
            raise BuildingOutOfScope(building_id)
        raise YearNotFound(data_year)
    return row


def features_from_request(request: EnergyPredictionRequest) -> dict[str, Any]:
    """Saisie libre → colonnes SQL de ``prediction_inputs``."""
    data = request.model_dump()
    data["PropertyGFABuilding(s)"] = data.pop("PropertyGFABuilding")
    return features_to_sql(data)


def create_input(
    session: Session,
    *,
    features: dict[str, Any],
    source: str,
    api_request_id: int | None,
    building_record_id: int | None = None,
) -> PredictionInput:
    """Enregistre et commit le snapshot AVANT tout appel au modèle."""
    inp = PredictionInput(
        input_source=source,
        api_request_id=api_request_id,
        building_record_id=building_record_id,
        **features,
    )
    session.add(inp)
    session.commit()
    return inp


def input_frame(inp: PredictionInput) -> pd.DataFrame:
    return pd.DataFrame([features_from_sql(inp)])[FEATURE_COLUMNS]


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


def run_model(session: Session, inp: PredictionInput, model_name: str) -> Prediction:
    """Prédit depuis la ligne stockée (pas depuis le payload HTTP)."""
    frame = input_frame(inp)
    if model_name == KUMO_NAME:
        model = active_model(session, model_name)
        values = {t: float(kumo_service.predict_batch(frame, t)[0]) for t in TARGETS}
    else:
        # Prédire d'abord : le chargement des .cbm fige la version à tracer.
        values = {t: float(v[0]) for t, v in model_service.predict_frame(frame).items()}
        model = _served_catboost(session, model_name)
    prediction = Prediction(
        prediction_input_id=inp.id,
        model_id=model.id,
        energy_use_kbtu=values["energy"],
        ghg_emissions_tco2e=values["emissions"],
    )
    session.add(prediction)
    session.commit()
    return prediction
