"""Kumo-Tabular zero-shot (few-shot) multi-cible.

NVIDIA Kumo-Tabular est un modèle tabulaire fondation utilisé en *in-context
learning* : un petit jeu d'exemples de référence (contexte) est fourni au
modèle en même temps que la requête, sans entraînement par jeu de données.

Un **modèle partagé** est chargé une seule fois ; chaque cible dispose de sa
propre table de contexte (mise en cache), et la prédiction peut se faire par
lots.
"""

import threading

import numpy as np
import pandas as pd
import torch

from ..lib.tools import get_logger
from ..schemas.api import (
    CAT_FEATURES,
    FEATURE_COLUMNS,
    TARGETS,
    EnergyPredictionRequest,
)
from ._kumo_context import build_context_df

# ---------------------------------------------------------------------------
# Détection paresseuse du device – CUDA si disponible, sinon CPU.
# ---------------------------------------------------------------------------
_DEVICE = torch.device("cuda" if torch.cuda.is_available() else "cpu")

_log = get_logger(__name__)

# ---------------------------------------------------------------------------
# Singleton paresseux du modèle KumoTabular partagé entre toutes les cibles.
# ---------------------------------------------------------------------------
_model: object | None = None
_lock = threading.Lock()

# Cache paresseux d'une table de contexte TableTensor par cible.
_context_tables: dict[str, object] = {}
_context_lock = threading.Lock()


def _import_sdm():
    """Import paresseux de ``sdm`` (le module reste importable sans lui)."""
    import sdm

    return sdm


def load_model():
    """Charge le modèle KumoTabular une seule fois (singleton paresseux)."""
    global _model
    if _model is None:
        with _lock:
            if _model is None:
                sdm = _import_sdm()
                _model = sdm.models.KumoTabular(task="regression", device=_DEVICE)
    return _model


def _context_table(target: str):
    """Table de contexte :class:`sdm.TableTensor` de ``target`` (cache)."""
    if target not in TARGETS:
        raise KeyError(f"Cible inconnue : {target}")

    table = _context_tables.get(target)
    if table is None:
        with _context_lock:
            table = _context_tables.get(target)
            if table is None:
                sdm = _import_sdm()
                df = build_context_df(target)
                for col in CAT_FEATURES:
                    df[col] = df[col].astype(str)
                table = sdm.TableTensor.from_pandas(
                    df=df,
                    stypes=sdm.infer_stypes(df),
                    device=_DEVICE,
                )
                _context_tables[target] = table
    return table


def _to_table(df: pd.DataFrame):
    """Convertit un DataFrame de features en :class:`sdm.TableTensor`.

    Gère les deux nommages de colonne : ``PropertyGFABuilding`` (issu de
    ``request.model_dump()``) et ``PropertyGFABuilding(s)`` (issu de la
    matrice de features ``FEATURE_COLUMNS``).
    """
    sdm = _import_sdm()

    d = df.copy()
    if "PropertyGFABuilding" in d.columns:
        d["PropertyGFABuilding(s)"] = d.pop("PropertyGFABuilding")

    for col in CAT_FEATURES:
        d[col] = d[col].astype(str)
    for col in ("Has_NaturalGas", "Has_Steam"):
        d[col] = d[col].astype(float)

    d = d[FEATURE_COLUMNS]
    return sdm.TableTensor.from_pandas(
        df=d,
        stypes=sdm.infer_stypes(d),
        device=_DEVICE,
    )


def _predict_dataframe(df: pd.DataFrame, target: str) -> np.ndarray:
    """Prédit ``target`` pour toutes les lignes de ``df`` (retourne un vecteur)."""
    if target not in TARGETS:
        raise KeyError(f"Cible inconnue : {target}")

    model = load_model()
    context = _context_table(target)
    target_column = TARGETS[target]["column"]
    query_table = _to_table(df)

    with torch.no_grad():
        with torch.amp.autocast(
            _DEVICE.type,
            torch.float16,
            enabled=_DEVICE.type == "cuda",
        ):
            output = model(
                x_context=context.drop_columns(target_column),
                y_context=context[target_column],
                x_query=query_table,
                num_estimators=4,
            )
        pred = output.numerical.mean(dim=-1)

    return np.asarray(pred.detach().cpu().numpy(), dtype=float).reshape(-1)


def predict(request: EnergyPredictionRequest, target: str) -> float:
    """Prédit ``target`` pour une requête unique (unités réelles)."""
    df = pd.DataFrame([request.model_dump()])
    return float(_predict_dataframe(df, target)[0])


def predict_all(request: EnergyPredictionRequest) -> dict[str, float]:
    """Prédit toutes les cibles pour une requête unique."""
    return {target: predict(request, target) for target in TARGETS}


def predict_batch(X, target: str) -> np.ndarray:
    """Prédit ``target`` pour une matrice de features (colonnes FEATURE_COLUMNS)."""
    if getattr(X, "ndim", 2) != 2:
        raise ValueError("predict_batch attend une matrice 2-D de features.")
    if not isinstance(X, pd.DataFrame):
        X = pd.DataFrame(np.asarray(X), columns=FEATURE_COLUMNS)
    return _predict_dataframe(X, target)


def is_available() -> bool:
    """Indique si le modèle Kumo-Tabular peut être chargé."""
    try:
        load_model()
        return True
    except Exception as exc:  # noqa: BLE001
        _log.warning("Kumo-Tabular indisponible : %s", exc)
        return False
