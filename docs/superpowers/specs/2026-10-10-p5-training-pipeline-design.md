# Design — Pipeline d'entraînement multi-cible + serving optimisé (P5)

**Date** : 2026-10-10
**Auteur** : William Derue
**Statut** : proposé (en attente de revue)

---

## 1. Contexte

Le projet P5 expose via FastAPI un modèle CatBoost de prédiction de la
consommation d'énergie des bâtiments de Seattle. Le notebook de référence P3
modélise **deux cibles** — `SiteEnergyUse(kBtu)` (consommation, kBtu/an) et
`TotalGHGEmissions` (émissions, t CO₂e/an) — et produit un tableau de scores
comparable par cible.

Aujourd'hui dans P5 :

- deux scripts d'entraînement coexistent (`scripts/train_model.py`
  synthétique, `scripts/train_model_seattle.py` réel) ;
- une seule cible est entraînée et exposée ; `TotalGHGEmissions` est écartée
  comme fuite ;
- Kumo-Tabular (NVIDIA `structured-data-models`) est intégré en zero-shot sur
  la consommation uniquement ;
- MLflow n'est branché que sur CatBoost ;
- `tests/test_jwt.py` contient un bug pré-existant (assertion mal placée).

## 2. Objectifs

1. **Un seul** script d'entraînement, organisé en package `app/training/`.
2. Une classe `TrainPipeline` aux **étapes découplées et testables**.
3. Entraîner CatBoost sur les **deux cibles** et évaluer Kumo (zero-shot) sur
   les deux cibles, sur le **même split de test**.
4. Intégration MLflow complète pour **les deux modèles** (CatBoost ×2 cibles,
   Kumo ×2 cibles).
5. Table de scores **R² / MAE / MedAE / MedAPE%** par (cible, modèle),
   **regroupée par cible**, servie par l'API.
6. API étendue : prédire les émissions en plus de la consommation.
7. Chargement des modèles optimisé (stratégie lazy + Kumo partagé).
8. Reproductibilité : téléchargement automatique du dataset au démarrage.

## 3. Non-objectifs

- Pas de changement de modèle/algorithme (on garde CatBoost + Kumo).
- Pas de nouvelle base de données ni de migration (le scaffolding
  `database_service` reste hors périmètre).
- Pas de bagging/ensemble par seeds (le `train_final` boucle uniquement sur les
  cibles).

## 4. Architecture cible

```
app/
├── lib/
│   ├── __init__.py
│   └── tools.py            # logging / wrapper / helper
├── training/
│   ├── __init__.py
│   ├── __main__.py         # CLI : python -m app.training [--download] [--csv ...]
│   ├── data_processing.py  # nettoyage, flags, prépa CatBoost, dataset
│   └── pipeline.py         # class TrainPipeline
├── core/
│   ├── model_service.py    # CatBoost multi-cible (énergie + émissions)
│   ├── kumo_service.py     # Kumo partagé, contexte par cible
│   └── metrics_service.py  # table de scores (2 cibles × 2 modèles)
├── routers/model.py        # routes étendues
└── schemas/api.py          # schémas étendus
```

- `/scripts/` est **supprimé** (`train_model.py`, `train_model_seattle.py`).
- Entrée d'entraînement : `uv run python -m app.training`.
- `data/` ajouté au `.gitignore` ; dataset téléchargé par script.

## 5. `app/lib/tools.py`

Trois familles de fonctions transverses.

**logging**

- `get_logger(name) -> logging.Logger` : logger configuré, handler unique,
  format horodaté (`%(asctime)s %(levelname)s %(name)s %(message)s`), pas de
  handler dupliqué si appelé plusieurs fois.
- `setup_logging(level="INFO")` : configuration racine idempotente.

**wrapper** (décorateurs)

- `@timed(label=None)` : logue la durée d'exécution de la fonction.
- `@log_calls` : logue entrée/sortie (résumé des arguments, pas de valeurs
  sensibles).
- `log_mlflow_metrics(prefix, metrics)` : enveloppe `mlflow.log_metric` en
  nettoyant les clés (voir `sanitize_metric_key`).

**helper**

