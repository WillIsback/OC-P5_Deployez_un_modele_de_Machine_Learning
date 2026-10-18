"""Contexte de l'inférence zero-shot Kumo-Tabular : le jeu d'entraînement.

Kumo-Tabular prédit par analogie avec les exemples étiquetés qu'on lui passe
(*in-context learning*, aucun poids n'est modifié) : l'ordre de grandeur de ses
prédictions vient entièrement des étiquettes du contexte. Le contexte est donc
le jeu d'entraînement de CatBoost (même split, aucun bâtiment de test), exporté
par le pipeline dans ``models/kumo_context.csv`` à côté des ``.cbm``.

``KUMO_CONTEXT_SIZE`` réduit le contexte à un échantillon reproductible (la
latence croît avec le nombre de lignes) ; absent ou 0 : toutes les lignes.
"""

import os
from pathlib import Path

import pandas as pd

from ..schemas.api import FEATURE_COLUMNS, TARGETS

DEFAULT_CONTEXT_PATH = "models/kumo_context.csv"
_SEED = 42


def context_size() -> int | None:
    """Taille demandée par ``KUMO_CONTEXT_SIZE`` (``None`` : tout le contexte)."""
    raw = os.getenv("KUMO_CONTEXT_SIZE", "").strip()
    if not raw:
        return None
    if not raw.isdigit():
        raise ValueError(f"KUMO_CONTEXT_SIZE doit être un entier ≥ 0 : {raw!r}")
    return int(raw) or None


def write_context(X: pd.DataFrame, Y: pd.DataFrame, path: str | Path) -> Path:
    """Écrit le contexte (features + toutes les cibles) d'un jeu d'entraînement."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    columns = [t["column"] for t in TARGETS.values()]
    X[FEATURE_COLUMNS].join(Y[columns]).to_csv(path, index=False)
    return path


def build_context_df(
    target: str, path: str | Path | None = None, size: int | None = None
) -> pd.DataFrame:
    """Lignes de contexte pour ``target`` (features + cible)."""
    if target not in TARGETS:
        raise KeyError(f"Cible inconnue : {target}")
    path = Path(path or os.getenv("KUMO_CONTEXT_PATH", DEFAULT_CONTEXT_PATH))
    if not path.exists():
        raise FileNotFoundError(
            f"Contexte Kumo introuvable : {path}. Il est exporté par "
            "`python -m app.training`."
        )
    df = pd.read_csv(path)
    size = size if size is not None else context_size()
    if size is not None and size < len(df):
        df = df.sample(n=size, random_state=_SEED).reset_index(drop=True)
    return df[FEATURE_COLUMNS + [TARGETS[target]["column"]]]
