"""Pipeline d'entraînement multi-cible (CatBoost + évaluation Kumo)."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
from catboost import CatBoostRegressor
from sklearn.model_selection import train_test_split

from app.lib.tools import get_logger, timed
from app.schemas.api import FEATURE_COLUMNS
from app.training import data_processing as dp

log = get_logger(__name__)

# Grille grossière pour la CV (pré-réglage).
COARSE_GRID = {
    "iterations": [2000],
    "learning_rate": [0.03, 0.05, 0.08],
    "depth": [4, 5, 6],
    "l2_leaf_reg": [3.0, 6.0, 10.0],
}
MAX_TREES_BUDGET = 1200  # garde-fou "overkill"


class TrainPipeline:
    """Orchestre split -> FE -> CV -> pré-réglage -> fine-tuning -> train -> éval."""

    def __init__(
        self,
        df_raw: pd.DataFrame | None = None,
        *,
        csv_path: str | Path | None = None,
        output_dir: str | Path = "models",
        test_size: float = 0.2,
        seed: int = 42,
        cv_splits: int = 5,
        mlflow_tracking_uri: str | None = None,
        mlflow_experiment: str | None = None,
    ) -> None:
        if df_raw is None and csv_path is None:
            raise ValueError("Fournir df_raw ou csv_path.")
        if df_raw is not None:
            self.df_raw = df_raw
        else:
            csv_path = Path(csv_path)
            if not csv_path.exists():
                raise FileNotFoundError(f"Dataset introuvable : {csv_path}")
            self.df_raw = pd.read_csv(csv_path)
        self.output_dir = Path(output_dir)
        self.test_size = test_size
        self.seed = seed
        self.cv_splits = cv_splits
        self.mlflow_tracking_uri = mlflow_tracking_uri
        self.mlflow_experiment = mlflow_experiment
        # état rempli par les étapes
        self.df_clean: pd.DataFrame | None = None
        self.idx_train: pd.Index | None = None
        self.idx_test: pd.Index | None = None
        self.X_train: pd.DataFrame | None = None
        self.X_test: pd.DataFrame | None = None
        self.Y_train: pd.DataFrame | None = None
        self.Y_test: pd.DataFrame | None = None
        self.cv_results: dict[str, list] = {}
        self.pre_tuned_grid: dict[str, dict] = {}
        self.best_params: dict[str, dict] = {}
        self.models: dict[str, CatBoostRegressor] = {}
        self.metrics: dict = {}

    def _require_split(self) -> None:
        """Garde commune : vérifie que split() a bien préparé l'état."""
        if self.df_clean is None or self.idx_train is None:
            raise RuntimeError("Appelez split() avant cette étape.")

    @timed("split")
    def split(self) -> TrainPipeline:
        """Nettoyage puis découpe train/test (les indices bruts sont conservés)."""
        self.df_clean = dp.build_clean(self.df_raw)
        if len(self.df_clean) < 2:
            raise ValueError(
                f"Jeu nettoyé trop petit pour un split : {len(self.df_clean)} lignes"
            )
        idx = self.df_clean.index
        self.idx_train, self.idx_test = train_test_split(
            idx, test_size=self.test_size, random_state=self.seed
        )
        log.info("split : %d train / %d test", len(self.idx_train), len(self.idx_test))
        return self

    @timed("feature_engineering")
    def feature_engineering(self) -> TrainPipeline:
        """Encodage stateless (catégorielles en str + flags), appliqué
        identiquement à train et test."""
        self._require_split()
        features = [
            c for c in FEATURE_COLUMNS if c not in ("Has_NaturalGas", "Has_Steam")
        ]
        for name, idx in (("train", self.idx_train), ("test", self.idx_test)):
            X = self.df_clean.loc[idx, features]
            flags = dp.build_flags(self.df_raw, self.df_clean.loc[idx])
            setattr(self, f"X_{name}", dp.prepare_catboost(X, flags))
            setattr(self, f"Y_{name}", self.df_clean.loc[idx, dp.TARGET_COLUMNS])
        return self