- `sanitize_metric_key(name)` : remplace `%` par `pct` (compatibilité MLflow).
- `ensure_dir(path) -> Path`.
- `save_json(path, obj)` / `load_json(path)`.
- `set_seed(seed)` : graine `random` + `numpy` (+ `PYTHONHASHSEED` documenté).
- `metrics_reelles(y_true, y_pred) -> dict` : métriques en unités réelles
  (`R2`, `MAE`, `MedAE`, `MedAPE_%`) — identique au notebook P3.

## 6. `app/training/data_processing.py`

Reprend et factorise la logique existante de `train_model_seattle.py` :

- `PII_COLUMNS`, `DATA_LEAKAGE_COLUMNS`, `TARGETS` (les 2 cibles).
- `build_clean(df_raw) -> pd.DataFrame` : filtres F0 → F11, **conserve les deux
  cibles**, retire PII + fuites.
- `build_flags(df_raw, df_clean) -> pd.DataFrame` : `Has_NaturalGas`,
  `Has_Steam`.
- `prepare_catboost(X, flags) -> pd.DataFrame` : catégorielles en `str` +
  flags, colonnes ordonnées selon `FEATURE_COLUMNS`.
- `ensure_dataset(path, url=DATASET_URL, download=False) -> Path` : renvoie le
  chemin du CSV ; si absent et `download=True`, le télécharge (idempotent).
- `DATASET_URL = "https://s3.eu-west-1.amazonaws.com/course.oc-static.com/projects/Data_Scientist_P4/2016_Building_Energy_Benchmarking.csv"`.

## 7. `app/training/pipeline.py` — `TrainPipeline`

Classe dont chaque étape est une méthode publique testable, avec un état porté
par l'instance. `run()` orchestre dans l'ordre.

| Étape | Méthode | Sortie / état |
|---|---|---|
| 1 | `split()` | `self.X_train, X_test, y_train, y_test` (DataFrames bruts nettoyés, 80/20, seed 42) |
| 2 | `feature_engineering()` | `self.X_train_fe, self.X_test_fe` (cat→str + flags, ajusté sur train) |
| 3 | `cross_validate()` | `self.cv_results` (métriques par pli + mean/std) |
| 4 | `pre_tune()` | `self.pre_tuned_grid` (grille restreinte dérivée de la CV) |
| 5 | `fine_tune()` | `self.best_params` (candidat pénalisé overfit/overkill) |
| 6 | `train_final()` | `self.models` (1 `.cbm` par cible) |
| 7 | `evaluate()` | `self.metrics` (table de scores) |
| — | `run()` | orchestration + logging MLflow |

**Détail des étapes sensibles**

- **split d'abord, feature engineering ensuite** : le split opère sur les
  données nettoyées ; l'encodage/flags est ajusté sur le train puis appliqué au
  test (pas de fuite).
