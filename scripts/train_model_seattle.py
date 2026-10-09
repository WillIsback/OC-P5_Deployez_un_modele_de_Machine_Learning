"""Training "ultime" — CatBoost pour la consommation d'énergie des bâtiments de Seattle.

Pipeline fidèle au notebook OC-Ai-Engineer-P3 (filtres F0 -> F11, ``df_clean``,
``FLAGS`` de raccordement gaz/vapeur, transform ``log1p``/``expm1``), enrichi avec :

* division train / validation (tuning) / test (hold-out intouché) ;
* protection contre l'over-fitting : early stopping, ``use_best_model``,
  mesure et pénalisation de l'écart train/validation ;
* fine-tune sur un **scope restreint** d'hyper-paramètres (grille courte 27) ;
* ré-entraînement final sur tout l'entraînement puis évaluation sur le test.

Usage
-----
    uv run python scripts/train_model_seattle.py [chemin_vers_le_CSV] \
        [--output models/energy_use_catboost.cbm]
"""

import argparse
import os
import sys
from itertools import product
from pathlib import Path

import mlflow
import numpy as np
import pandas as pd
from catboost import CatBoostRegressor
from sklearn.metrics import r2_score
from sklearn.model_selection import KFold, train_test_split

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.model_service import CAT_FEATURES, FEATURE_COLUMNS

TARGET = "SiteEnergyUse(kBtu)"  # consommation d'énergie (kBtu/an)

# ---------------------------------------------------------------------------
# 1. Pré-traitement : réplique des filtres F0 -> F11 du notebook P3
# ---------------------------------------------------------------------------
PII_COLUMNS = [
    "OSEBuildingID",
    "PropertyName",
    "Address",
    "TaxParcelIdentificationNumber",
    "ZipCode",
    "CouncilDistrictCode",
]
DATA_LEAKAGE_COLUMNS = [
    "GHGEmissionsIntensity",
    "SourceEUIWN(kBtu/sf)",
    "SiteEUI(kBtu/sf)",
    "SiteEUIWN(kBtu/sf)",
    "SourceEUI(kBtu/sf)",
    "SiteEnergyUseWN(kBtu)",
    "SteamUse(kBtu)",
    "Electricity(kWh)",
    "Electricity(kBtu)",
    "NaturalGas(therms)",
    "NaturalGas(kBtu)",
]


def build_clean(df: pd.DataFrame) -> pd.DataFrame:
    """Applique la chaîne de nettoyage du notebook (F0 -> F11)."""
    # F0 - périmètre : bâtiments NON destinés à l'habitation
    habitation = df["BuildingType"].str.startswith("Multifamily", na=False)
    out = df.loc[~habitation].copy()

    # F1 - colonnes sans variance
    out = out.loc[:, out.nunique() > 1]

    # outliers signalés (High / Low) -> suppression des lignes et de la colonne
    if "Outlier" in out.columns:
        out = out.drop(
            index=out[out["Outlier"].isin(["High outlier", "Low outlier"])].index
        )
        out = out.drop(columns=["Outlier"])

    # F5 - features = data leakage (EUI, émissions, énergies décomposées)
    out = out.drop(columns=DATA_LEAKAGE_COLUMNS, errors="ignore")
    # colonnes ENERGYSTAR = data leakage
    out = out.drop(
        columns=["YearsENERGYSTARCertified", "ENERGYSTARScore"], errors="ignore"
    )

    # F3 - PII / métadonnées d'identification
    out = out.drop(columns=PII_COLUMNS, errors="ignore")

    # F4 - ne garder que les bâtiments conformes
    if "ComplianceStatus" in out.columns:
        out = out[out["ComplianceStatus"].eq("Compliant")].drop(
            columns=["ComplianceStatus", "DefaultData"], errors="ignore"
        )

    # F6 - colinéarité forte
    out = out.drop(
        columns=["PropertyGFATotal", "LargestPropertyUseTypeGFA"], errors="ignore"
    )

    # F8 - normalisation Neighborhood (case) : supprime les doublons sémantiques
    if "Neighborhood" in out.columns:
        out["Neighborhood"] = out["Neighborhood"].str.upper().str.strip()

    # F9 - colonne non atomique
    out = out.drop(columns=["ListOfAllPropertyUseTypes"], errors="ignore")

    # F10 - cible strictement positive
    out = out[out[TARGET] > 0]

    # F11 - un bâtiment vaut au moins 1 (0 -> 1)
    if "NumberofBuildings" in out.columns:
        out.loc[out["NumberofBuildings"] == 0, "NumberofBuildings"] = 1

    # on ne garde que les lignes où la cible est renseignée
    out = out.dropna(subset=[TARGET])
    return out


