from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException

from ..core import kumo_service, metrics_service, model_service
from ..core.security import get_current_user
from ..schemas.api import (
    ComparisonPredictionResponse,
    EnergyPredictionRequest,
    EnergyPredictionResponse,
    MetricsResponse,
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
    Model(
        id=2,
        name="catboost-emissions-seattle",
        created_at=datetime(2026, 1, 2, tzinfo=UTC),
    ),
    Model(
        id=3, name="kumo-tabular-zero-shot", created_at=datetime(2026, 1, 3, tzinfo=UTC)
    ),
]


@router.get("/list", response_model=list[Model])
async def read_models_list():
    return available_models


@router.get("/metrics", response_model=MetricsResponse)
async def read_metrics():
    try:
        return MetricsResponse(**metrics_service.get_metrics())
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.post(
    "/predict",
    response_model=EnergyPredictionResponse,
    responses={503: {"description": "Model not loaded"}},
)
async def write_prediction(payload: EnergyPredictionRequest):
    from starlette.concurrency import run_in_threadpool

    try:
        preds = await run_in_threadpool(model_service.predict_all, payload)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    return EnergyPredictionResponse(
        model_name="catboost-multitarget",
        energy_use_kbtu=preds["energy"],
        ghg_emissions_tco2e=preds["emissions"],
        predicted_at=datetime.now(UTC),
    )


@router.post(
    "/predict/compare",
    response_model=ComparisonPredictionResponse,
    responses={503: {"description": "One or both models could not be loaded"}},
)
async def write_comparison(payload: EnergyPredictionRequest):
    from starlette.concurrency import run_in_threadpool

    now = datetime.now(UTC)
    try:
        cb = await run_in_threadpool(model_service.predict_all, payload)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=503, detail=f"CatBoost: {exc}")
    try:
        km = await run_in_threadpool(kumo_service.predict_all, payload)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=503, detail=f"Kumo-Tabular: {exc}")

    def resp(name, energy, emissions):
        return EnergyPredictionResponse(
            model_name=name,
            energy_use_kbtu=energy,
            ghg_emissions_tco2e=emissions,
            predicted_at=now,
        )

    return ComparisonPredictionResponse(
        catboost_prediction=resp("catboost-multitarget", cb["energy"], cb["emissions"]),
        kumo_prediction=resp("kumo-tabular-zero-shot", km["energy"], km["emissions"]),
    )
