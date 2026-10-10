# Gate CI de performance du modèle — Plan d'implémentation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ajouter un gate CI/CD qui échoue si les performances du modèle se dégradent par rapport à une baseline committée.

**Architecture:** Le pipeline d'entraînement écrit `models/scores.json` (écrasé à chaque entraînement). Une baseline gelée `models/scores_baseline.json` sert de référence. Un module pur `app/training/score_validation.py` compare les deux (MedAPE qui monte de > 5 pts ou R2 qui baisse de > 0,05 par cible = échec). Un workflow `ci-model-performance.yml` lance ce module sur chaque PR. Au passage, correction d'un bug bloquant : les catégorielles avec NA faisaient planter CatBoost sur le dataset réel.

**Tech Stack:** Python 3.12, CatBoost, pandas 3.0, pytest, GitHub Actions, uv.

---

## File Structure

- Create: `app/training/score_validation.py` — logique de comparaison + CLI.
- Create: `tests/test_score_validation.py` — tests du gate.
- Create: `.github/workflows/ci-model-performance.yml` — workflow CI.
- Create: `models/scores.json`, `models/scores_baseline.json` — artefacts committés.
- Modify: `app/training/data_processing.py` — fix NA catégoriels (`prepare_catboost`).
- Modify: `tests/test_training.py` — test du fix.
- Modify: `.gitignore` — dé-ignorer les deux fichiers de scores.
- Modify: `docs/ci-cd/README.md` — documenter le nouveau gate.

---

### Task 1: Corriger les NA catégoriels (prérequis entraînement réel)

**Files:**
- Modify: `app/training/data_processing.py:88-92`
- Test: `tests/test_training.py`

- [ ] **Step 1: Écrire le test qui échoue**

Ajouter à `tests/test_training.py` :

```python
def test_prepare_catboost_fills_missing_categoricals():
    df = make_synth(40)
    df.loc[0, "SecondLargestPropertyUseType"] = np.nan
    df.loc[1, "ThirdLargestPropertyUseType"] = np.nan
    X, _, _ = dp.prepare_dataset(df)
    for col in dp.CAT_FEATURES:
        assert not X[col].isna().any()
    assert X.loc[0, "SecondLargestPropertyUseType"] == "UNKNOWN"
    assert X.loc[1, "ThirdLargestPropertyUseType"] == "UNKNOWN"
```

- [ ] **Step 2: Lancer le test, vérifier l'échec**

Run: `uv run pytest tests/test_training.py::test_prepare_catboost_fills_missing_categoricals -v`
Expected: FAIL (`assert ...` sur NA restants).

- [ ] **Step 3: Implémenter le fix minimal**

Dans `app/training/data_processing.py`, remplacer le corps de `prepare_catboost` :

```python
def prepare_catboost(X: pd.DataFrame, flags: pd.DataFrame) -> pd.DataFrame:
    """Catégorielles brutes en str + marqueurs de raccordement.

    Les valeurs manquantes sont remplacées par ``"UNKNOWN"`` : sans cela,
    pandas 3.0 conserve les NA et CatBoost refuse les catégorielles non-str.
    """
    d = X.copy()
    for col in CAT_FEATURES:
        d[col] = d[col].astype("string").fillna("UNKNOWN").astype(str)
    return d.join(flags)[FEATURE_COLUMNS]
```

- [ ] **Step 4: Lancer le test, vérifier le succès**

Run: `uv run pytest tests/test_training.py::test_prepare_catboost_fills_missing_categoricals -v`
Expected: PASS.

- [ ] **Step 5: Lancer toute la suite training**

Run: `uv run pytest tests/test_training.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add app/training/data_processing.py tests/test_training.py
git commit -m "fix(training): remplace les NA catégoriels par UNKNOWN (CatBoost)"
```

---

### Task 2: Module de validation des scores

**Files:**
- Create: `app/training/score_validation.py`
- Test: `tests/test_score_validation.py`

