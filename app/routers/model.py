from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException

from ..core import model_service
from ..core.security import get_current_user
from ..schemas.api import (
    EnergyPredictionRequest,
    EnergyPredictionResponse,
    Model,
)

router = APIRouter(
    prefix="/model",
    tags=["model"],
    dependencies=[Depends(get_current_user)],
    responses={404: {"description": "Not found"}},
)

available_models = [
    Model(
        id=1,
        name="catboost-energy-seattle",
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
    ),
]


@router.get("/list", response_model=list[Model])
async def read_models_list():
    return available_models


@router.post(
    "/predict",
    response_model=EnergyPredictionResponse,
    responses={503: {"description": "Model not loaded"}},
)
async def write_prediction(payload: EnergyPredictionRequest):
    try:
        energy_use_kbtu = model_service.predict_energy(payload)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    return EnergyPredictionResponse(
        model_name=model_service.MODEL_PATH,
        energy_use_kbtu=energy_use_kbtu,
        predicted_at=datetime.now(UTC),
    )