- **pre_tune** : à partir de `cv_results`, dérive une grille restreinte
  (zone d'hyperparamètres prometteuse + budget d'arbres maximal pour éviter
  l'« overkill »).
- **fine_tune** : parcourt `pre_tuned_grid` avec early stopping +
  `use_best_model` ; classe les candidats par `MedAPE` val, puis `R2` val, puis
  `overfit_gap` ; départage les égalités par **coût de complexité** (moins
  d'arbres / profondeur moindre).
- **train_final** : boucle sur les 2 cibles ; refit sur tout le train ; une
  sauvegarde `.cbm` par cible.
- **evaluate** : métriques test par cible en unités réelles.

**Métriques** (`metrics_reelles`) : `R2`, `MAE`, `MedAE`, `MedAPE_%`.

## 8. MLflow

- Un run parent (`catboost-energy-seattle` remplacé par un nom générique,
  ex. `p5-multitarget`), avec **runs imbriqués par cible** pour CatBoost :
  hyperparamètres, CV (mean/std/par pli), métriques test, artefact `.cbm`.
- **Kumo** : run d'évaluation par cible (zero-shot, pas d'entraînement) loggant
  les mêmes métriques test + la config du contexte. Évaluation **par lots**
  (`x_query` multi-lignes) pour rester rapide.
- Artifact final : table de scores consolidée (JSON + CSV).

## 9. API (scope B)

- `model_service.py` : deux modèles CatBoost paresseux, chemins
  `MODEL_PATH_ENERGY` / `MODEL_PATH_EMISSIONS` (défauts sous `models/`).
- `kumo_service.py` : **une instance Kumo partagée** (singleton), table de
  contexte cachée **par cible**.
- `POST /model/predict` : réponse **additive** — `energy_use_kbtu` **et**
  `ghg_emissions_tco2e` (rétro-compatible avec les champs existants).
- `POST /model/predict/compare` : CatBoost vs Kumo, pour les deux cibles.
- `GET /model/metrics` : table de scores **regroupée par cible**, chaque cible
  contenant ses entrées par modèle. Forme de réponse :

  ```json
  {
    "targets": {
      "SiteEnergyUse(kBtu)": {
        "unit": "kBtu/an",
        "models": {
          "catboost":  {"R2": 0.85, "MAE": 45000.0, "MedAE": 28000.0, "MedAPE_pct": 12.5},
          "kumo":      {"R2": 0.71, "MAE": 61000.0, "MedAE": 39000.0, "MedAPE_pct": 19.3}
        }
      },
      "TotalGHGEmissions": {
        "unit": "t CO2e/an",
        "models": {
          "catboost":  {"R2": 0.80, "MAE": 120.0, "MedAE": 70.0, "MedAPE_pct": 15.0},
          "kumo":      {"R2": 0.66, "MAE": 180.0, "MedAE": 110.0, "MedAPE_pct": 22.0}
        }
      }
    }
  }
  ```

  (Les valeurs ci-dessus sont **illustratives** ; les vraies proviennent de
  `evaluate()`.)
- `GET /model/list` : liste des modèles logiques (CatBoost énergie, CatBoost
  émissions, Kumo).

**Stratégie de chargement (option A retenue)**

- Chargement **lazy** + singleton caché (thread-safe), par modèle.
- Kumo chargé **une seule fois**, réutilisé pour les deux cibles (3 artefacts :
  2 CatBoost + 1 Kumo).
- Seuls les modèles nécessaires à la requête sont chargés.
- Endpoints `async` qui **délèguent le calcul CPU à un threadpool**
  (`asyncio.to_thread`) pour ne pas bloquer l'event loop.
- `compare` exécute CatBoost (rapide) puis Kumo.

## 10. Reproductibilité / dataset

- `data/` ajouté au `.gitignore`.
- `ensure_dataset(..., download=True)` idempotent.
- CLI : `uv run python -m app.training --download` sur un clone neuf.
- `README` mis à jour avec la procédure.

## 11. Tests

- **Corriger** le bug `tests/test_jwt.py` : replacer l'assertion 422 dans
  `test_model_predict_rejects_extra_field` (actuellement fusionnée dans
  `test_metrics_with_token`).
- Adapter `test_jwt.py` : nouvelle liste de modèles, réponses multi-cible.
- Migrer `tests/test_training.py` vers `app.training` / `TrainPipeline`
  (chaque étape testée).
- Étendre `tests/test_kumo.py` aux deux cibles.
- Nouveaux tests pour `app/lib/tools.py`.
- Objectif de couverture maintenu (voir `pyproject.toml`).

## 12. Erreurs & robustesse

- Fichier dataset absent → message explicite + `--download`.
- Modèle `.cbm` absent au serving → `503` (comportement actuel conservé).
- Kumo indisponible → `503` avec cause.
- Métriques absentes → `404`.
- Téléchargement dataset : échec réseau → erreur explicite, pas de fichier
  partiel (téléchargement vers `.tmp` puis `rename`).

## 13. Risques

- **Coût évaluation Kumo** sur tout le test → mitigation par prédiction par
  lots.
- **Compatibilité ascendante** des réponses API → ajouts uniquement, pas de
  suppression de champs.
- **Charge CPU** de Kumo en production (pas de GPU) → threadpool + singletons.

## 14. Points de décision tranchés

- Layout sous `app/` (option B).
- Deux étapes de tuning distinctes (pré-réglage puis fine-tuning).
- `train_final` boucle sur les cibles.
- Stratégie d'inférence A (lazy + Kumo partagé).
- Table de scores regroupée par cible.
- `data/` en `.gitignore` + script de téléchargement.