- [ ] **Step 1: Écrire les tests qui échouent**

Créer `tests/test_score_validation.py` :

```python
"""Tests du gate de performance (app.training.score_validation)."""

from __future__ import annotations

from app.training.score_validation import validate_scores


def _scores(energy=(0.30, 40.0), emissions=(0.15, 45.0)):
    def block(r2, medape):
        return {"catboost": {"R2": r2, "MAE": 2.0, "MedAE": 1.0, "MedAPE_pct": medape}}

    return {
        "targets": {
            "energy": {"unit": "kBtu/an", "models": block(*energy)},
            "emissions": {"unit": "t CO2e/an", "models": block(*emissions)},
        }
    }


def test_validate_passes_when_no_regression():
    s = _scores()
    assert validate_scores(s, s) == []


def test_validate_fails_on_medape_increase():
    cur = _scores(energy=(0.30, 46.0))
    base = _scores(energy=(0.30, 40.0))
    violations = validate_scores(cur, base)
    assert any("energy" in v and "MedAPE_pct" in v for v in violations)


def test_validate_fails_on_r2_drop():
    cur = _scores(emissions=(0.10, 45.0))
    base = _scores(emissions=(0.20, 45.0))
    violations = validate_scores(cur, base)
    assert any("emissions" in v and "R2" in v for v in violations)


def test_validate_within_margins_passes():
    base = _scores()
    cur = _scores(energy=(0.30, 44.9), emissions=(0.11, 49.9))
    assert validate_scores(cur, base) == []


def test_validate_missing_target_fails():
    cur = _scores()
    del cur["targets"]["emissions"]
    violations = validate_scores(cur, _scores())
    assert any("emissions" in v for v in violations)


def test_validate_missing_metric_fails():
    cur = _scores()
    del cur["targets"]["energy"]["models"]["catboost"]["R2"]
    violations = validate_scores(cur, _scores())
    assert any("energy" in v and "R2" in v for v in violations)


def test_validate_missing_model_fails():
    cur = _scores()
    del cur["targets"]["energy"]["models"]["catboost"]
    violations = validate_scores(cur, _scores())
    assert any("energy" in v for v in violations)
```

- [ ] **Step 2: Lancer, vérifier l'échec**

Run: `uv run pytest tests/test_score_validation.py -q`
Expected: FAIL (module introuvable).

- [ ] **Step 3: Implémenter le module**

Créer `app/training/score_validation.py` :