# ---------------------------------------------------------------------------
# 2. Préparation CatBoost (catégorielles en str + flags de raccordement)
# ---------------------------------------------------------------------------
def build_flags(df_raw: pd.DataFrame, df_clean: pd.DataFrame) -> pd.DataFrame:
    """Approximation du raccordement gaz/vapeur : consommation déclarée > 0."""
    return pd.DataFrame(
        {
            "Has_NaturalGas": (
                df_raw.loc[df_clean.index, "NaturalGas(kBtu)"] > 0
            ).astype(int),
            "Has_Steam": (df_raw.loc[df_clean.index, "SteamUse(kBtu)"] > 0).astype(int),
        },
        index=df_clean.index,
    )


def prepare_catboost(X: pd.DataFrame, flags: pd.DataFrame) -> pd.DataFrame:
    """Catégorielles brutes en str + marqueurs de raccordement."""
    d = X.copy()
    for col in CAT_FEATURES:
        d[col] = d[col].astype(str)
    return d.join(flags)


# ---------------------------------------------------------------------------
# 3. Métriques en unités réelles (comparables entre cibles)
# ---------------------------------------------------------------------------
def metrics_reelles(y_true, y_pred) -> dict:
    err = np.abs(np.asarray(y_true) - np.asarray(y_pred))
    with np.errstate(divide="ignore"):
        medape = np.nanmedian(err / np.asarray(y_true, dtype=float)) * 100
    return {
        "R2": r2_score(y_true, y_pred),
        "MAE": float(np.mean(err)),
        "MedAE": float(np.median(err)),
        "MedAPE_%": float(medape),
    }


def report(metrics: dict, label: str) -> str:
    return (
        f"{label:<8} R2={metrics['R2']:.3f}  "
        f"MAE={metrics['MAE']:,.0f}  MedAE={metrics['MedAE']:,.0f}  "
        f"MedAPE={metrics['MedAPE_%']:.1f}%"
    )


# ---------------------------------------------------------------------------
# 4. Protection contre l'over-fitting + fine-tune à scope restreint
# ---------------------------------------------------------------------------
# Grille courte ("restricted scope") : 1 x 3 x 3 x 3 = 27 combinaisons.
# Chaque config est évaluée avec early stopping sur le pli de validation ;
# candidate classée par MedAPE valid, puis R2 valid, puis écart train/valid.
GRID = {
    "iterations": [2000],
    "learning_rate": [0.03, 0.05, 0.08],
    "depth": [4, 5, 6],
    "l2_leaf_reg": [3.0, 6.0, 10.0],
}


def train_with_early_stopping(X_fit, y_fit_log, X_val, y_val_log, params, cat_features):
    """CatBoost avec early stopping + use_best_model (anti over-fitting)."""
    model = CatBoostRegressor(
        random_seed=42,
        loss_function="RMSE",
        verbose=0,
        early_stopping_rounds=100,
        **params,
    )
    model.fit(
        X_fit,
        y_fit_log,
        cat_features=cat_features,
        eval_set=(X_val, y_val_log),
        use_best_model=True,
    )
    return model


