"""Logging, wrappers (décorateurs) et helpers transverses."""

from __future__ import annotations

import functools
import json
import logging
import os
import random
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any, TypeVar

import numpy as np
from sklearn.metrics import r2_score

_LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s %(message)s"

F = TypeVar("F", bound=Callable[..., Any])


def setup_logging(level: str = "INFO") -> None:
    """Configure le logging racine (idempotent via basicConfig)."""
    logging.basicConfig(level=level, format=_LOG_FORMAT)


def get_logger(name: str) -> logging.Logger:
    """Retourne un logger configuré (idempotent)."""
    setup_logging()
    return logging.getLogger(name)


def timed(label: str | None = None) -> Callable[[F], F]:
    """Décorateur : logue la durée d'exécution de la fonction."""

    def deco(fn: F) -> F:
        @functools.wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            log = get_logger(fn.__module__)
            start = time.perf_counter()
            try:
                return fn(*args, **kwargs)
            finally:
                log.info(
                    "%s took %.2fs",
                    label or fn.__qualname__,
                    time.perf_counter() - start,
                )

        return wrapper  # type: ignore[return-value]

    return deco


def log_calls(fn: F) -> F:  # noqa: UP047
    """Décorateur : logue l'entrée et la sortie d'une fonction."""

    @functools.wraps(fn)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        log = get_logger(fn.__module__)
        log.debug("call %s", fn.__qualname__)
        result = fn(*args, **kwargs)
        log.debug("done %s", fn.__qualname__)
        return result

    return wrapper  # type: ignore[return-value]


def sanitize_metric_key(name: str) -> str:
    """Rend une clé de métrique compatible MLflow (`%` -> `pct`)."""
    return name.replace("%", "pct")


def log_mlflow_metrics(prefix: str, metrics: dict[str, float]) -> None:
    """Logue des métriques MLflow sous ``prefix_<nom>`` (clés nettoyées)."""
    import mlflow

    for name, value in metrics.items():
        mlflow.log_metric(f"{prefix}_{sanitize_metric_key(name)}", float(value))


def ensure_dir(path: str | os.PathLike[str]) -> Path:
    """Crée le dossier (et parents) s'il n'existe pas, retourne son Path."""
    p = Path(path)
    p.mkdir(parents=True, exist_ok=True)
    return p


def save_json(path: str | os.PathLike[str], obj: Any) -> None:
    """Écrit ``obj`` en JSON UTF-8 indenté (crée les dossiers parents)."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2, ensure_ascii=False)


def load_json(path: str | os.PathLike[str]) -> Any:
    """Lit un fichier JSON UTF-8."""
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def set_seed(seed: int = 42) -> None:
    """Fixe les graines ``random`` et ``numpy``.

    ``PYTHONHASHSEED`` n'est pas modifiable à chaud : il doit être défini
    avant le démarrage de l'interpréteur pour réellement fixer le hash.
    """
    random.seed(seed)
    np.random.seed(seed)


def metrics_reelles(y_true: Any, y_pred: Any) -> dict[str, float]:
    """Métriques en unités réelles : R2, MAE, MedAE, MedAPE_%."""
    y_true = np.asarray(y_true, dtype=float)
    y_pred = np.asarray(y_pred, dtype=float)
    err = np.abs(y_true - y_pred)
    with np.errstate(divide="ignore", invalid="ignore"):
        medape = np.nanmedian(err / y_true) * 100
    return {
        "R2": float(r2_score(y_true, y_pred)),
        "MAE": float(np.mean(err)),
        "MedAE": float(np.median(err)),
        "MedAPE_%": float(medape),
    }