```python
"""Validation des scores du dernier entraînement (gate CI de non-régression).

Compare ``models/scores.json`` (dernier entraînement) à
``models/scores_baseline.json`` (référence gelée) et échoue si les métriques
CatBoost se dégradent au-delà des marges autorisées.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

DEFAULT_SCORES_PATH = Path("models/scores.json")
DEFAULT_BASELINE_PATH = Path("models/scores_baseline.json")

TARGETS = ("energy", "emissions")
MODEL_NAME = "catboost"
MEDAPE_KEY = "MedAPE_pct"
R2_KEY = "R2"

# Marges de non-régression tolérées.
MAX_MEDAPE_INCREASE = 5.0  # points de %
MIN_R2_DROP = 0.05


def _metric(block: Any, key: str) -> float | None:
    if not isinstance(block, dict):
        return None
    value = block.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _target_model(scores: Any, target: str) -> dict | None:
    if not isinstance(scores, dict):
        return None
    targets = scores.get("targets")
    if not isinstance(targets, dict):
        return None
    block = targets.get(target)
    if not isinstance(block, dict):
        return None
    models = block.get("models")
    if not isinstance(models, dict):
        return None
    model = models.get(MODEL_NAME)
    return model if isinstance(model, dict) else None


def validate_scores(
    scores: Any,
    baseline: Any,
    *,
    max_medape_increase: float = MAX_MEDAPE_INCREASE,
    min_r2_drop: float = MIN_R2_DROP,
) -> list[str]:
    """Retourne la liste des violations (vide = gate OK)."""
    violations: list[str] = []
    for target in TARGETS:
        cur = _target_model(scores, target)
        if cur is None:
            violations.append(f"{target}: scores '{MODEL_NAME}' absents ou invalides")
            continue
        ref = _target_model(baseline, target)
        if ref is None:
            violations.append(f"{target}: baseline '{MODEL_NAME}' absente ou invalide")
            continue

        cur_medape = _metric(cur, MEDAPE_KEY)
        ref_medape = _metric(ref, MEDAPE_KEY)
        cur_r2 = _metric(cur, R2_KEY)
        ref_r2 = _metric(ref, R2_KEY)

        if cur_medape is None or ref_medape is None:
            violations.append(f"{target}: métrique '{MEDAPE_KEY}' manquante")
        elif cur_medape > ref_medape + max_medape_increase:
            violations.append(
                f"{target}: {MEDAPE_KEY} {cur_medape:.2f}% > baseline "
                f"{ref_medape:.2f}% + {max_medape_increase:.1f} pts"
            )

        if cur_r2 is None or ref_r2 is None:
            violations.append(f"{target}: métrique '{R2_KEY}' manquante")
        elif cur_r2 < ref_r2 - min_r2_drop:
            violations.append(
                f"{target}: {R2_KEY} {cur_r2:.3f} < baseline "
                f"{ref_r2:.3f} - {min_r2_drop:.2f}"
            )
    return violations


def _load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Gate de performance du modèle")
    parser.add_argument("scores", nargs="?", default=str(DEFAULT_SCORES_PATH))
    parser.add_argument("baseline", nargs="?", default=str(DEFAULT_BASELINE_PATH))
    args = parser.parse_args(argv)

    for label, raw in (("scores", args.scores), ("baseline", args.baseline)):
        if not Path(raw).exists():
            print(f"❌ Fichier {label} introuvable : {raw}")
            return 1
    try:
        scores = _load(Path(args.scores))
        baseline = _load(Path(args.baseline))
    except json.JSONDecodeError as exc:
        print(f"❌ JSON invalide : {exc}")
        return 1

    violations = validate_scores(scores, baseline)
    if violations:
        print("❌ Gate performance : ÉCHEC")
        for v in violations:
            print(f"   - {v}")
        return 1

    print("✅ Gate performance : OK (pas de régression)")
    for target in TARGETS:
        cur = _target_model(scores, target) or {}
        ref = _target_model(baseline, target) or {}
        print(
            f"   {target}: MedAPE {cur.get(MEDAPE_KEY):.2f}% "
            f"(baseline {ref.get(MEDAPE_KEY):.2f}%) | "
            f"R2 {cur.get(R2_KEY):.3f} (baseline {ref.get(R2_KEY):.3f})"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Lancer, vérifier le succès**

Run: `uv run pytest tests/test_score_validation.py -q`
Expected: PASS (7 tests).

- [ ] **Step 5: Commit**

```bash
git add app/training/score_validation.py tests/test_score_validation.py
git commit -m "feat(training): ajoute le gate de non-régression des scores"
```

---

### Task 3: Dé-ignorer et bootstrapper les fichiers de scores

**Files:**
- Modify: `.gitignore` (ligne `models/`)
- Create: `models/scores.json`, `models/scores_baseline.json`

- [ ] **Step 1: Modifier `.gitignore`**

Remplacer la ligne `models/` par :

```
models/*
!models/scores.json
!models/scores_baseline.json
```

- [ ] **Step 2: Générer un entraînement réel**

Run: `uv run python -m app.training --no-kumo`
Expected: termine, écrit `models/scores.json` (multi-cible catboost).

- [ ] **Step 3: Créer la baseline**

Run: `cp models/scores.json models/scores_baseline.json`
Expected: `models/scores_baseline.json` identique.

- [ ] **Step 4: Vérifier que Git les voit**

Run: `git check-ignore models/scores.json models/energy.cbm || true` et `git status --short models`
Expected: `scores.json` et `scores_baseline.json` listés, `.cbm` toujours ignoré.

- [ ] **Step 5: Commit**

```bash
git add .gitignore models/scores.json models/scores_baseline.json
git commit -m "chore(training): committe scores.json + baseline pour le gate CI"
```

---

### Task 4: Workflow GitHub Actions

**Files:**
- Create: `.github/workflows/ci-model-performance.yml`

- [ ] **Step 1: Créer le workflow**

Créer `.github/workflows/ci-model-performance.yml` :

```yaml
# Workflow : Gate de performance du modèle (non-régression)
# Compare les scores du dernier entraînement à la baseline committée.
name: ci-model-performance

on:
  pull_request:
    branches: [main]
    types: [opened, synchronize, reopened, ready_for_review]
  workflow_dispatch:

concurrency:
  group: model-performance-${{ github.ref }}
  cancel-in-progress: true

permissions:
  contents: read

jobs:
  ci-model-performance:
    name: ci-model-performance
    runs-on: ubuntu-latest
    timeout-minutes: 10

    steps:
      - name: Checkout du code
        uses: actions/checkout@v4
        with:
          fetch-depth: 0

      - name: Installer Python 3.12
        uses: actions/setup-python@v5
        with:
          python-version: "3.12"

      - name: Installer uv
        uses: astral-sh/setup-uv@d4b2f3b6ecc6e67c4457f6d3e41ec42d3d0fcb86 # v5
        with:
          version: "latest"
          cache-dependency-glob: "uv.lock"

      - name: Synchroniser les dépendances
        run: |
          set -euo pipefail
          uv sync --frozen --no-cache --no-install-project

      - name: Gate performance (dernier entraînement vs baseline)
        run: |
          set -euo pipefail
          uv run --frozen --no-sync python -m app.training.score_validation \
            models/scores.json \
            models/scores_baseline.json
```

- [ ] **Step 2: Valider le YAML**

Run: `uv run --with yamllint yamllint -d '{"extends": "default", "rules": {"line-length": "disable", "document-start": "disable", "brackets": "disable", "new-line-at-end-of-file": "disable"}}' .github/workflows/ci-model-performance.yml`
Expected: aucune erreur.

- [ ] **Step 3: Simuler le gate en local**

Run: `uv run python -m app.training.score_validation models/scores.json models/scores_baseline.json`
Expected: `✅ Gate performance : OK (pas de régression)`.

- [ ] **Step 4: Commit**

```bash
git add .github/workflows/ci-model-performance.yml
git commit -m "ci: ajoute le gate de performance du modèle (ci-model-performance)"
```

---

### Task 5: Documentation

**Files:**
- Modify: `docs/ci-cd/README.md` (table CI)

- [ ] **Step 1: Ajouter la ligne au tableau CI**

Après la ligne `ci-test.yml`, ajouter :

```
| `ci-model-performance.yml` | `ci-model-performance` | Gate non-régression du modèle : compare `models/scores.json` (dernier entraînement) à `models/scores_baseline.json` |
```

- [ ] **Step 2: Commit**

```bash
git add docs/ci-cd/README.md
git commit -m "docs(ci-cd): documente le gate ci-model-performance"
```

---

### Task 6: Vérification finale

- [ ] **Step 1: Suite de tests complète + couverture**

Run: `uv run pytest --cov=app tests/ -q`
Expected: PASS, couverture ≥ 70 %.

- [ ] **Step 2: Lint**

Run: `.venv/bin/ruff check . && .venv/bin/ruff format --check .`
Expected: aucune erreur.

- [ ] **Step 3: Gate en conditions nominales et dégradées**

Run: `uv run python -m app.training.score_validation`
Expected: OK.

Puis simuler une régression (MedAPE +10) et vérifier un code de sortie 1.
