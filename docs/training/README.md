# Entraînement du modèle

Le dépôt **livre le modèle entraîné** (`models/energy.cbm`, `models/emissions.cbm`, scores dans `models/scores.json`) : le [Quickstart](../../README.md#-quickstart) sert l'API sans entraînement, avec la version `baseline` enregistrée par `create_db`. Ce document décrit comment réentraîner.

## Entraînement réel

Pipeline multi-cible + MLflow, environ 5 minutes. Il remplace les modèles livrés dans `models/` (à commiter avec `models/scores.json`, contrôlé par la gate `ci-model-performance`). Avec Docker Compose, après le Quickstart :

```bash
printf 'UID=%s\nGID=%s\n' "$(id -u)" "$(id -g)" >> .env   # le service tools écrit dans ./models avec votre uid
mkdir -p mlruns
docker compose run --rm tools python -m app.training
docker compose restart api          # recharge les nouveaux .cbm
```

Ou en local avec `uv` :

```bash
# 1. Ingérer l'année d'entraînement (nettoyage, features et split inclus)
#    (le CSV 2016 doit être présent dans data/ ; --download le récupère s'il est absent,
#    mais uniquement en local avec `uv run` : dans le service tools, ./data est monté en lecture seule)
uv run python -m app.db.ingest --year 2016 --csv data/2016_Building_Energy_Benchmarking.csv [--download]

# 2. Entraîner depuis la base (rôle propriétaire : DATABASE_OWNER_URL)
uv run python -m app.training
```

L'entraînement lit désormais les features et cibles dans PostgreSQL (`building_years`, `buildings.split` et `building_actuals`), et non plus le CSV. Le pipeline entraîne un CatBoost par cible (`SiteEnergyUse(kBtu)` et
`TotalGHGEmissions`), évalue Kumo-Tabular en zero-shot sur le même test et
logue les runs MLflow (`uv run mlflow ui --backend-store-uri "$MLFLOW_TRACKING_URI"`). Sorties : `models/<cible>.cbm`,
`models/scores.json` et `models/version.json` (version servie, lue par l'API).

## Suivi d'expérimentation avec MLflow

L'entraînement (`app.training`) journalise automatiquement chaque run dans **MLflow** :
- **Run parent `p5-multitarget`** : paramètres `test_size`, `seed`, `cv_splits` ; artefacts `scores.json` / `scores.csv`.
- **Run imbriqué par cible `catboost-<cible>`** : meilleurs hyper-paramètres, scores CV sur l'entraînement (`cv_train_*`, `cv_train_std_*`, `cv_fold*_*`), évaluation sur le test (`test_R2`, `test_MAE`, `test_MedAE`, `test_MedAPE_pct`) et artefact du modèle `.cbm`.
- **Run imbriqué par cible `kumo-<cible>`** : évaluation Kumo-Tabular en zero-shot (`test_*`).

Configurable par variables d'environnement :
```bash
export MLFLOW_TRACKING_URI="postgresql+psycopg://p5_mlflow:<mdp>@localhost:5432/mlflow"   # voir .example.env
export MLFLOW_EXPERIMENT="seattle-energy"           # défaut
uv run python -m app.training
```
Puis visualiser (les runs sont dans PostgreSQL, pas dans `./mlruns` : préciser la base) :
```bash
uv run mlflow ui --backend-store-uri "$MLFLOW_TRACKING_URI"
```

## Tests unitaires du training

```bash
uv run pytest tests/test_training.py -q        # pipeline, CV, tune, MLflow
uv run pytest --cov=app tests/                 # ensemble des tests
```
