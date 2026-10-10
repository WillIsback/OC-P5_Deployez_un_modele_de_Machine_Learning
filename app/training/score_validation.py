"""Validation des scores du dernier entraînement (gate CI de non-régression).

Compare ``models/scores.json`` (dernier entraînement) à
``models/scores_baseline.json`` (référence gelée) et échoue si les métriques
CatBoost se dégradent au-delà des marges autorisées.
"""

from __future__ import annotations

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


def main() -> int:
    """Point d'entrée CLI : lit les deux fichiers canoniques du dépôt.

    Les chemins sont des constantes (pas d'argument CLI) afin d'éviter toute
    injection de chemin via l'entrée utilisateur.
    """
    for label, path in (
        ("scores", DEFAULT_SCORES_PATH),
        ("baseline", DEFAULT_BASELINE_PATH),
    ):
        if not path.exists():
            print(f"❌ Fichier {label} introuvable : {path}")
            return 1
    try:
        scores = _load(DEFAULT_SCORES_PATH)
        baseline = _load(DEFAULT_BASELINE_PATH)
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
