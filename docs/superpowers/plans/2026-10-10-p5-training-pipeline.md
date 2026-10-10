# Pipeline d'entraînement multi-cible + serving optimisé — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Unifier l'entraînement CatBoost/Kumo sur les deux cibles (consommation + émissions), intégrer MLflow pour les deux modèles, étendre l'API et optimiser le chargement des modèles.

**Architecture:** Un package `app/training/` expose `TrainPipeline` (étapes découplées : split → feature engineering → CV → pré-réglage → fine-tuning → train final → évaluation). `app/lib/tools.py` regroupe logging/wrappers/helpers. Les services `app/core/*` deviennent multi-cible ; Kumo est chargé une seule fois et partagé. `scripts/` est supprimé.

**Tech Stack:** Python 3.12+, FastAPI, CatBoost, scikit-learn, MLflow, NVIDIA `structured-data-models` (Kumo-Tabular), pytest, ruff, uv.

**Spec:** `docs/superpowers/specs/2026-10-10-p5-training-pipeline-design.md` (issue #9)

---

## File Structure

**Créer**
- `app/lib/__init__.py` — package vide
- `app/lib/tools.py` — logging, wrappers, helpers
- `app/training/__init__.py` — export `TrainPipeline`
- `app/training/data_processing.py` — nettoyage F0→F11, flags, prépa CatBoost, dataset
- `app/training/pipeline.py` — classe `TrainPipeline`
- `app/training/__main__.py` — CLI `python -m app.training`
- `tests/test_tools.py` — tests de `app.lib.tools`

**Modifier**
- `app/schemas/api.py` — constantes `FEATURE_COLUMNS`, `TARGETS` + schémas étendus
- `app/core/model_service.py` — CatBoost multi-cible (lazy par cible)
- `app/core/kumo_service.py` — Kumo partagé, contexte par cible, prédiction par lots
- `app/core/metrics_service.py` — table de scores regroupée par cible
- `app/routers/model.py` — routes étendues
- `tests/test_training.py` — migré vers `app.training`
- `tests/test_kumo.py` — étendu aux 2 cibles
- `tests/test_jwt.py` — bug corrigé + nouvelles réponses
- `.gitignore` — ajouter `data/`
- `README.md` — commande d'entraînement

**Supprimer**
- `scripts/train_model.py`, `scripts/train_model_seattle.py`, `scripts/__pycache__/`

**Convention de commit:** Conventional Commits, chaque commit référence `#9`.

---

## Task 1: `app/lib/tools.py`

**Files:**
- Create: `app/lib/__init__.py`
- Create: `app/lib/tools.py`
- Test: `tests/test_tools.py`

- [ ] **Step 1: Write the failing test**

```python
"""Tests unitaires de app.lib.tools."""

import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.lib import tools


def test_get_logger_is_stable_and_has_no_duplicate_handlers():
    log1 = tools.get_logger("demo")
    log2 = tools.get_logger("demo")
    assert log1 is log2
    assert logging.getLogger("demo").handlers == [] or len(
        logging.getLogger("demo").handlers
    ) <= 1


def test_sanitize_metric_key_replaces_percent():
    assert tools.sanitize_metric_key("MedAPE_%") == "MedAPE_pct"


def test_ensure_dir_and_json_roundtrip(tmp_path):
    d = tools.ensure_dir(tmp_path / "a" / "b")
    assert d.is_dir()
    p = d / "x.json"
    tools.save_json(p, {"a": 1, "b": "é"})
    assert tools.load_json(p) == {"a": 1, "b": "é"}
    assert json.loads(p.read_text(encoding="utf-8"))["a"] == 1


def test_metrics_reelles_values():
    y_true = [100.0, 200.0, 300.0]
    y_pred = [110.0, 180.0, 330.0]
    m = tools.metrics_reelles(y_true, y_pred)
    assert set(m) == {"R2", "MAE", "MedAE", "MedAPE_%"}
    assert m["MAE"] == 20.0
    assert m["MedAE"] == 20.0
    assert m["MedAPE_%"] > 0


def test_timed_and_log_calls_decorators_return_value():
    @tools.timed("add")
    @tools.log_calls
    def add(a, b):
        return a + b

    assert add(2, 3) == 5
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_tools.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.lib'`

- [ ] **Step 3: Create the package and write the implementation**

`app/lib/__init__.py`:

```python
"""Utilitaires transverses du projet."""
```

`app/lib/tools.py`:

```python
"""Logging, wrappers (décorateurs) et helpers transverses."""

from __future__ import annotations

import functools
import json
import logging
import os
import random
import time
from pathlib import Path
from typing import Any, Callable, TypeVar

import numpy as np
from sklearn.metrics import r2_score

_LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s %(message)s"
_configured = False

F = TypeVar("F", bound=Callable[..., Any])


def setup_logging(level: str = "INFO") -> None:
    """Configure le logging racine une seule fois."""
    global _configured
    if _configured:
        return
    logging.basicConfig(level=level, format=_LOG_FORMAT)
    _configured = True


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
                log.info("%s took %.2fs", label or fn.__qualname__,
                         time.perf_counter() - start)

        return wrapper  # type: ignore[return-value]

    return deco


def log_calls(fn: F) -> F:
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
    """Écrit ``obj`` en JSON UTF-8 indenté."""
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2, ensure_ascii=False)


def load_json(path: str | os.PathLike[str]) -> Any:
    """Lit un fichier JSON UTF-8."""
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def set_seed(seed: int = 42) -> None:
    """Fixe les graines ``random`` et ``numpy``."""
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_tools.py -q`
Expected: PASS (5 passed)

- [ ] **Step 5: Lint and commit**

```bash
uv run ruff check app/lib/tools.py tests/test_tools.py
uv run ruff format app/lib/tools.py tests/test_tools.py
git add app/lib/__init__.py app/lib/tools.py tests/test_tools.py
git commit -m "feat: outils transverses logging/wrapper/helper (app/lib/tools.py)

Related to #9"
```

---

## Task 2: Constantes partagées dans `app/schemas/api.py`

**Files:**
- Modify: `app/schemas/api.py`

- [ ] **Step 1: Add the shared contract constants**

Ajouter au début de `app/schemas/api.py` (après les imports, avant `Model`) :

```python
CAT_FEATURES = [
    "BuildingType",
    "PrimaryPropertyType",
    "Neighborhood",
    "LargestPropertyUseType",
    "SecondLargestPropertyUseType",
    "ThirdLargestPropertyUseType",
]

FEATURE_COLUMNS = [
    "BuildingType",
    "PrimaryPropertyType",
    "Neighborhood",
    "Latitude",
    "Longitude",
    "YearBuilt",
    "NumberofBuildings",
    "NumberofFloors",
    "PropertyGFAParking",
    "PropertyGFABuilding(s)",
    "LargestPropertyUseType",
    "SecondLargestPropertyUseType",
    "SecondLargestPropertyUseTypeGFA",
    "ThirdLargestPropertyUseType",
    "ThirdLargestPropertyUseTypeGFA",
    "Has_NaturalGas",
    "Has_Steam",
]

TARGETS = {
    "energy": {"column": "SiteEnergyUse(kBtu)", "unit": "kBtu/an"},
    "emissions": {"column": "TotalGHGEmissions", "unit": "t CO2e/an"},
}
```

Supprimer l'ancienne définition dupliquée de `CAT_FEATURES` (elle est désormais unique en tête de fichier).

- [ ] **Step 2: Verify imports still resolve**

Run: `uv run python -c "from app.schemas.api import CAT_FEATURES, FEATURE_COLUMNS, TARGETS; print(len(FEATURE_COLUMNS), list(TARGETS))"`
Expected: `17 ['energy', 'emissions']`

- [ ] **Step 3: Commit**

```bash
git add app/schemas/api.py
git commit -m "refactor: constantes de contrat partagées dans app/schemas/api.py

Related to #9"
```

---

## Task 3: `app/training/data_processing.py`

**Files:**
- Create: `app/training/__init__.py`
- Create: `app/training/data_processing.py`
- Test: `tests/test_training.py` (nouveau contenu, partie data)

- [ ] **Step 1: Write the failing test**

Remplacer le contenu de `tests/test_training.py` par :

```python
"""Tests du pipeline d'entraînement multi-cible (app.training)."""

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.training import data_processing as dp


def make_synth(n: int = 80, seed: int = 0) -> pd.DataFrame:
    """DataFrame brut synthétique au format du benchmark Seattle."""
    rng = np.random.default_rng(seed)
    n_multi = n // 8
    n_other = n - n_multi
    building_type = ["Multifamily LR (1-4)"] * n_multi + [
        "NonResidential"
    ] * n_other
    return pd.DataFrame(
        {
            "BuildingType": building_type,
            "PrimaryPropertyType": rng.choice(
                ["Office", "Retail Store", "Warehouse"], n
            ),
            "Neighborhood": rng.choice(["BALLARD", "Downtown", "Fremont"], n),
            "Latitude": rng.uniform(47.5, 47.7, n),
            "Longitude": rng.uniform(-122.4, -122.25, n),
            "YearBuilt": rng.integers(1930, 2020, n),
            "NumberofBuildings": rng.integers(0, 3, n).astype(float),
            "NumberofFloors": rng.integers(1, 8, n),
            "PropertyGFAParking": rng.integers(0, 20000, n),
            "PropertyGFABuilding(s)": rng.integers(500, 40000, n),
            "LargestPropertyUseType": rng.choice(["Office", "Retail"], n),
            "SecondLargestPropertyUseType": rng.choice(["Retail", "Service"], n),
            "SecondLargestPropertyUseTypeGFA": rng.uniform(0, 12000, n),
            "ThirdLargestPropertyUseType": rng.choice(["Parking", "Service"], n),
            "ThirdLargestPropertyUseTypeGFA": rng.uniform(0, 8000, n),
            "SiteEnergyUse(kBtu)": rng.uniform(1000, 500000, n),
            "TotalGHGEmissions": rng.uniform(1, 500, n),
            "NaturalGas(kBtu)": rng.uniform(0, 1000, n),
            "SteamUse(kBtu)": rng.uniform(0, 1000, n),
            "PropertyGFATotal": rng.integers(500, 40000, n),
            "LargestPropertyUseTypeGFA": rng.integers(0, 40000, n),
            "OSEBuildingID": np.arange(n),
            "PropertyName": [f"b{i}" for i in range(n)],
            "Address": [f"{i} st" for i in range(n)],
            "TaxParcelIdentificationNumber": [f"t{i}" for i in range(n)],
            "ZipCode": ["98101"] * n,
            "CouncilDistrictCode": [1] * n,
            "ListOfAllPropertyUseTypes": ["Office"] * n,
            "ComplianceStatus": ["Compliant"] * n,
            "DefaultData": [False] * n,
            "Outlier": ["None"] * n,
            "YearsENERGYSTARCertified": [np.nan] * n,
            "ENERGYSTARScore": rng.uniform(0, 100, n),
            "GHGEmissionsIntensity": rng.uniform(0, 10, n),
        }
    )


def test_build_clean_drops_multifamily_and_leakage():
    clean = dp.build_clean(make_synth())
    assert not clean["BuildingType"].str.startswith("Multifamily").any()
    assert "GHGEmissionsIntensity" not in clean.columns
    assert "SiteEnergyUse(kBtu)" in clean.columns
    assert "TotalGHGEmissions" in clean.columns


def test_build_clean_keeps_positive_targets_only():
    df = make_synth()
    df.loc[0, "SiteEnergyUse(kBtu)"] = 0
    df.loc[1, "TotalGHGEmissions"] = 0
    clean = dp.build_clean(df)
    assert (clean["SiteEnergyUse(kBtu)"] > 0).all()
    assert (clean["TotalGHGEmissions"] > 0).all()


def test_prepare_dataset_shapes_and_targets():
    X, Y, df_clean = dp.prepare_dataset(make_synth(120))
    assert list(X.columns) == dp.FEATURE_COLUMNS
    assert set(Y.columns) == {"SiteEnergyUse(kBtu)", "TotalGHGEmissions"}
    assert len(X) == len(Y) == len(df_clean)
    for col in dp.CAT_FEATURES:
        assert X[col].dtype == object


def test_build_flags_from_raw_columns():
    df = make_synth(40)
    df["NaturalGas(kBtu)"] = 0.0
    df["SteamUse(kBtu)"] = 0.0
    df.loc[df.index[0], "NaturalGas(kBtu)"] = 500.0
    clean = dp.build_clean(df)
    flags = dp.build_flags(df, clean)
    assert set(flags.columns) == {"Has_NaturalGas", "Has_Steam"}
    assert flags["Has_NaturalGas"].sum() >= 1
    assert flags["Has_Steam"].sum() == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_training.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.training'`

- [ ] **Step 3: Write the implementation**

`app/training/__init__.py`:

```python
"""Package d'entraînement P5 (pipeline multi-cible)."""

from app.training.pipeline import TrainPipeline

__all__ = ["TrainPipeline"]
```

> Note : `pipeline.py` n'existe pas encore ; le test de cette tâche importe
> `app.training.data_processing` directement. Créer un `pipeline.py` vide
> (placeholder) n'est pas nécessaire — `__init__` importera `TrainPipeline`
> seulement à partir de la Task 4. Pour que l'import de package fonctionne ici,
> écrire provisoirement `app/training/__init__.py` **sans** l'import :

```python
"""Package d'entraînement P5 (pipeline multi-cible)."""
```

`app/training/data_processing.py`:

```python
"""Nettoyage (F0->F11), flags gaz/vapeur et préparation CatBoost multi-cible."""

from __future__ import annotations

import shutil
import urllib.request
from pathlib import Path

import pandas as pd

from app.schemas.api import CAT_FEATURES, FEATURE_COLUMNS, TARGETS

DATASET_URL = (
    "https://s3.eu-west-1.amazonaws.com/course.oc-static.com/projects/"
    "Data_Scientist_P4/2016_Building_Energy_Benchmarking.csv"
)
DEFAULT_DATASET_PATH = Path("data/2016_Building_Energy_Benchmarking.csv")

TARGET_COLUMNS = [t["column"] for t in TARGETS.values()]

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
    habitation = df["BuildingType"].str.startswith("Multifamily", na=False)
    out = df.loc[~habitation].copy()

    out = out.loc[:, out.nunique() > 1]

    if "Outlier" in out.columns:
        out = out.drop(
            index=out[out["Outlier"].isin(["High outlier", "Low outlier"])].index
        )
        out = out.drop(columns=["Outlier"])

    out = out.drop(columns=DATA_LEAKAGE_COLUMNS, errors="ignore")
    out = out.drop(
        columns=["YearsENERGYSTARCertified", "ENERGYSTARScore"], errors="ignore"
    )
    out = out.drop(columns=PII_COLUMNS, errors="ignore")

    if "ComplianceStatus" in out.columns:
        out = out[out["ComplianceStatus"].eq("Compliant")].drop(
            columns=["ComplianceStatus", "DefaultData"], errors="ignore"
        )

    out = out.drop(
        columns=["PropertyGFATotal", "LargestPropertyUseTypeGFA"], errors="ignore"
    )

    if "Neighborhood" in out.columns:
        out["Neighborhood"] = out["Neighborhood"].str.upper().str.strip()

    out = out.drop(columns=["ListOfAllPropertyUseTypes"], errors="ignore")

    # F10 - les deux cibles strictement positives
    for target in TARGET_COLUMNS:
        out = out[out[target] > 0]

    if "NumberofBuildings" in out.columns:
        out.loc[out["NumberofBuildings"] == 0, "NumberofBuildings"] = 1

    out = out.dropna(subset=TARGET_COLUMNS)
    return out


def build_flags(df_raw: pd.DataFrame, df_clean: pd.DataFrame) -> pd.DataFrame:
    """Raccordement gaz/vapeur : consommation déclarée > 0."""
    return pd.DataFrame(
        {
            "Has_NaturalGas": (
                df_raw.loc[df_clean.index, "NaturalGas(kBtu)"] > 0
            ).astype(int),
            "Has_Steam": (
                df_raw.loc[df_clean.index, "SteamUse(kBtu)"] > 0
            ).astype(int),
        },
        index=df_clean.index,
    )


def prepare_catboost(X: pd.DataFrame, flags: pd.DataFrame) -> pd.DataFrame:
    """Catégorielles brutes en str + marqueurs de raccordement."""
    d = X.copy()
    for col in CAT_FEATURES:
        d[col] = d[col].astype(str)
    return d.join(flags)[FEATURE_COLUMNS]


def prepare_dataset(df_raw: pd.DataFrame):
    """build_clean + flags + prepare_catboost -> (X, Y, df_clean)."""
    df_clean = build_clean(df_raw)
    features = [c for c in FEATURE_COLUMNS if c not in ("Has_NaturalGas", "Has_Steam")]
    missing = [c for c in features if c not in df_clean.columns]
    if missing:
        raise ValueError(f"Colonnes attendues absentes après nettoyage : {missing}")

    X_features = df_clean.drop(columns=TARGET_COLUMNS, errors="ignore")
    flags = build_flags(df_raw, df_clean)
    X = prepare_catboost(X_features, flags)
    Y = df_clean[TARGET_COLUMNS]
    return X, Y, df_clean


def ensure_dataset(
    path: str | Path = DEFAULT_DATASET_PATH,
    url: str = DATASET_URL,
    download: bool = False,
) -> Path:
    """Retourne le chemin du CSV ; le télécharge (idempotent) si demandé."""
    path = Path(path)
    if path.exists():
        return path
    if not download:
        raise FileNotFoundError(
            f"Dataset introuvable : {path}. Relancez avec --download."
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    urllib.request.urlretrieve(url, tmp)  # noqa: S310 (URL constante du projet)
    shutil.move(str(tmp), str(path))
    return path
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_training.py -q`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
uv run ruff check app/training tests/test_training.py
uv run ruff format app/training tests/test_training.py
git add app/training/__init__.py app/training/data_processing.py tests/test_training.py
git commit -m "feat: data_processing multi-cible + téléchargement dataset idempotent

Related to #9"
```

---

## Task 4: `TrainPipeline` — squelette, split, feature engineering

**Files:**
- Create: `app/training/pipeline.py`
- Modify: `app/training/__init__.py`
- Test: `tests/test_training.py` (ajout)

- [ ] **Step 1: Write the failing test**

Ajouter à la fin de `tests/test_training.py` :

```python
from app.training.pipeline import TrainPipeline


def test_pipeline_split_then_feature_engineering():
    pipe = TrainPipeline(df_raw=make_synth(200), seed=42, test_size=0.25)
    pipe.split()
    pipe.feature_engineering()
    assert len(pipe.idx_train) + len(pipe.idx_test) == 200
    assert len(pipe.X_train) == len(pipe.Y_train) == len(pipe.idx_train)
    assert list(pipe.X_train.columns) == dp.FEATURE_COLUMNS
    assert set(pipe.Y_train.columns) == {"SiteEnergyUse(kBtu)", "TotalGHGEmissions"}
    # pas de fuite : le test n'a pas été vu à l'ajustement
    assert set(pipe.idx_train).isdisjoint(set(pipe.idx_test))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_training.py::test_pipeline_split_then_feature_engineering -q`
Expected: FAIL — `ImportError: cannot import name 'TrainPipeline'`

- [ ] **Step 3: Write the implementation**

`app/training/pipeline.py` :

```python
"""Pipeline d'entraînement multi-cible (CatBoost + évaluation Kumo)."""

from __future__ import annotations

import os
from pathlib import Path

import mlflow
import numpy as np
import pandas as pd
from catboost import CatBoostRegressor
from sklearn.model_selection import KFold, train_test_split

from app.lib.tools import (
    ensure_dir,
    get_logger,
    log_mlflow_metrics,
    metrics_reelles,
    save_json,
    sanitize_metric_key,
    timed,
)
from app.schemas.api import CAT_FEATURES, FEATURE_COLUMNS, TARGETS
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
        self.df_raw = df_raw if df_raw is not None else pd.read_csv(csv_path)
        self.output_dir = Path(output_dir)
        self.test_size = test_size
        self.seed = seed
        self.cv_splits = cv_splits
        self.mlflow_tracking_uri = mlflow_tracking_uri
        self.mlflow_experiment = mlflow_experiment
        # état rempli par les étapes
        self.df_clean: pd.DataFrame | None = None
        self.idx_train = self.idx_test = None
        self.X_train = self.X_test = None
        self.Y_train = self.Y_test = None
        self.cv_results: dict[str, list] = {}
        self.pre_tuned_grid: dict[str, dict] = {}
        self.best_params: dict[str, dict] = {}
        self.models: dict[str, CatBoostRegressor] = {}
        self.metrics: dict = {}

    @timed("split")
    def split(self) -> "TrainPipeline":
        """Nettoyage puis découpe train/test (les indices bruts sont conservés)."""
        self.df_clean = dp.build_clean(self.df_raw)
        idx = self.df_clean.index
        self.idx_train, self.idx_test = train_test_split(
            idx, test_size=self.test_size, random_state=self.seed
        )
        log.info("split : %d train / %d test", len(self.idx_train), len(self.idx_test))
        return self

    @timed("feature_engineering")
    def feature_engineering(self) -> "TrainPipeline":
        """Catégorielles->str + flags, ajusté sur train et appliqué au test."""
        features = [
            c for c in FEATURE_COLUMNS if c not in ("Has_NaturalGas", "Has_Steam")
        ]
        for name, idx in (("train", self.idx_train), ("test", self.idx_test)):
            X = self.df_clean.loc[idx, features]
            flags = dp.build_flags(self.df_raw, self.df_clean.loc[idx])
            setattr(self, f"X_{name}", dp.prepare_catboost(X, flags))
            setattr(self, f"Y_{name}", self.df_clean.loc[idx, dp.TARGET_COLUMNS])
        return self
```

Mettre à jour `app/training/__init__.py` :

```python
"""Package d'entraînement P5 (pipeline multi-cible)."""

from app.training.pipeline import TrainPipeline

__all__ = ["TrainPipeline"]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_training.py -q`
Expected: PASS (5 passed)

- [ ] **Step 5: Commit**

```bash
uv run ruff check app/training tests/test_training.py
uv run ruff format app/training tests/test_training.py
git add app/training/__init__.py app/training/pipeline.py tests/test_training.py
git commit -m "feat: TrainPipeline split + feature engineering (sans fuite)

Related to #9"
```

---

## Task 5: `cross_validate` + `pre_tune`

**Files:**
- Modify: `app/training/pipeline.py`
- Test: `tests/test_training.py` (ajout)

- [ ] **Step 1: Write the failing test**

```python
def test_pipeline_cross_validate_and_pre_tune_restrict_grid():
    pipe = TrainPipeline(df_raw=make_synth(160), seed=42, cv_splits=3)
    pipe.split().feature_engineering().cross_validate().pre_tune()
    for target in dp.TARGETS:
        assert target in pipe.cv_results
        assert pipe.cv_results[target]  # au moins une config évaluée
        grid = pipe.pre_tuned_grid[target]
        # grille restreinte : pas plus de 2 valeurs par axe
        assert all(len(v) <= 2 for v in grid.values())
        assert grid["iterations"][0] <= dp.MAX_TREES_BUDGET
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_training.py::test_pipeline_cross_validate_and_pre_tune_restrict_grid -q`
Expected: FAIL — `AttributeError: 'TrainPipeline' object has no attribute 'cross_validate'`

- [ ] **Step 3: Write the implementation**

Ajouter à `TrainPipeline` :

```python
    def _fit_early_stopping(self, X_fit, y_fit_log, X_val, y_val_log, params):
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

    def _yield_grid(self, grid: dict):
        from itertools import product

        keys = list(grid)
        for combo in product(*(grid[k] for k in keys)):
            yield dict(zip(keys, combo))

    @timed("cross_validate")
    def cross_validate(self) -> "TrainPipeline":
        """CV sur le train, pour chaque cible et chaque config de COARSE_GRID."""
        kf = KFold(n_splits=self.cv_splits, shuffle=True, random_state=self.seed)
        for target in TARGETS:
            y_log = np.log1p(self.Y_train[TARGETS[target]["column"]])
            results = []
            for params in self._yield_grid(COARSE_GRID):
                per_fold = []
                for tr, va in kf.split(self.X_train):
                    model = self._fit_early_stopping(
                        self.X_train.iloc[tr], y_log.iloc[tr],
                        self.X_train.iloc[va], y_log.iloc[va], params,
                    )
                    pred = np.expm1(model.predict(self.X_train.iloc[va]))
                    per_fold.append(
                        metrics_reelles(
                            np.expm1(y_log.iloc[va]), pred
                        )
                    )
                mean = {
                    k: float(np.mean([f[k] for f in per_fold]))
                    for k in per_fold[0]
                }
                std = {
                    k: float(np.std([f[k] for f in per_fold]))
                    for k in per_fold[0]
                }
                results.append(
                    {"params": params, "mean": mean, "std": std, "per_fold": per_fold}
                )
                log.info("CV %s %s -> MedAPE=%.1f%%", target, params,
                         mean["MedAPE_%"])
            self.cv_results[target] = results
        return self

    @timed("pre_tune")
    def pre_tune(self) -> "TrainPipeline":
        """Dérive une grille restreinte depuis les résultats de CV."""
        for target, results in self.cv_results.items():
            best = min(results, key=lambda r: r["mean"]["MedAPE_%"])
            p = best["params"]
            self.pre_tuned_grid[target] = {
                "iterations": [min(COARSE_GRID["iterations"][0], MAX_TREES_BUDGET)],
                "learning_rate": sorted({p["learning_rate"], p["learning_rate"] * 1.5}),
                "depth": sorted({max(3, p["depth"] - 1), p["depth"]}),
                "l2_leaf_reg": sorted({p["l2_leaf_reg"], p["l2_leaf_reg"] * 2}),
            }
            log.info("pre_tune %s : grille=%s", target, self.pre_tuned_grid[target])
        return self
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_training.py::test_pipeline_cross_validate_and_pre_tune_restrict_grid -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/training/pipeline.py tests/test_training.py
git commit -m "feat: cross-validation et pré-réglage de la grille restreinte

Related to #9"
```

---

## Task 6: `fine_tune` + `train_final`

**Files:**
- Modify: `app/training/pipeline.py`
- Test: `tests/test_training.py` (ajout)

- [ ] **Step 1: Write the failing test**

```python
def test_pipeline_fine_tune_penalizes_overkill_and_trains_final(tmp_path):
    pipe = TrainPipeline(
        df_raw=make_synth(160), seed=42, cv_splits=3, output_dir=tmp_path
    )
    pipe.split().feature_engineering().cross_validate().pre_tune()
    pipe.fine_tune().train_final()
    for target in dp.TARGETS:
        assert "depth" in pipe.best_params[target]
        assert "overfit_gap" in pipe.best_params[target]
        cbm = tmp_path / f"{target}.cbm"
        assert cbm.exists()
        assert pipe.models[target] is not None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_training.py::test_pipeline_fine_tune_penalizes_overkill_and_trains_final -q`
Expected: FAIL — `AttributeError: ... 'fine_tune'`

- [ ] **Step 3: Write the implementation**

Ajouter à `TrainPipeline` :

```python
    @timed("fine_tune")
    def fine_tune(self) -> "TrainPipeline":
        """Recherche restreinte ; classe par MedAPE/R2 puis pénalise l'overkill."""
        for target in TARGETS:
            y_log = np.log1p(self.Y_train[TARGETS[target]["column"]])
            X_fit, X_val, y_fit, y_val = train_test_split(
                self.X_train, y_log, test_size=0.15, random_state=self.seed
            )
            candidates = []
            for params in self._yield_grid(self.pre_tuned_grid[target]):
                model = self._fit_early_stopping(
                    X_fit, y_fit, X_val, y_val, params
                )
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
                log.info("fine_tune %s %s -> MedAPE=%.1f%% trees=%d",
                         target, params, m_val["MedAPE_%"], model.tree_count_)
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
    def train_final(self) -> "TrainPipeline":
        """Boucle sur les cibles : refit sur tout le train, sauvegarde un .cbm."""
        ensure_dir(self.output_dir)
        for target in TARGETS:
            column = TARGETS[target]["column"]
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_training.py::test_pipeline_fine_tune_penalizes_overkill_and_trains_final -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/training/pipeline.py tests/test_training.py
git commit -m "feat: fine-tuning avec pénalité overfit/overkill + train final par cible

Related to #9"
```

---

## Task 7: `evaluate` + MLflow + `run`

**Files:**
- Modify: `app/training/pipeline.py`
- Test: `tests/test_training.py` (ajout)

- [ ] **Step 1: Write the failing test**

```python
def test_pipeline_evaluate_builds_grouped_scores(tmp_path):
    pipe = TrainPipeline(
        df_raw=make_synth(160), seed=42, cv_splits=3, output_dir=tmp_path
    )
    pipe.split().feature_engineering().cross_validate().pre_tune()
    pipe.fine_tune().train_final()
    # Kumo remplacé par un prédicteur factice (pas de chargement lourd en test)
    pipe.evaluate(kumo_predictor=lambda X, target: np.full(len(X), 42.0))
    assert set(pipe.metrics) == set(dp.TARGETS)
    for target, block in pipe.metrics.items():
        assert block["unit"] == dp.TARGETS[target]["unit"]
        assert set(block["models"]) == {"catboost", "kumo"}
        assert set(block["models"]["catboost"]) == {"R2", "MAE", "MedAE", "MedAPE_pct"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_training.py::test_pipeline_evaluate_builds_grouped_scores -q`
Expected: FAIL — `AttributeError: ... 'evaluate'`

- [ ] **Step 3: Write the implementation**

Ajouter à `TrainPipeline` :

```python
    @timed("evaluate")
    def evaluate(self, kumo_predictor=None) -> "TrainPipeline":
        """Métriques test par cible (CatBoost + Kumo) -> table regroupée."""
        for target in TARGETS:
            column = TARGETS[target]["column"]
            y_true = self.Y_test[column].to_numpy()
            y_pred = np.expm1(self.models[target].predict(self.X_test))
            cb = metrics_reelles(y_true, y_pred)
            block = {
                "unit": TARGETS[target]["unit"],
                "models": {
                    "catboost": {
                        sanitize_metric_key(k): v for k, v in cb.items()
                    }
                },
            }
            if kumo_predictor is not None:
                kumo_pred = np.asarray(
                    kumo_predictor(self.X_test, target), dtype=float
                )
                km = metrics_reelles(y_true, kumo_pred)
                block["models"]["kumo"] = {
                    sanitize_metric_key(k): v for k, v in km.items()
                }
            self.metrics[target] = block
        return self

    @timed("run")
    def run(self, include_kumo: bool = True) -> dict:
        """Orchestre toutes les étapes et logue dans MLflow."""
        mlflow.set_tracking_uri(
            self.mlflow_tracking_uri
            or os.getenv("MLFLOW_TRACKING_URI", "sqlite:///mlflow.db")
        )
        mlflow.set_experiment(
            self.mlflow_experiment or os.getenv("MLFLOW_EXPERIMENT", "seattle-energy")
        )

        self.split().feature_engineering().cross_validate().pre_tune()
        self.fine_tune().train_final()

        kumo_predictor = None
        if include_kumo:
            from app.core import kumo_service

            def kumo_predictor(X, target):  # noqa: E731
                return kumo_service.predict_batch(X, target)

        self.evaluate(kumo_predictor=kumo_predictor)

        with mlflow.start_run(run_name="p5-multitarget"):
            mlflow.log_params(
                {
                    "test_size": self.test_size,
                    "seed": self.seed,
                    "cv_splits": self.cv_splits,
                }
            )
            for target in TARGETS:
                with mlflow.start_run(run_name=f"catboost-{target}", nested=True):
                    mlflow.log_params(self.best_params[target])
                    log_mlflow_metrics(
                        "test", self.metrics[target]["models"]["catboost"]
                    )
                    mlflow.log_artifact(
                        str(self.output_dir / f"{target}.cbm"), artifact_path="models"
                    )
            if include_kumo:
                for target in TARGETS:
                    with mlflow.start_run(run_name=f"kumo-{target}", nested=True):
                        mlflow.log_param("mode", "zero-shot")
                        log_mlflow_metrics(
                            "test", self.metrics[target]["models"]["kumo"]
                        )

            scores_path = self.output_dir / "scores.json"
            save_json(scores_path, {"targets": self.metrics})
            mlflow.log_artifact(str(scores_path), artifact_path="models")
        log.info("run terminé : %s", scores_path)
        return self.metrics
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_training.py::test_pipeline_evaluate_builds_grouped_scores -q`
Expected: PASS

- [ ] **Step 5: Full training tests + commit**

```bash
uv run pytest tests/test_training.py -q
uv run ruff check app/training tests/test_training.py
uv run ruff format app/training tests/test_training.py
git add app/training/pipeline.py tests/test_training.py
git commit -m "feat: évaluation multi-cible, table de scores et runs MLflow imbriqués

Related to #9"
```

---

## Task 8: CLI `app/training/__main__.py` + suppression de `scripts/`

**Files:**
- Create: `app/training/__main__.py`
- Modify: `.gitignore`, `README.md`
- Delete: `scripts/train_model.py`, `scripts/train_model_seattle.py`, `scripts/__pycache__/`

- [ ] **Step 1: Write the CLI**

`app/training/__main__.py` :

```python
"""Entrée CLI : ``uv run python -m app.training [--download]``."""

from __future__ import annotations

import argparse

from app.training import data_processing as dp
from app.training.pipeline import TrainPipeline


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Entraînement CatBoost multi-cible (P5)")
    parser.add_argument("--csv", default=str(dp.DEFAULT_DATASET_PATH))
    parser.add_argument("--output-dir", default="models")
    parser.add_argument("--download", action="store_true",
                        help="Télécharge le dataset s'il est absent")
    parser.add_argument("--no-kumo", action="store_true",
                        help="N'évalue pas le modèle Kumo")
    parser.add_argument("--cv-splits", type=int, default=5)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    csv_path = dp.ensure_dataset(args.csv, download=args.download)
    pipe = TrainPipeline(
        csv_path=csv_path, output_dir=args.output_dir, cv_splits=args.cv_splits
    )
    metrics = pipe.run(include_kumo=not args.no_kumo)
    print(f"[done] scores: {metrics}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Add `data/` to `.gitignore`**

Ajouter à la fin de `.gitignore` :

```gitignore

# Données brutes téléchargées (reproductibles via `python -m app.training --download`)
data/
```

- [ ] **Step 3: Update the README training section**

Remplacer la section « Entraînement réel » par :

```markdown
**Entraînement réel (pipeline multi-cible + MLflow)** :

```bash
# Sur un clone neuf, télécharge le dataset puis entraîne
uv run python -m app.training --download

# Sinon, dataset déjà présent
uv run python -m app.training
```

Le pipeline entraîne un CatBoost par cible (`SiteEnergyUse(kBtu)` et
`TotalGHGEmissions`), évalue Kumo-Tabular en zero-shot sur le même test et
logue les runs MLflow (`uv run mlflow ui`). Sorties : `models/<cible>.cbm` et
`models/scores.json`.
```

- [ ] **Step 4: Delete the obsolete scripts**

```bash
git rm -r scripts/
```

- [ ] **Step 5: Verify the CLI help + commit**

Run: `uv run python -m app.training --help`
Expected: affiche les options `--csv`, `--output-dir`, `--download`, `--no-kumo`, `--cv-splits`

```bash
git add app/training/__main__.py .gitignore README.md
git commit -m "feat: CLI app.training, data/ ignoré et scripts/ obsolètes supprimés

Related to #9"
```

---

## Task 9: `model_service` multi-cible

**Files:**
- Modify: `app/core/model_service.py`
- Test: `tests/test_models.py` (créer)

- [ ] **Step 1: Write the failing test**

`tests/test_models.py` :

```python
"""Tests des services de modèles (CatBoost multi-cible)."""

import sys
from pathlib import Path

import numpy as np
import pandas as pd
from catboost import CatBoostRegressor

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core import model_service
from app.schemas.api import CAT_FEATURES, FEATURE_COLUMNS, EnergyPredictionRequest


def _train(path, value=1000.0):
    rng = np.random.default_rng(0)
    n = 60
    df = pd.DataFrame({c: rng.uniform(1, 10, n) for c in FEATURE_COLUMNS})
    for c in CAT_FEATURES:
        df[c] = "x"
    m = CatBoostRegressor(iterations=20, depth=3, verbose=0)
    m.fit(df[FEATURE_COLUMNS], np.log1p(np.full(n, value)), cat_features=CAT_FEATURES)
    m.save_model(str(path))


def test_model_service_loads_per_target(tmp_path, monkeypatch):
    p_energy = tmp_path / "energy.cbm"
    p_emiss = tmp_path / "emissions.cbm"
    _train(p_energy, 1000.0)
    _train(p_emiss, 50.0)
    monkeypatch.setitem(model_service.MODEL_PATHS, "energy", str(p_energy))
    monkeypatch.setitem(model_service.MODEL_PATHS, "emissions", str(p_emiss))
    model_service._models.clear()

    req = EnergyPredictionRequest(
        BuildingType="Office", PrimaryPropertyType="Office", Neighborhood="BALLARD",
        Latitude=47.6, Longitude=-122.3, YearBuilt=1990, NumberofBuildings=1,
        NumberofFloors=4, PropertyGFAParking=100, PropertyGFABuilding=1000,
        LargestPropertyUseType="Office", SecondLargestPropertyUseType="Retail",
        SecondLargestPropertyUseTypeGFA=10.0, ThirdLargestPropertyUseType="Parking",
        ThirdLargestPropertyUseTypeGFA=5.0, Has_NaturalGas=True, Has_Steam=False,
    )
    preds = model_service.predict_all(req)
    assert set(preds) == {"energy", "emissions"}
    assert preds["energy"] > 0 and preds["emissions"] > 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_models.py -q`
Expected: FAIL — `AttributeError: module 'app.core.model_service' has no attribute 'MODEL_PATHS'`

- [ ] **Step 3: Rewrite `app/core/model_service.py`**

```python
"""CatBoost multi-cible (consommation + émissions) — chargement paresseux."""

from __future__ import annotations

import os
import threading

import numpy as np
import pandas as pd
from catboost import CatBoostRegressor, Pool

from ..schemas.api import CAT_FEATURES, FEATURE_COLUMNS, TARGETS, EnergyPredictionRequest

MODEL_PATHS = {
    "energy": os.getenv("MODEL_PATH_ENERGY", "models/energy.cbm"),
    "emissions": os.getenv("MODEL_PATH_EMISSIONS", "models/emissions.cbm"),
}

_models: dict[str, CatBoostRegressor] = {}
_lock = threading.Lock()


def load_model(target: str) -> CatBoostRegressor:
    """Charge (une fois) le CatBoost de la cible ``target``."""
    if target not in MODEL_PATHS:
        raise KeyError(f"Cible inconnue : {target}")
    model = _models.get(target)
    if model is None:
        with _lock:
            model = _models.get(target)
            if model is None:
                path = MODEL_PATHS[target]
                if not os.path.exists(path):
                    raise FileNotFoundError(
                        f"Modèle {target} introuvable à {path}. "
                        "Entraînez-le avec `uv run python -m app.training`."
                    )
                model = CatBoostRegressor()
                model.load_model(path)
                _models[target] = model
    return model


def _to_dataframe(request: EnergyPredictionRequest) -> pd.DataFrame:
    data = request.model_dump()
    data["PropertyGFABuilding(s)"] = data.pop("PropertyGFABuilding")
    data["Has_NaturalGas"] = int(data["Has_NaturalGas"])
    data["Has_Steam"] = int(data["Has_Steam"])
    df = pd.DataFrame([data])[FEATURE_COLUMNS]
    for col in CAT_FEATURES:
        df[col] = df[col].astype(str)
    return df


def predict(request: EnergyPredictionRequest, target: str) -> float:
    """Prédiction pour une cible (unités réelles via expm1)."""
    model = load_model(target)
    pool = Pool(_to_dataframe(request), cat_features=CAT_FEATURES)
    return float(np.expm1(model.predict(pool))[0])


def predict_all(request: EnergyPredictionRequest) -> dict[str, float]:
    """Prédiction pour toutes les cibles."""
    return {target: predict(request, target) for target in TARGETS}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_models.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
uv run ruff check app/core/model_service.py tests/test_models.py
uv run ruff format app/core/model_service.py tests/test_models.py
git add app/core/model_service.py tests/test_models.py
git commit -m "refactor: model_service multi-cible avec chargement paresseux par cible

Related to #9"
```

---

## Task 10: `kumo_service` partagé + multi-cible + lots

**Files:**
- Modify: `app/core/kumo_service.py`
- Test: `tests/test_kumo.py` (réécrire)

- [ ] **Step 1: Rewrite the test**

`tests/test_kumo.py` :

```python
"""Tests du service Kumo-Tabular (zero-shot, multi-cible, par lots)."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core import kumo_service
from app.schemas.api import EnergyPredictionRequest, TARGETS

SAMPLE_INPUT = EnergyPredictionRequest(
    BuildingType="Commercial", PrimaryPropertyType="Office", Neighborhood="Ballard",
    Latitude=47.62, Longitude=-122.35, YearBuilt=1990, NumberofBuildings=1,
    NumberofFloors=4, PropertyGFAParking=5000, PropertyGFABuilding=15000,
    LargestPropertyUseType="Office", SecondLargestPropertyUseType="Retail",
    SecondLargestPropertyUseTypeGFA=3000.0, ThirdLargestPropertyUseType="Parking",
    ThirdLargestPropertyUseTypeGFA=2000.0, Has_NaturalGas=True, Has_Steam=False,
)


def test_is_available():
    assert kumo_service.is_available()


@pytest.mark.parametrize("target", list(TARGETS))
def test_predict_positive_per_target(target):
    value = kumo_service.predict(SAMPLE_INPUT, target)
    assert isinstance(value, float)
    assert value > 0


def test_single_shared_model_instance():
    kumo_service.load_model()
    kumo_service.load_model()
    assert kumo_service._model is not None


def test_predict_all_targets():
    preds = kumo_service.predict_all(SAMPLE_INPUT)
    assert set(preds) == set(TARGETS)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_kumo.py -q`
Expected: FAIL — `AttributeError: module 'app.core.kumo_service' has no attribute 'predict'`

- [ ] **Step 3: Rewrite `app/core/kumo_service.py`**

Reprendre la structure existante (contexte synthétique, `TableTensor`, `KumoTabular`) et l'étendre :

```python
"""Kumo-Tabular zero-shot multi-cible (modèle partagé, contexte par cible)."""

from __future__ import annotations

import threading

import numpy as np
import pandas as pd
import torch

from ..schemas.api import FEATURE_COLUMNS, TARGETS, EnergyPredictionRequest

_DEVICE = torch.device("cuda" if torch.cuda.is_available() else "cpu")
_TARGET_COLUMNS = [t["column"] for t in TARGETS.values()]

_model = None
_model_lock = threading.Lock()
_context_tables: dict[str, object] = {}
_context_lock = threading.Lock()

# _CONTEXT_DF_DATA : mêmes 30 lignes de contexte que la version actuelle,
# plus une colonne "TotalGHGEmissions" (heuristique : ~0.1 * énergie).


def _import_sdm():
    import sdm

    return sdm


def load_model():
    """Charge le modèle Kumo une seule fois (partagé entre les cibles)."""
    global _model
    if _model is None:
        with _model_lock:
            if _model is None:
                sdm = _import_sdm()
                _model = sdm.models.KumoTabular(task="regression", device=_DEVICE)
    return _model


def _context_dataframe(target: str) -> pd.DataFrame:
    from . import _kumo_context as ctx  # module de données de contexte

    return ctx.build_context_df(target)


def _context_table(target: str):
    sdm = _import_sdm()
    if target not in _context_tables:
        with _context_lock:
            if target not in _context_tables:
                df = _context_dataframe(target)
                _context_tables[target] = sdm.TableTensor.from_pandas(
                    df=df, stypes=sdm.infer_stypes(df), device=_DEVICE
                )
    return _context_tables[target]


def _to_table(df: pd.DataFrame):
    sdm = _import_sdm()
    d = df.copy()
    d["PropertyGFABuilding(s)"] = d.pop("PropertyGFABuilding")
    d["Has_NaturalGas"] = d["Has_NaturalGas"].astype(float)
    d["Has_Steam"] = d["Has_Steam"].astype(float)
    d = d[FEATURE_COLUMNS]
    for col in [c for c in FEATURE_COLUMNS if c in _CAT]:
        d[col] = d[col].astype(str)
    return sdm.TableTensor.from_pandas(
        df=d, stypes=sdm.infer_stypes(d), device=_DEVICE
    )


_CAT = [
    "BuildingType", "PrimaryPropertyType", "Neighborhood",
    "LargestPropertyUseType", "SecondLargestPropertyUseType",
    "ThirdLargestPropertyUseType",
]


def _predict_dataframe(df: pd.DataFrame, target: str) -> np.ndarray:
    model = load_model()
    column = TARGETS[target]["column"]
    context = _context_table(target)
    query = _to_table(df)
    with torch.no_grad():
        out = model(
            x_context=context.drop_columns(column),
            y_context=context[column],
            x_query=query,
            num_estimators=4,
        )
        pred = out.numerical.mean(dim=-1)
    return pred.detach().cpu().numpy().reshape(-1)


def predict(request: EnergyPredictionRequest, target: str) -> float:
    df = pd.DataFrame([request.model_dump()])
    return float(_predict_dataframe(df, target)[0])


def predict_all(request: EnergyPredictionRequest) -> dict[str, float]:
    return {target: predict(request, target) for target in TARGETS}


def predict_batch(X: pd.DataFrame, target: str) -> np.ndarray:
    """Prédit une matrice de features (colonnes FEATURE_COLUMNS) par lots."""
    return _predict_dataframe(X[FEATURE_COLUMNS], target)


def is_available() -> bool:
    try:
        load_model()
        return True
    except Exception:
        return False
```

Créer `app/core/_kumo_context.py` avec `build_context_df(target)` : les 30 lignes
synthétiques (issues de l'ancien `_CONTEXT_DF_DATA`) auxquelles s'ajoute la
colonne cible demandée (`energy` -> `SiteEnergyUse(kBtu)`, `emissions` ->
`TotalGHGEmissions`, heuristique `0.1 * énergie`). Conserver la graine 42 pour
rester déterministe.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_kumo.py -q`
Expected: PASS (le chargement Kumo prend ~10 s)

- [ ] **Step 5: Commit**

```bash
uv run ruff check app/core/kumo_service.py app/core/_kumo_context.py tests/test_kumo.py
uv run ruff format app/core/kumo_service.py app/core/_kumo_context.py tests/test_kumo.py
git add app/core/kumo_service.py app/core/_kumo_context.py tests/test_kumo.py
git commit -m "refactor: Kumo partagé multi-cible + prédiction par lots

Related to #9"
```

---

## Task 11: `metrics_service` + schémas + router + `test_jwt.py`

**Files:**
- Modify: `app/core/metrics_service.py`, `app/schemas/api.py`, `app/routers/model.py`, `tests/test_jwt.py`

- [ ] **Step 1: Rewrite `app/core/metrics_service.py`**

```python
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
    except Exception:
        return False
```

- [ ] **Step 2: Extend schemas in `app/schemas/api.py`**

Remplacer `EnergyPredictionResponse` et `MetricsResponse` :

```python
class EnergyPredictionResponse(BaseModel):
    """Prédictions pour les deux cibles du modèle."""

    model_name: str
    energy_use_kbtu: float
    ghg_emissions_tco2e: float = 0.0
    predicted_at: datetime
    units: str = "kBtu/an"
    emissions_units: str = "t CO2e/an"


class ModelScores(BaseModel):
    R2: float
    MAE: float
    MedAE: float
    MedAPE_pct: float


class TargetScores(BaseModel):
    unit: str
    models: dict[str, ModelScores]


class MetricsResponse(BaseModel):
    """Table de scores regroupée par cible (modèles CatBoost et Kumo)."""

    targets: dict[str, TargetScores]
```

`ComparisonPredictionResponse` reste inchangé.

- [ ] **Step 3: Rewrite `app/routers/model.py`**

```python
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
    Model(id=1, name="catboost-energy-seattle",
          created_at=datetime(2026, 1, 1, tzinfo=UTC)),
    Model(id=2, name="catboost-emissions-seattle",
          created_at=datetime(2026, 1, 2, tzinfo=UTC)),
    Model(id=3, name="kumo-tabular-zero-shot",
          created_at=datetime(2026, 1, 3, tzinfo=UTC)),
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


@router.post("/predict", response_model=EnergyPredictionResponse,
             responses={503: {"description": "Model not loaded"}})
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


@router.post("/predict/compare", response_model=ComparisonPredictionResponse,
             responses={503: {"description": "One or both models could not be loaded"}})
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
            model_name=name, energy_use_kbtu=energy,
            ghg_emissions_tco2e=emissions, predicted_at=now,
        )

    return ComparisonPredictionResponse(
        catboost_prediction=resp("catboost-multitarget", cb["energy"], cb["emissions"]),
        kumo_prediction=resp("kumo-tabular-zero-shot", km["energy"], km["emissions"]),
    )
```

- [ ] **Step 4: Fix and update `tests/test_jwt.py`**

- Déplacer l'`assert r.status_code == 422` dans le corps de
  `test_model_predict_rejects_extra_field` (actuellement fusionné dans
  `test_metrics_with_token`).
- `test_model_list_with_token` : attendre **3** modèles.
- `test_model_predict_with_token` : ajouter
  `assert body["ghg_emissions_tco2e"] > 0`.
- `test_metrics_with_token` : lire la forme regroupée
  (`body["targets"]["energy"]["models"]["catboost"]["R2"]`) ; écrire un
  `models/scores.json` de test via un fixture `tmp_path` + `MODEL_METRICS_PATH`.
- Le fixture `ensure_demo_model` doit entraîner **deux** modèles et pointer
  `model_service.MODEL_PATHS` sur les fichiers temporaires, puis vider
  `model_service._models`.

- [ ] **Step 5: Run the full suite + commit**

```bash
uv run pytest -q
uv run ruff check .
uv run ruff format --check .
git add app/core/metrics_service.py app/schemas/api.py app/routers/model.py tests/test_jwt.py
git commit -m "feat: API multi-cible, table de scores regroupée et correction test_jwt

Related to #9"
```

---

## Task 12: Vérification finale

- [ ] **Step 1: Full test suite with coverage**

Run: `uv run pytest --cov=app -q`
Expected: tous les tests passent (y compris l'ancien test rouge corrigé)

- [ ] **Step 2: Lint + format**

Run: `uv run ruff check . && uv run ruff format --check .`
Expected: aucune erreur

- [ ] **Step 3: Smoke test du CLI d'entraînement (jeu réduit)**

Run: `uv run python -m app.training --help`
Expected: exit 0, options listées

- [ ] **Step 4: Final commit (si ajustements)**

```bash
git add -A
git commit -m "chore: vérification finale pipeline multi-cible et serving (#9)"
```

---

## Self-Review (auteur du plan)

- **Couverture spec** : layout `app/training` + `app/lib` (Tasks 1-8), pipeline 7 étapes (Tasks 4-7), MLflow 2 modèles (Task 7), API étendue + table regroupée (Tasks 9-11), stratégie d'inférence A (Kumo partagé Task 10, threadpool Task 11), dataset + `data/` ignoré (Tasks 3, 8), tests + bug `test_jwt` (Tasks 1, 9-11). ✔
- **Placeholders** : le seul contenu « à compléter » est `_kumo_context.py` (données de contexte) — le plan précise la source (ancien `_CONTEXT_DF_DATA` + heuristique émissions), ce qui est suffisant pour l'implémenteur. ✔
- **Cohérence des noms** : `MODEL_PATHS`, `_models`, `predict`, `predict_all`, `predict_batch`, `TARGETS`, `FEATURE_COLUMNS`, `scores.json` utilisés de façon identique dans les tasks de service/routeur/tests. ✔
