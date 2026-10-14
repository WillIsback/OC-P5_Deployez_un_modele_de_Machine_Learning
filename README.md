# P5 — Déployez un modèle de Machine Learning

**Auteur** : William Derue
**Formation** : [AI Engineer](https://openclassrooms.com/fr/paths/1011-ai-engineer) — OpenClassrooms
**Projet** : 5 — Déployez un modèle de Machine Learning
**Date** : 2026

---

## 🏢 Contexte — Scénario de mission

Vous êtes **freelance spécialisé en machine learning** et vous venez de recevoir une demande de la part de votre client **Futurisys**, une entreprise innovante qui souhaite rendre ses modèles de machine learning opérationnels et accessibles via une API performante.

Le directeur technique de Futurisys, **Aurélien**, vous formule la demande suivante :

> *"Nous avons besoin que vous déployiez notre modèle de machine learning en production. Pour cela, vous allez :*
> 1. *Créer une API avec FastAPI pour exposer le modèle ;*
> 2. *Écrire des tests unitaires avec Pytest pour garantir sa fiabilité ;*
> 3. *Gérer la version du code avec Git pour une collaboration fluide."*

L'objectif est de **rendre le modèle utilisable en production** tout en respectant les meilleures pratiques de l'ingénierie logicielle.

---

## 📦 Livrables

### 1. Dépôt Git structuré

- Code source complet
- `requirements.txt` / `uv.lock` / `pyproject.toml`
- Historique de commits clair (branches, tags, Conventional Commits)
- README complet

### 2. API de machine learning

- Développée avec **FastAPI**
- Expose le modèle de ML via des endpoints REST
- Documentation intégrée (Swagger / OpenAPI)
- Endpoints, schémas de données, exemples d'appels

### 3. Tests unitaires & fonctionnels

- **Pytest** — couverture des cas critiques et scénarios d'erreur
- Rapport de couverture (`pytest-cov`)
- Tests d'intégration de l'API

### 4. Base de données PostgreSQL

- Script SQL / Python pour la création de la base et des tables
- Modèle de données documenté
- Exemples d'entrées (inputs / outputs du modèle ML)
- Scripts d'interrogation et d'interaction avec le modèle

### 5. Pipeline CI/CD

- Configuration complète dans `.github/workflows/`
- Gestion des environnements (dev, test, prod)
- Intégration des secrets
- Rulesets GitHub (branches + tags)

---

## 🏗️ Stack technique

| Composant | Technologie |
|-----------|-------------|
| **Runtime** | Python 3.12+ |
| **Framework API** | FastAPI |
| **Gestionnaire de paquets** | [uv](https://github.com/astral-sh/uv) |
| **Base de données** | PostgreSQL |
| **Linter / Formateur** | ruff |
| **Tests** | pytest + coverage |
| **Container** | Docker |
| **Scan de sécurité** | Trivy, CodeQL, Gitleaks |
| **CI/CD** | GitHub Actions |
| **Diagramme** | [D2](https://d2lang.com/) |

---

## 🚀 Démarrage rapide

```bash
# Cloner le dépôt
git clone https://github.com/<org>/P5_Deployez_un_modele_de_Machine_Learning.git
cd P5_Deployez_un_modele_de_Machine_Learning

# Installer les dépendances
uv sync

# Lancer l'application
uv run fastapi dev app/main.py

# Exécuter les tests
uv run pytest --cov=app

# Linter
uv run ruff check .

# Formatter
uv run ruff format .
```

---

## 🗄️ Base de données

L'API s'appuie sur **PostgreSQL** : dataset structuré (brut puis features préparées), traçabilité de chaque appel API par utilisateur, prédictions versionnées et authentification via la table `users`. Schéma UML, choix techniques, rôles et requêtes d'exemple : voir [`docs/db/README.md`](docs/db/README.md) (DDL : [`docs/db/schema.sql`](docs/db/schema.sql)).

Démarrage avec Docker Compose :

```bash
cp .example.env .env                 # puis remplacer les valeurs change-me* et SECRET_KEY
docker compose up -d db
docker compose run --rm tools python -m app.db.create_db
docker compose run --rm tools python -m app.db.ingest --year 2016 --csv data/2016_Building_Energy_Benchmarking.csv
docker compose run --rm tools python -m app.db.prepare --year 2016
docker compose up -d api             # API sur http://localhost:8080
```

Les comptes de démonstration `johndoe` / `alice` (mot de passe `secret`) ne sont créés par `create_db` que si `P5_SEED_DEMO_USERS=1` (valeur de `.example.env`, transmise au service `tools`) ou avec `python -m app.db.create_db --demo-users`. **En production, laisser `P5_SEED_DEMO_USERS` à 0 (ou absent)** et créer les utilisateurs réels directement dans la table `users`.

Le service `tools` (profil Compose, non démarré par `up`) est le seul à recevoir les identifiants administrateur et propriétaire ; le service `api` n'utilise que le rôle restreint `p5_api`. Les CSV 2017–2019 doivent être déposés dans `data/` et `YEAR_COLUMN_RENAMES` complété dans `app/db/ingest.py` avant ingestion (voir `docs/db/README.md`).

---

## 🔐 Authentification Bearer JWT

Toutes les routes du router `/model` sont protégées par un **Bearer token** (schéma `HTTPBearer`). Obtenez un token via `POST /token` :

```bash
curl -X POST http://localhost:8000/token \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=johndoe&password=secret"
```

Puis utilisez-le sur les routes protégées :

```bash
curl http://localhost:8000/model/list -H "Authorization: Bearer <TOKEN>"
```

La clé `SECRET_KEY` est chargée depuis le fichier `.env` (voir `.gitignore`). Génération : `openssl rand -hex 32`. Elle est **obligatoire** : le code ne contient aucune clé par défaut, et créer ou vérifier un jeton sans `SECRET_KEY` lève une erreur explicite.

---

## ⚡ API de prédiction (CatBoost — Seattle)

La route `POST /model/predict` prédit, à partir d'un `building_id` présent en base (features préparées par `app.db.prepare`), la consommation d'énergie (`SiteEnergyUse(kBtu)`) d'un bâtiment de Seattle à l'aide d'un `CatBoostRegressor`, en suivant le pipeline du projet de référence [OC-Ai-Engineer-P3](https://github.com/WillIsback/OC-Ai-Engineer-P3) (target transformée `log1p`, prédiction ramenée en unités réelles avec `expm1`).

Exemple d'appel par identifiant de bâtiment (`data_year` optionnel : par défaut l'année la plus récente disponible) :

```bash
curl -X POST http://localhost:8080/model/predict \
  -H "Authorization: Bearer <TOKEN>" \
  -H "Content-Type: application/json" \
  -d '{"building_id": 1}'
```

La réponse inclut `prediction_id` et `request_id` (en-tête `X-Request-ID`) pour retrouver la trace en base. Codes d'erreur : 404 (bâtiment ou année inconnus), 422 (hors périmètre, ex. résidentiel), 503 (modèle indisponible).

#### Saisie libre — `POST /model/predict/features`

Pour un bâtiment absent de la base (simulation, test), envoyer directement les features à `POST /model/predict/features` :

```bash
curl -X POST http://localhost:8080/model/predict/features \
  -H "Authorization: Bearer <TOKEN>" \
  -H "Content-Type: application/json" \
  -d '{"BuildingType":"Commercial","PrimaryPropertyType":"Office","Neighborhood":"Ballard","Latitude":47.62,"Longitude":-122.35,"YearBuilt":1990,"NumberofBuildings":1,"NumberofFloors":4,"PropertyGFAParking":5000,"PropertyGFABuilding":15000,"LargestPropertyUseType":"Office","SecondLargestPropertyUseType":"Retail","SecondLargestPropertyUseTypeGFA":3000,"ThirdLargestPropertyUseType":"Parking","ThirdLargestPropertyUseTypeGFA":2000,"Has_NaturalGas":true,"Has_Steam":false}'
```

### Trois exemples réels postérieurs à l'entraînement (DataYear > 2016)

Les exemples ci-dessous proviennent du jeu [Building Energy Benchmarking Data, 2015-Present](https://data.seattle.gov/Built-Environment/Building-Energy-Benchmarking-Data-2015-Present/teqw-tu6e), filtré sur `DataYear > 2016`. Ce champ sert à sélectionner les enregistrements et n'est pas une entrée du modèle.

Attention aux correspondances entre le jeu actuel et le schéma historique du modèle :

| Colonne du jeu 2015-Present | Champ envoyé à l'API | Traitement |
| ----------------------------- | ---------------------- | ---------- |
| `EPAPropertyType` | `PrimaryPropertyType` | Approximation : le jeu actuel ne fournit plus `PrimaryPropertyType`. Les catégories ne sont pas nécessairement équivalentes à celles vues à l'entraînement. |
| `PropertyGFABuildings` | `PropertyGFABuilding` | L'API renomme ensuite ce champ en `PropertyGFABuilding(s)` pour le modèle. |
| `SecondLargestPropertyUseTypeGFA` (identifiant Socrata : `secondlargestpropertyuse`) | `SecondLargestPropertyUseTypeGFA` | Surface en pieds carrés. |
| `NaturalGas(kBtu)` | `Has_NaturalGas` | `true` si la consommation est strictement positive, sinon `false`. |
| `SteamUse(kBtu)` | `Has_Steam` | `true` si la consommation est strictement positive, sinon `false`. |

Les champs de surface d'usage absents dans la source sont ramenés à `0`; la valeur catégorielle source `NA` est conservée telle quelle. Ces payloads illustrent le mapping et l'appel à l'API, mais les écarts de taxonomie entre les deux millésimes peuvent limiter la qualité des prédictions.

Chaque objet JSON ci-dessous est à envoyer séparément à `POST /model/predict/features` (saisie libre).

#### 1. Hôpital — DataYear 2025

```json
{
  "BuildingType": "Hospital",
  "PrimaryPropertyType": "Other/Specialty Hospital",
  "Neighborhood": "LAKE UNION",
  "Latitude": 47.626602695626,
  "Longitude": -122.33047891939,
  "YearBuilt": 2021,
  "NumberofBuildings": 1,
  "NumberofFloors": 5,
  "PropertyGFAParking": 66459,
  "PropertyGFABuilding": 131797,
  "LargestPropertyUseType": "Other/Specialty Hospital",
  "SecondLargestPropertyUseType": "Parking",
  "SecondLargestPropertyUseTypeGFA": 0,
  "ThirdLargestPropertyUseType": "NA",
  "ThirdLargestPropertyUseTypeGFA": 0,
  "Has_NaturalGas": true,
  "Has_Steam": false
}
```

#### 2. Bâtiment à usage mixte — DataYear 2025

```json
{
  "BuildingType": "NonResidential",
  "PrimaryPropertyType": "Mixed Use Property",
  "Neighborhood": "LAKE UNION",
  "Latitude": 47.653912401735,
  "Longitude": -122.32544330281,
  "YearBuilt": 2022,
  "NumberofBuildings": 1,
  "NumberofFloors": 5,
  "PropertyGFAParking": 77291,
  "PropertyGFABuilding": 216859,
  "LargestPropertyUseType": "Office",
  "SecondLargestPropertyUseType": "Other",
  "SecondLargestPropertyUseTypeGFA": 79578,
  "ThirdLargestPropertyUseType": "Non-Refrigerated Warehouse",
  "ThirdLargestPropertyUseTypeGFA": 24058,
  "Has_NaturalGas": false,
  "Has_Steam": false
}
```

#### 3. Bureau — DataYear 2025

```json
{
  "BuildingType": "NonResidential",
  "PrimaryPropertyType": "Office",
  "Neighborhood": "DOWNTOWN",
  "Latitude": 47.605422444475,
  "Longitude": -122.33588476937,
  "YearBuilt": 1950,
  "NumberofBuildings": 1,
  "NumberofFloors": 11,
  "PropertyGFAParking": 10537,
  "PropertyGFABuilding": 221508,
  "LargestPropertyUseType": "Office",
  "SecondLargestPropertyUseType": "Parking",
  "SecondLargestPropertyUseTypeGFA": 26054,
  "ThirdLargestPropertyUseType": "NA",
  "ThirdLargestPropertyUseTypeGFA": 0,
  "Has_NaturalGas": false,
  "Has_Steam": false
}
```

Les modèles sont chargés depuis `models/energy.cbm` et `models/emissions.cbm` (chemins surchargeables par `MODEL_PATH_ENERGY` / `MODEL_PATH_EMISSIONS`).

**Entraînement réel (pipeline multi-cible + MLflow)** :

```bash
# 1. Ingérer puis préparer l'année d'entraînement dans PostgreSQL
#    (le CSV 2016 doit être présent dans data/ ; --download le récupère s'il est absent,
#    mais uniquement en local avec `uv run` : dans le service tools, ./data est monté en lecture seule)
uv run python -m app.db.ingest --year 2016 --csv data/2016_Building_Energy_Benchmarking.csv [--download]
uv run python -m app.db.prepare --year 2016

# 2. Entraîner depuis la base (rôle propriétaire : DATABASE_OWNER_URL)
uv run python -m app.training
```

L'entraînement lit désormais les features et cibles dans PostgreSQL (`building_features` et `building_actuals`), et non plus le CSV. Le pipeline entraîne un CatBoost par cible (`SiteEnergyUse(kBtu)` et
`TotalGHGEmissions`), évalue Kumo-Tabular en zero-shot sur le même test et
logue les runs MLflow (`uv run mlflow ui`). Sorties : `models/<cible>.cbm` et
`models/scores.json`.

### Suivi d'expérimentation avec MLflow

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
Puis visualiser : `uv run mlflow ui`.

### Tests unitaires du training

```bash
uv run pytest tests/test_training.py -q        # pipeline, CV, tune, MLflow
uv run pytest --cov=app tests/                 # ensemble des tests
```

---

## 📁 Structure du dépôt

```
.github/
├── dependabot.yml              # Mise à jour automatique des dépendances
├── ISSUE_TEMPLATE/              # Templates d'issues (5 types + config)
├── PULL_REQUEST_TEMPLATE.md     # Template de PR
├── security-exceptions.yml     # Exceptions de sécurité
└── workflows/                   # Workflows CI/CD
    ├── ci-code-quality.yml       # Qualité du code (lint, format, actionlint)
    ├── ci-security.yml           # Sécurité (SCA, SAST, secrets, IaC)
    ├── ci-test.yml               # Tests unitaires + couverture
    ├── ci-traceability.yml       # Traçabilité issues/PR
    └── release.yml               # Release automatisée (CD)
app/                              # Code source de l'application FastAPI
docs/
├── ci-cd/README.md               # Documentation du pipeline CI/CD
├── db/
│   ├── README.md                 # Base PostgreSQL : schéma, choix, rôles, requêtes
│   └── schema.sql                # DDL généré par Alembic
├── diagrams/
│   ├── workflow.d2               # Source D2 du diagramme
│   └── workflow.svg              # SVG généré
└── policies/
    ├── semver.md                 # Politique de versionnement sémantique
    └── security-gates.md         # Politique des gates de sécurité
CONTRIBUTING.md                   # Guide de contribution
RELEASE.md                        # Runbook de release
```

---

## 📚 Documentation

| Document | Description |
|----------|-------------|
| [Pipeline CI/CD](docs/ci-cd/README.md) | Diagramme du flux, workflows, rulesets, sécurité du pipeline |
| [Base de données](docs/db/README.md) | Schéma UML, choix techniques, rôles, mise en route, requêtes SQL |
| [Guide de contribution](CONTRIBUTING.md) | Cycle Issue → Branche → PR, conventions |
| [Runbook Release](RELEASE.md) | Semver, gates CD, rollback, incidents |
| [Politique semver](docs/policies/semver.md) | Règle du max, comportement v0.x |
| [Politique sécurité](docs/policies/security-gates.md) | Seuils SCA/SAST/secrets, exceptions |

---

## 🔒 Sécurité

- Analyse **SAST** (CodeQL) sur chaque PR
- Scan des dépendances (**Trivy + Dependency Review**)
- Détection de secrets (**Gitleaks**)
- Scan des containers avant publication (**Trivy**)
- Protection des branches (push direct interdit)
- Protection des tags (immuables)
- Permissions minimales des workflows

## 📦 Release

Les releases sont entièrement automatisées via le workflow `release.yml` :

1. Merge dans `main` → déclenchement du workflow
2. Calcul de version (Semver automatique, max des bumps)
3. Gates CD bloquantes (cohérence de version + scan container)
4. Création GitHub Release + tag `vX.Y.Z`
5. Publication image Docker sur **GHCR** avec attestations SBOM
6. Sérialisation stricte : pas de releases en parallèle

## 📄 Licence

MIT
