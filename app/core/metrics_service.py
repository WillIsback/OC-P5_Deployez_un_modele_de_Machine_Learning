"""Chargement de la table de scores regroupée par cible."""

from __future__ import annotations

import os
import threading

from ..lib.tools import load_json

METRICS_PATH = os.getenv("MODEL_METRICS_PATH", "models/scores.json")

_metrics: dict | None = None
_lock = threading.Lock()


def load_metrics() -> dict:
    global _metrics
    if _metrics is None:
        with _lock:
            if _metrics is None:
                if not os.path.exists(METRICS_PATH):
                    raise FileNotFoundError(
                        f"Table de scores introuvable à {METRICS_PATH}. "
                        "Entraînez avec `uv run python -m app.training`."
                    )
                _metrics = load_json(METRICS_PATH)
    return _metrics


def get_metrics() -> dict:
    return load_metrics()


def is_available() -> bool:
    try:
        load_metrics()
        return True
    except Exception:  # noqa: BLE001
        return False