def tune(X_train, y_train_log, cat_features, grid: dict | None = None):
    """Fine-tune sur scope restreint ; retourne (meilleur params, best)."""
    X_fit, X_val, y_fit, y_val = train_test_split(
        X_train, y_train_log, test_size=0.15, random_state=42
    )
    search_grid = grid if grid is not None else GRID
    candidates = []
    for params in _yield_grid(search_grid):
        model = train_with_early_stopping(
            X_fit, y_fit, X_val, y_val, params, cat_features
        )
        m_fit = metrics_reelles(np.expm1(y_fit), np.expm1(model.predict(X_fit)))
        m_val = metrics_reelles(np.expm1(y_val), np.expm1(model.predict(X_val)))
        overfit_gap = m_val["R2"] - m_fit["R2"]  # négatif -> validation dégradée
        candidates.append(
            {
                "params": params,
                "n_trees": model.tree_count_,
                "train": m_fit,
                "val": m_val,
                "overfit_gap": overfit_gap,
            }
        )
        print(
            f"[tune] {params}  trees={model.tree_count_:>4}  "
            f"{report(m_val, 'val')}  gapR2={overfit_gap:+.3f}"
        )

    # Tri : MedAPE valid croissant, puis R2 valid décroissant, puis gap décroissant.
    candidates.sort(
        key=lambda c: (c["val"]["MedAPE_%"], -c["val"]["R2"], -c["overfit_gap"])
    )
    best = candidates[0]
    print("\n=== MEILLEURE CONFIGURATION (scope restreint) ===")
    print(f"  {best['params']}  arbres={best['n_trees']}")
    print(f"  train {report(best['train'], 'train')}")
    print(f"  valid {report(best['val'], 'val')}")
    return best["params"], best


def _yield_grid(grid):
    keys = list(grid)
    for combo in product(*(grid[k] for k in keys)):
        yield dict(zip(keys, combo))


def cross_validate_energy(
    X: pd.DataFrame,
    y_log: pd.Series,
    params: dict,
    cat_features: list[str],
    n_splits: int = 5,
) -> dict:
    """Validation croisée sur le TRAIN : métriques en unités réelles.

    Chaque pli re-fitte le modèle avec early stopping (anti over-fitting) sur
    le pli de validation. Retourne ``{"mean": ..., "std": ..., "per_fold": [...]}``.
    """
    kf = KFold(n_splits=n_splits, shuffle=True, random_state=42)
    per_fold = []
    for tr_idx, va_idx in kf.split(X):
        X_fit, X_val = X.iloc[tr_idx], X.iloc[va_idx]
        y_fit, y_val = y_log.iloc[tr_idx], y_log.iloc[va_idx]
        model = train_with_early_stopping(
            X_fit, y_fit, X_val, y_val, params, cat_features
        )
        pred = np.expm1(model.predict(X_val))
        per_fold.append(metrics_reelles(np.expm1(y_val), pred))

    keys = list(per_fold[0])
    mean = {k: float(np.mean([f[k] for f in per_fold])) for k in keys}
    std = {k: float(np.std([f[k] for f in per_fold])) for k in keys}
    return {"mean": mean, "std": std, "per_fold": per_fold}


def _mlflow_key(name: str) -> str:
    """Noms de métriques MLflow : pas de '%', remplacé par 'pct'."""
    return name.replace("%", "pct")


def log_mlflow_metrics(prefix: str, metrics: dict):
    """Logue des métriques MLflow sous ``prefix_<nom>`` (noms nettoyés)."""
    for name, value in metrics.items():
        mlflow.log_metric(f"{prefix}_{_mlflow_key(name)}", float(value))


# ---------------------------------------------------------------------------
# 5. Ordonnancement global
# ---------------------------------------------------------------------------
def prepare_dataset(df_raw: pd.DataFrame):
    """build_clean + flags + prepare_catboost -> (X, y_log, df_clean).

    ``X`` a exactement les colonnes de ``FEATURE_COLUMNS`` (15 features + 2 flags),
    ``y_log`` est le ``log1p(SiteEnergyUse(kBtu))``.
    """
    df_clean = build_clean(df_raw)
    features_df_clean = [
        c for c in FEATURE_COLUMNS if c not in ("Has_NaturalGas", "Has_Steam")
    ]
    missing = [c for c in features_df_clean if c not in df_clean.columns]
    if missing:
        raise ValueError(f"Colonnes attendues absentes après nettoyage : {missing}")

    # On retire aussi l'autre cible (TotalGHGEmissions) si présente => pas de fuite.
    other_targets = ["TotalGHGEmissions"]
    X_features = df_clean.drop(
        columns=[c for c in [TARGET, *other_targets] if c in df_clean.columns],
        errors="ignore",
    )
    flags = build_flags(df_raw, df_clean)
    X = prepare_catboost(X_features, flags)[FEATURE_COLUMNS]
    y_log = np.log1p(df_clean[TARGET])
    return X, y_log, df_clean


