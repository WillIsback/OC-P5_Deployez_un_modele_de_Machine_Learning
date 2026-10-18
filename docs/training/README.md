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
#    en local comme dans le service tools où ./data est monté en lecture-écriture)
uv run python -m app.db.ingest --year 2016 --csv data/2016_Building_Energy_Benchmarking.csv [--download]

# 2. Entraîner depuis la base (rôle propriétaire : DATABASE_OWNER_URL)
uv run python -m app.training
```

L'entraînement lit désormais les features et cibles dans PostgreSQL (`building_years`, `buildings.split` et `building_actuals`), et non plus le CSV. Le pipeline entraîne un CatBoost par cible (`SiteEnergyUse(kBtu)` et
`TotalGHGEmissions`), évalue Kumo-Tabular en zero-shot sur le même test et
logue les runs MLflow (`uv run mlflow ui --backend-store-uri "$MLFLOW_TRACKING_URI"`). Sorties : `models/<cible>.cbm`,
`models/kumo_context.csv` (contexte de Kumo), `models/scores.json` et `models/version.json` (version servie, lue par l'API).

## Kumo-Tabular en zero-shot

Kumo-Tabular n'est jamais entraîné : il prédit par analogie avec des exemples étiquetés passés avec la requête (*in-context learning*), et l'ordre de grandeur de ses prédictions vient entièrement de ces exemples. Son contexte est donc **le jeu d'entraînement de CatBoost** (même split, aucun bâtiment de test), exporté par `train_final` dans `models/kumo_context.csv` et embarqué dans l'image. La comparaison des deux modèles sur le test est ainsi à armes égales.

Scores sur le test (`models/scores.json`, 310 bâtiments jamais vus) :

| Modèle | Énergie R² | MAE (kBtu) | MedAPE | Émissions R² | MAE (t CO2e) | MedAPE |
|---|---|---|---|---|---|---|
| CatBoost | 0,24 | 5,17 M | 35,0 % | 0,11 | 145,9 | 43,7 % |
| Kumo, contexte synthétique (avant #68) | −0,07 | 8,96 M | 83,1 % | −1 829 | 44 276 | 90 059 % |
| **Kumo, jeu d'entraînement (1 236 lignes)** | **0,45** | **4,71 M** | 35,1 % | **0,21** | **136,6** | 48,3 % |

Kumo fait mieux que CatBoost en R² et en MAE sur les deux cibles, donc sur les grands bâtiments qui pèsent le plus dans ces métriques. En erreur relative médiane (MedAPE), il fait jeu égal sur l'énergie et moins bien sur les émissions (48,3 % contre 43,7 %).

Latence par cible, sur CPU 4 threads : environ 25 s avec le contexte complet, 6 s avec `KUMO_CONTEXT_SIZE=300` (R² mesuré 0,49 en énergie, 0,23 en émissions) et 1,5 s avec 30 lignes ; environ 20 s sur 8 threads avec le contexte complet. Paralléliser les deux cibles n'apporte rien : PyTorch occupe déjà tous les cœurs. Sur une petite machine, réduire `KUMO_CONTEXT_SIZE` garde la comparaison sous le délai de l'interface (120 s). L'évaluation à l'entraînement utilise toujours le contexte complet, quelle que soit cette variable ; l'API lit le contexte une fois, au premier appel (redémarrer après un réentraînement).

L'ancien contexte synthétique fixait les émissions à 0,1 × l'énergie, contre environ 0,00002 t CO2e par kBtu à Seattle (≈ ×5 000) ; comme il sous-estimait aussi l'énergie par pi² (≈ ×0,25) et que Kumo reste proche des valeurs vues, les émissions prédites étaient en pratique environ 500 fois trop élevées.

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
