"""Pipeline d'entraînement multi-cible (CatBoost + évaluation Kumo)."""

from __future__ import annotations

from collections.abc import Iterator
from itertools import product
from pathlib import Path

import numpy as np
import pandas as pd
from catboost import CatBoostRegressor
from sklearn.model_selection import KFold, train_test_split

from app.lib.tools import ensure_dir, get_logger, metrics_reelles, timed
from app.schemas.api import CAT_FEATURES, FEATURE_COLUMNS
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

    def _require_split(self, *, require_features: bool = False) -> None:
        """Garde commune : vérifie que split() a bien préparé l'état."""
        if self.df_clean is None or self.idx_train is None:
            raise RuntimeError("Appelez split() avant cette étape.")
        if require_features and (self.X_train is None or self.Y_train is None):
            raise RuntimeError(
                "Appelez split() puis feature_engineering() avant cette étape."
            )

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

    def _fit_early_stopping(
        self,
        X_fit: pd.DataFrame,
        y_fit_log: pd.Series,
        X_val: pd.DataFrame,
        y_val_log: pd.Series,
        params: dict,
    ) -> CatBoostRegressor:
        model = CatBoostRegressor(
            random_seed=self.seed,
            loss_function="RMSE",
            verbose=0,
            early_stopping_rounds=100,
            **params,
        )
        model.fit(
            X_fit,
            y_fit_log,
            cat_features=CAT_FEATURES,
            eval_set=(X_val, y_val_log),
            use_best_model=True,
        )
        return model

    def _yield_grid(self, grid: dict) -> Iterator[dict]:
        keys = list(grid)
        for combo in product(*(grid[k] for k in keys)):
            yield dict(zip(keys, combo))

    @timed("cross_validate")
    def cross_validate(self) -> TrainPipeline:
        """CV sur le train, pour chaque cible et chaque config de COARSE_GRID."""
        self._require_split(require_features=True)
        kf = KFold(n_splits=self.cv_splits, shuffle=True, random_state=self.seed)
        for target in dp.TARGETS:
            y_log = np.log1p(self.Y_train[dp.TARGETS[target]["column"]])
            folds = [
                (tr, va, np.expm1(y_log.iloc[va])) for tr, va in kf.split(self.X_train)
            ]
            results = []
            for params in self._yield_grid(COARSE_GRID):
                per_fold = []
                for tr, va, y_val_real in folds:
                    model = self._fit_early_stopping(
                        self.X_train.iloc[tr],
                        y_log.iloc[tr],
                        self.X_train.iloc[va],
                        y_log.iloc[va],
                        params,
                    )
                    pred = np.expm1(model.predict(self.X_train.iloc[va]))
                    per_fold.append(metrics_reelles(y_val_real, pred))
                mean = {
                    k: float(np.mean([f[k] for f in per_fold])) for k in per_fold[0]
                }
                std = {k: float(np.std([f[k] for f in per_fold])) for k in per_fold[0]}
                results.append(
                    {"params": params, "mean": mean, "std": std, "per_fold": per_fold}
                )
                log.info("CV %s %s -> MedAPE=%.1f%%", target, params, mean["MedAPE_%"])
            self.cv_results[target] = results
        return self

    @timed("pre_tune")
    def pre_tune(self) -> TrainPipeline:
        """Dérive une grille restreinte depuis les résultats de CV."""
        if not self.cv_results:
            raise RuntimeError("Appelez cross_validate() avant pre_tune().")
        for target, results in self.cv_results.items():
            best = min(results, key=lambda r: r["mean"]["MedAPE_%"])
            p = best["params"]
            self.pre_tuned_grid[target] = {
                "iterations": [COARSE_GRID["iterations"][0]],
                "learning_rate": sorted({p["learning_rate"], p["learning_rate"] * 1.5}),
                "depth": sorted({max(3, p["depth"] - 1), p["depth"]}),
                "l2_leaf_reg": sorted({p["l2_leaf_reg"], p["l2_leaf_reg"] * 2}),
            }
            log.info("pre_tune %s : grille=%s", target, self.pre_tuned_grid[target])
        return self

    @timed("fine_tune")
    def fine_tune(self) -> TrainPipeline:
        """Recherche restreinte ; classe par MedAPE/R2 puis pénalise l'overkill."""
        self._require_split(require_features=True)
        if not self.pre_tuned_grid:
            raise RuntimeError("Appelez pre_tune() avant fine_tune().")
        for target in dp.TARGETS:
            y_log = np.log1p(self.Y_train[dp.TARGETS[target]["column"]])
            X_fit, X_val, y_fit, y_val = train_test_split(
                self.X_train, y_log, test_size=0.15, random_state=self.seed
            )
            candidates = []
            for params in self._yield_grid(self.pre_tuned_grid[target]):
                model = self._fit_early_stopping(X_fit, y_fit, X_val, y_val, params)
                m_fit = metrics_reelles(np.expm1(y_fit), np.expm1(model.predict(X_fit)))
                m_val = metrics_reelles(np.expm1(y_val), np.expm1(model.predict(X_val)))
                overfit_gap = m_val["R2"] - m_fit["R2"]
                candidates.append(
                    {
                        **params,
                        "n_trees": model.tree_count_,
                        "MedAPE_val": m_val["MedAPE_%"],
                        "R2_val": m_val["R2"],
                        "overfit_gap": overfit_gap,
                        # overkill : 1 si dépasse le budget d'arbres, sinon 0
                        "overkill": int(model.tree_count_ > MAX_TREES_BUDGET),
                    }
                )
                log.info(
                    "fine_tune %s %s -> MedAPE=%.1f%% trees=%d",
                    target,
                    params,
                    m_val["MedAPE_%"],
                    model.tree_count_,
                )
            # priorité : pas d'overkill, puis MedAPE, puis R2, puis gap
            candidates.sort(
                key=lambda c: (
                    c["overkill"],
                    c["MedAPE_val"],
                    -c["R2_val"],
                    -c["overfit_gap"],
                )
            )
            best = candidates[0]
            self.best_params[target] = {
                "iterations": best["iterations"],
                "learning_rate": best["learning_rate"],
                "depth": best["depth"],
                "l2_leaf_reg": best["l2_leaf_reg"],
                "overfit_gap": best["overfit_gap"],
                "n_trees": best["n_trees"],
            }
        return self

    @timed("train_final")
    def train_final(self) -> TrainPipeline:
        """Boucle sur les cibles : refit sur tout le train, sauvegarde un .cbm."""
        self._require_split(require_features=True)
        if not self.best_params:
            raise RuntimeError("Appelez fine_tune() avant train_final().")
        ensure_dir(self.output_dir)
        for target in dp.TARGETS:
            column = dp.TARGETS[target]["column"]
            y_log = np.log1p(self.Y_train[column])
            params = {
                k: self.best_params[target][k]
                for k in ("iterations", "learning_rate", "depth", "l2_leaf_reg")
            }
            X_fit, X_val, y_fit, y_val = train_test_split(
                self.X_train, y_log, test_size=0.1, random_state=self.seed
            )
            model = self._fit_early_stopping(X_fit, y_fit, X_val, y_val, params)
            out = self.output_dir / f"{target}.cbm"
            model.save_model(str(out))
            self.models[target] = model
            log.info("train_final %s -> %s", target, out)
        return self