def main() -> None:
    parser = argparse.ArgumentParser(description="Entraînement CatBoost Seattle (P3)")
    parser.add_argument(
        "csv",
        nargs="?",
        default="2016_Building_Energy_Benchmarking.csv",
        help="Chemin du dataset Seattle (2016_Building_Energy_Benchmarking.csv)",
    )
    parser.add_argument(
        "--output",
        default="models/energy_use_catboost.cbm",
        help="Fichier .cbm de sortie",
    )
    parser.add_argument(
        "--cv-splits",
        type=int,
        default=5,
        help="Nombre de plis de validation croisée sur le train",
    )
    args = parser.parse_args()

    csv_path = Path(args.csv)
    if not csv_path.exists():
        sys.exit(
            f"Dataset introuvable : {csv_path}\n"
            "Placez 2016_Building_Energy_Benchmarking.csv à la racine ou passez son chemin."
        )

    print(f"[data] chargement: {csv_path}")
    df_raw = pd.read_csv(csv_path)
    X, y_log, df_clean = prepare_dataset(df_raw)
    print(f"[clean] -> {df_clean.shape} | modèle-input X={X.shape[1]} cols, n={len(X)}")

    # Hold-out test intouché
    X_train, X_test, y_train_log, y_test_log = train_test_split(
        X, y_log, test_size=0.2, random_state=42
    )

    # --- MLflow : tracking, expériment, run unique ---
    mlflow.set_tracking_uri(os.getenv("MLFLOW_TRACKING_URI", "sqlite:///mlflow.db"))
    mlflow.set_experiment(os.getenv("MLFLOW_EXPERIMENT", "seattle-energy"))

    with mlflow.start_run(run_name="catboost-energy-seattle"):
        # Fine-tune (grille restreinte) + log des hyper-params
        best_params, _ = tune(X_train, y_train_log, CAT_FEATURES)
        mlflow.log_params(best_params)
        mlflow.log_params(
            {
                "target": TARGET,
                "target_transform": "log1p",
                "n_features": len(FEATURE_COLUMNS),
                "cat_features": ",".join(CAT_FEATURES),
                "train_rows": len(X_train),
                "test_rows": len(X_test),
                "cv_splits": args.cv_splits,
            }
        )

        # --- Scores CV sur le TRAIN (moyenne, écart-type, par pli) ---
        print(f"\n[CV] validation croisée sur le train ({args.cv_splits} splits)...")
        cv = cross_validate_energy(
            X_train, y_train_log, best_params, CAT_FEATURES, n_splits=args.cv_splits
        )
        for fold_idx, fold_metrics in enumerate(cv["per_fold"], start=1):
            mlflow.log_metrics(
                {
                    f"cv_fold{fold_idx}_{_mlflow_key(name)}": v
                    for name, v in fold_metrics.items()
                }
            )
        log_mlflow_metrics("cv_train", cv["mean"])
        log_mlflow_metrics("cv_train_std", cv["std"])
        print("CV(train) mean:", report(cv["mean"], "cv"))
        print("CV(train) std :", report(cv["std"], "std"))

        # --- Évaluation finale sur le TEST ---
        print(
            "\n[final-fit] ré-entraînement sur tout l'entraînement (early stopping)..."
        )
        final_model = train_with_early_stopping(
            X_train, y_train_log, X_test, y_test_log, best_params, CAT_FEATURES
        )
        m_test = metrics_reelles(
            np.expm1(y_test_log), np.expm1(final_model.predict(X_test))
        )
        print("\n=== ÉVALUATION FINALE SUR LE TEST (unité kBtu/an) ===")
        print(report(m_test, "test"))
        log_mlflow_metrics("test", m_test)
        mlflow.log_param("final_n_trees", final_model.tree_count_)

        # --- Sauvegarde du modèle + log artefact ---
        out = Path(args.output)
        out.parent.mkdir(parents=True, exist_ok=True)
        final_model.save_model(str(out))
        mlflow.log_artifact(str(out), artifact_path="models")
        print(f"\n[model] sauvegardé : {out} | MLflow run terminé.")


if __name__ == "__main__":
    main()
