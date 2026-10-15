from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from ..core import metrics_service
from ..core import prediction_service as ps
from ..core.security import get_current_user
from ..db.mapping import features_from_sql
from ..db.models import BuildingYear, MlModel, Prediction
from ..db.registry import CATBOOST_NAME, KUMO_NAME, NoActiveModel
from ..db.session import SessionDep
from ..lib.tools import get_logger
from ..schemas.api import (
    BuildingPredictionRequest,
    ComparisonPredictionResponse,
    EnergyPredictionRequest,
    EnergyPredictionResponse,
    MetricsResponse,
    Model,
)

log = get_logger(__name__)

router = APIRouter(
    prefix="/model",
    tags=["model"],
    dependencies=[Depends(get_current_user)],
    responses={404: {"description": "Introuvable"}},
)

UNAVAILABLE = {503: {"description": "Modèle, traçabilité ou base indisponible"}}
BUILDING_RESPONSES = {
    403: {"description": "Bâtiment déjà vu par l'entraînement"},
    404: {"description": "Bâtiment ou année introuvable"},
    422: {"description": "Bâtiment hors périmètre du modèle"},
    **UNAVAILABLE,
}


@router.get("/list", response_model=list[Model])
def read_models_list(session: SessionDep):
    models = session.scalars(select(MlModel).order_by(MlModel.id))
    return [
        Model(
            id=m.id,
            name=m.name,
            version=m.version,
            is_active=m.is_active,
            created_at=m.created_at,
        )
        for m in models
    ]


@router.get(
    "/metrics",
    response_model=MetricsResponse,
    responses={404: {"description": "Fichier de métriques introuvable"}},
)
async def read_metrics():
    try:
        return MetricsResponse(**metrics_service.get_metrics())
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


def _api_request_id(request: Request) -> int:
    """Identifiant de trace ; sans lui, aucune prédiction (jamais d'input orphelin)."""
    api_request_id = getattr(request.state, "api_request_id", None)
    if api_request_id is None:
        raise HTTPException(503, "Traçabilité indisponible, prédiction refusée")
    return api_request_id


def _resolve(session: Session, payload: BuildingPredictionRequest) -> BuildingYear:
    try:
        return ps.resolve_features(session, payload.building_id, payload.data_year)
    except ps.BuildingNotFound:
        raise HTTPException(404, f"Bâtiment {payload.building_id} inconnu")
    except ps.BuildingSeen:
        raise HTTPException(
            403,
            f"Bâtiment {payload.building_id} déjà vu par l'entraînement : "
            "prédiction par identifiant refusée (voir GET /buildings)",
        )
    except ps.YearNotFound:
        raise HTTPException(
            404,
            f"Aucune donnée {payload.data_year} pour le bâtiment {payload.building_id}",
        )
    except ps.BuildingOutOfScope:
        raise HTTPException(
            422,
            f"Bâtiment {payload.building_id} hors périmètre du modèle "
            "(résidentiel ou données incomplètes)",
        )


def _input_from_building(
    session: Session, request: Request, payload: BuildingPredictionRequest
) -> ps.ModelInput:
    api_request_id = _api_request_id(request)
    year = _resolve(session, payload)
    return ps.ModelInput(
        features=features_from_sql(year),
        api_request_id=api_request_id,
        building_year_id=year.id,
    )


def _run(session: Session, inp: ps.ModelInput, model_name: str) -> Prediction:
    try:
        return ps.run_model(session, inp, model_name)
    except NoActiveModel:
        raise HTTPException(503, f"Aucun modèle actif : {model_name}")
    except SQLAlchemyError:
        raise  # géré par le handler « base indisponible »
    except Exception:
        log.exception("Échec du modèle %s", model_name)
        label = "Kumo-Tabular" if model_name == KUMO_NAME else "CatBoost"
        raise HTTPException(503, f"Modèle {label} indisponible")


def _response(
    prediction: Prediction, model_name: str, request: Request
) -> EnergyPredictionResponse:
    return EnergyPredictionResponse(
        model_name=model_name,
        energy_use_kbtu=prediction.energy_use_kbtu,
        ghg_emissions_tco2e=prediction.ghg_emissions_tco2e,
        predicted_at=prediction.predicted_at,
        prediction_id=prediction.id,
        request_id=request.state.request_id,
    )


@router.post(
    "/predict", response_model=EnergyPredictionResponse, responses=BUILDING_RESPONSES
)
def write_prediction(
    payload: BuildingPredictionRequest, request: Request, session: SessionDep
):
    inp = _input_from_building(session, request, payload)
    return _response(_run(session, inp, CATBOOST_NAME), CATBOOST_NAME, request)


@router.post(
    "/predict/features",
    response_model=EnergyPredictionResponse,
    responses=UNAVAILABLE,
)
def write_prediction_from_features(
    payload: EnergyPredictionRequest, request: Request, session: SessionDep
):
    inp = ps.ModelInput(
        features=ps.features_from_request(payload),
        api_request_id=_api_request_id(request),
    )
    return _response(_run(session, inp, CATBOOST_NAME), CATBOOST_NAME, request)


@router.post(
    "/predict/compare",
    response_model=ComparisonPredictionResponse,
    responses=BUILDING_RESPONSES,
)
def write_comparison(
    payload: BuildingPredictionRequest, request: Request, session: SessionDep
):
    inp = _input_from_building(session, request, payload)
    catboost = _run(session, inp, CATBOOST_NAME)
    kumo = _run(session, inp, KUMO_NAME)
    return ComparisonPredictionResponse(
        catboost_prediction=_response(catboost, CATBOOST_NAME, request),
        kumo_prediction=_response(kumo, KUMO_NAME, request),
    )
