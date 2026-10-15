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
- `pyproject.toml` / `uv.lock` (dépendances gérées par uv, pas de `requirements.txt`)
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
- Configuration par variables d'environnement (`.env` en local, services Docker Compose `api` / `tools`) ; pas d'environnements GitHub dev/test/prod distincts
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

## 🚀 Quickstart

**Prérequis** : Git, Docker avec Compose v2, [uv](https://docs.astral.sh/uv/getting-started/installation/), `curl` (Linux, macOS ou WSL). Ports utilisés : `8080` (API) et `5432` (PostgreSQL). S'ils sont déjà pris, les changer **avant** de lancer le bloc, par exemple `export API_PORT=18080 DB_PORT=15432`.

Depuis un dossier vide, ces commandes clonent le projet, provisionnent la base, entraînent les modèles, lancent l'API puis la vérifient (jeton + prédiction). Elles sont rejouées **telles quelles** sur une machine vierge par le workflow `ci-install` (`scripts/quickstart_test.sh`) : si ce bloc casse, la CI échoue.

```bash
git clone https://github.com/WillIsback/OC-P5_Deployez_un_modele_de_Machine_Learning.git
cd OC-P5_Deployez_un_modele_de_Machine_Learning

# Configuration de démonstration (comptes johndoe/alice) : changer les mots de passe et SECRET_KEY hors démo
cp .example.env .env

# Données : CSV 2016 téléchargé depuis l'hôte (data/ est monté en lecture seule dans le service tools)
uv run python -c "from app.training.data_processing import ensure_dataset; ensure_dataset(download=True)"

# Base et ingestion (features et split inclus), puis API sur http://localhost:8080 avec le modèle livré
docker compose --profile tools build --pull   # images api + tools sur la dernière base :base (GHCR)
docker compose up -d --wait db
docker compose run --rm tools python -m app.db.create_db
docker compose run --rm tools python -m app.db.ingest --year 2016 --csv data/2016_Building_Energy_Benchmarking.csv
docker compose up -d --wait api

# Vérification : obtenir un jeton puis prédire la consommation d'un bâtiment
API=http://localhost:${API_PORT:-8080}
TOKEN=$(curl -fsS -X POST $API/token -d "username=johndoe&password=secret" | sed -E 's/.*"access_token":"([^"]+)".*/\1/')
curl -fsS -X POST $API/model/predict -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" -d '{"building_id": 1}'
```

**Le modèle entraîné est livré** dans `models/` (`energy.cbm`, `emissions.cbm`, scores dans `models/scores.json`) et enregistré comme version `baseline` par `create_db` : aucun entraînement n'est nécessaire pour servir l'API. Pour réentraîner, voir [`docs/training/README.md`](docs/training/README.md).

Documentation interactive : http://localhost:8080/docs. Arrêt : `docker compose down` (ajouter `-v` pour effacer la base).

---

## 🛠️ Développement local

```bash
# Installer les dépendances
uv sync

# Lancer l'application en mode développement (http://localhost:8000) : nécessite
# la base provisionnée par le Quickstart (modèles livrés dans models/)
uv run fastapi dev app/main.py

# Exécuter les tests (les tests PostgreSQL sont ignorés si aucune base n'est joignable)
uv run pytest --cov=app

# Linter
uv run ruff check .

# Formatter
uv run ruff format .

# Rejouer le Quickstart dans un dossier vide (comme la CI)
scripts/quickstart_test.sh
```

Les tests de base de données créent une base `p5_test` via l'URL administrateur `TEST_DATABASE_ADMIN_URL` (par défaut `postgres:$POSTGRES_PASSWORD@localhost:5432`, soit le service `db` de Docker Compose). Sans PostgreSQL joignable, ils sont **ignorés** (skip) ; avec `REQUIRE_TEST_DB=1` (utilisé en CI), ils **échouent** à la place.

---

## 🗄️ Base de données

L'API s'appuie sur **PostgreSQL** : dataset structuré (identité des bâtiments, features par année, cibles réelles), traçabilité de chaque appel API par utilisateur, prédictions versionnées et authentification via la table `users`. Schéma UML, choix techniques, rôles et requêtes d'exemple : voir [`docs/db/README.md`](docs/db/README.md) (DDL : [`docs/db/schema.sql`](docs/db/schema.sql)).

La base est provisionnée et alimentée par le [Quickstart](#-quickstart) (`create_db` puis `ingest` — nettoyage, features et split inclus).

Les comptes de démonstration `johndoe` / `alice` (mot de passe `secret`) ne sont créés par `create_db` que si `P5_SEED_DEMO_USERS=1` (valeur de `.example.env`, transmise au service `tools`) ou avec `python -m app.db.create_db --demo-users`. Seul `johndoe` est actif : `alice` est créée **inactive** et `POST /token` lui répond 400 (elle sert à tester le refus d'un compte désactivé). **En production, laisser `P5_SEED_DEMO_USERS` à 0 (ou absent)** et créer les utilisateurs réels directement dans la table `users`.

Le service `tools` (profil Compose, non démarré par `up`) est le seul à recevoir les identifiants administrateur et propriétaire ; le service `api` n'utilise que le rôle restreint `p5_api`. Les années 2017–2019 viennent de l'open data de Seattle et sont ramenées au schéma 2016 à l'ingestion. Comme pour 2016, le téléchargement doit se faire depuis l'hôte (`--download` ne peut pas écrire dans `./data` depuis le service `tools`), par exemple :

```bash
for y in 2017 2018 2019; do
  uv run python -c "from app.db.harmonize import download_open_data_year; download_open_data_year($y, 'data/${y}_Building_Energy_Benchmarking.csv')"
done
```

Ingestion, préparation et évaluation de ces années : voir [`docs/db/README.md`](docs/db/README.md) (section « Années de production 2017–2019 »).

### Variables d'environnement

| Variable | Rôle | Défaut |
|----------|------|--------|
| `SECRET_KEY` | Signature des jetons JWT | aucun (obligatoire) |
| `DATABASE_URL` | Connexion de l'API (rôle restreint `p5_api`) | aucun (obligatoire pour l'API) |
| `DATABASE_OWNER_URL` / `DATABASE_ADMIN_URL` | Rôle propriétaire (ingestion, préparation, entraînement, migrations) / administrateur (`create_db`) | aucun |
| `POSTGRES_PASSWORD`, `P5_OWNER_PASSWORD`, `P5_API_PASSWORD`, `P5_MLFLOW_PASSWORD` | Mots de passe des rôles, utilisés par Docker Compose et `create_db` | aucun |
| `MLFLOW_TRACKING_URI` / `MLFLOW_EXPERIMENT` | Suivi MLflow de l'entraînement | `sqlite:///mlflow.db` / `seattle-energy` |
| `TRAINING_YEAR` | Année d'entraînement (référence de l'ingestion et de l'harmonisation) | `2016` |
| `P5_SEED_DEMO_USERS` | `1` : `create_db` crée les comptes de démonstration | `0` (Compose) |
| `MODEL_PATH_ENERGY` / `MODEL_PATH_EMISSIONS` | Modèles CatBoost servis | `models/energy.cbm` / `models/emissions.cbm` |
| `MODEL_VERSION_PATH` / `MODEL_METRICS_PATH` | Version servie / table de scores de `GET /model/metrics` | `models/version.json` / `models/scores.json` |
| `API_PORT` / `DB_PORT` | Ports hôte des services `api` et `db` (Compose) | `8080` / `5432` |
| `UID` / `GID` | Utilisateur du service `tools` (écriture dans `./models` et `./mlruns`) | `1000` / `1000` |
| `TEST_DATABASE_ADMIN_URL` / `REQUIRE_TEST_DB` | Base des tests / `1` : échec au lieu de skip sans base | voir « Développement local » |

---

## 🔐 Authentification Bearer JWT

Toutes les routes du router `/model` sont protégées par un **Bearer token** (schéma `HTTPBearer`). Obtenez un token via `POST /token` (exemples sur le port **8080** de Docker Compose ; avec `uv run fastapi dev`, remplacer par `8000`) :

```bash
curl -X POST http://localhost:8080/token \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=johndoe&password=secret"
```

Puis utilisez-le sur les routes protégées :

```bash
curl http://localhost:8080/model/list -H "Authorization: Bearer <TOKEN>"
```

La clé `SECRET_KEY` est chargée depuis le fichier `.env` (voir `.gitignore`). Génération : `openssl rand -hex 32`. Elle est **obligatoire** : le code ne contient aucune clé par défaut, et créer ou vérifier un jeton sans `SECRET_KEY` lève une erreur explicite.

---

## ⚡ API de prédiction (CatBoost — Seattle)

La route `POST /model/predict` prédit, à partir d'un `building_id` présent en base (features calculées à l'ingestion), la consommation d'énergie (`SiteEnergyUse(kBtu)`) d'un bâtiment de Seattle à l'aide d'un `CatBoostRegressor`, en suivant le pipeline du projet de référence [OC-Ai-Engineer-P3](https://github.com/WillIsback/OC-Ai-Engineer-P3) (target transformée `log1p`, prédiction ramenée en unités réelles avec `expm1`).

**Retrouver un bâtiment avant de prédire.** `GET /buildings` cherche parmi les bâtiments **jamais vus par l'entraînement** (ni `train` ni `test`) : seuls ceux-là sont consultables et prédictibles par `building_id` (`/model/predict` et `/model/predict/compare` répondent 403 pour un bâtiment vu). Filtres : `q` (nom ou adresse), `year`, `neighborhood`, `building_type`, `limit` (100 au plus), `offset`. Aucune valeur réelle (consommation, émissions) n'est exposée.

```bash
curl "http://localhost:8080/buildings?q=needle&year=2018" -H "Authorization: Bearer <TOKEN>"
curl http://localhost:8080/buildings/1 -H "Authorization: Bearer <TOKEN>"   # identité et features par année
```

Exemple d'appel par identifiant de bâtiment (`data_year` optionnel : par défaut l'année la plus récente disponible) :

```bash
curl -X POST http://localhost:8080/model/predict \
  -H "Authorization: Bearer <TOKEN>" \
  -H "Content-Type: application/json" \
  -d '{"building_id": 1}'
```

La réponse inclut `prediction_id` et `request_id` (en-tête `X-Request-ID`) pour retrouver la trace en base. Codes d'erreur :

- **400** sur `POST /token` : identifiants incorrects ou compte inactif ;
- **401** sur `/model/*` : jeton absent, invalide ou expiré, ou utilisateur supprimé/désactivé depuis l'émission ;
- **403** : bâtiment déjà vu par l'entraînement (`train` ou `test`) ;
- **404** : bâtiment ou année inconnus ;
- **422** : bâtiment hors périmètre (ex. résidentiel), ou corps de requête invalide (champ inconnu refusé, `extra="forbid"`, ou valeur hors bornes, voir `app/schemas/api.py`) ;
- **503** : modèle indisponible (aucun modèle actif ou `.cbm` absent), base de données ou traçabilité indisponible (aucune prédiction n'est servie sans trace).

Autres routes protégées :

- `POST /model/predict/compare` : même entrée que `/model/predict` (`building_id`, `data_year`) ; renvoie `catboost_prediction` et `kumo_prediction` (Kumo-Tabular en zero-shot), chacune au format de `/model/predict`, mêmes codes d'erreur ;
- `GET /model/metrics` : table de scores du dernier entraînement (`models/scores.json`), par cible puis par modèle (`R2`, `MAE`, `MedAE`, `MedAPE_pct`) ; 404 si le fichier est absent.

#### Saisie libre — `POST /model/predict/features`

Pour un bâtiment absent de la base (simulation, test), envoyer directement les features à `POST /model/predict/features` :

```bash
curl -X POST http://localhost:8080/model/predict/features \
  -H "Authorization: Bearer <TOKEN>" \
  -H "Content-Type: application/json" \
  -d '{"BuildingType":"NonResidential","PrimaryPropertyType":"Small- and Mid-Sized Office","Neighborhood":"BALLARD","Latitude":47.62,"Longitude":-122.35,"YearBuilt":1990,"NumberofBuildings":1,"NumberofFloors":4,"PropertyGFAParking":5000,"PropertyGFABuilding":15000,"LargestPropertyUseType":"Office","SecondLargestPropertyUseType":"Retail Store","SecondLargestPropertyUseTypeGFA":3000,"ThirdLargestPropertyUseType":"Parking","ThirdLargestPropertyUseTypeGFA":2000,"Has_NaturalGas":true,"Has_Steam":false}'
```

### Trois exemples réels postérieurs à l'entraînement (DataYear > 2016)

Les exemples ci-dessous proviennent du jeu [Building Energy Benchmarking Data, 2015-Present](https://data.seattle.gov/Built-Environment/Building-Energy-Benchmarking-Data-2015-Present/teqw-tu6e), filtré sur `DataYear > 2016`. Ce champ sert à sélectionner les enregistrements et n'est pas une entrée du modèle.

Le jeu actuel n'a pas la taxonomie de 2016 sur laquelle le modèle est entraîné : les payloads ci-dessous appliquent les correspondances de `app/db/harmonize.py`, les mêmes que celles utilisées à l'ingestion des années 2017–2019 (détail : [`docs/db/README.md`](docs/db/README.md), « Harmonisation vers le schéma 2016 »).

| Colonne du jeu 2015-Present | Champ envoyé à l'API | Traitement |
| ----------------------------- | ---------------------- | ---------- |
| `EPAPropertyType` | `PrimaryPropertyType` | Table `EPA_TO_PRIMARY` (catégories non listées → `Other`) ; `Office` → `Large Office` si `PropertyGFATotal` ≥ 100 000 sf, sinon `Small- and Mid-Sized Office`. |
| `BuildingType` | `BuildingType` | Valeur 2016 du bâtiment si elle existe ; sinon `BUILDING_TYPE_FALLBACK` (`Hospital` / `University` → `NonResidential`, `School` → `SPS-District K-12`). |
| `Largest` / `Second` / `ThirdLargestPropertyUseType` | idem | Libellés renommés depuis 2016 ramenés à leur forme d'origine (`USE_TYPE_LABELS`). |
| `PropertyGFABuildings` | `PropertyGFABuilding` | L'API renomme ensuite ce champ en `PropertyGFABuilding(s)` pour le modèle. |
| `SecondLargestPropertyUseTypeGFA` (identifiant Socrata : `secondlargestpropertyuse`) | `SecondLargestPropertyUseTypeGFA` | Surface en pieds carrés. |
| `NaturalGas(kBtu)` | `Has_NaturalGas` | `true` si la consommation est strictement positive, sinon `false`. |
| `SteamUse(kBtu)` | `Has_Steam` | `true` si la consommation est strictement positive, sinon `false`. |

Les champs de surface d'usage absents dans la source sont ramenés à `0`; la valeur catégorielle source `NA` est conservée telle quelle. Cette harmonisation reste une approximation : les correspondances ont été établies empiriquement et les écarts résiduels entre millésimes peuvent limiter la qualité des prédictions (voir l'évaluation projetée dans [`docs/db/README.md`](docs/db/README.md)).

Chaque objet JSON ci-dessous est à envoyer séparément à `POST /model/predict/features` (saisie libre).

#### 1. Hôpital — DataYear 2025

Source : `BuildingType` `Hospital` (bâtiment de 2021, sans valeur 2016) → `NonResidential` ; `EPAPropertyType` `Other/Specialty Hospital`, absent de `EPA_TO_PRIMARY` → `Other`.

```json
{
  "BuildingType": "NonResidential",
  "PrimaryPropertyType": "Other",
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

Source : `EPAPropertyType` `Office` ; `PropertyGFATotal` (au moins les 221 508 sf bâtis) ≥ 100 000 sf → `Large Office`.

```json
{
  "BuildingType": "NonResidential",
  "PrimaryPropertyType": "Large Office",
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

Réentraîner le modèle (pipeline multi-cible CatBoost + Kumo, suivi MLflow, tests) : voir [`docs/training/README.md`](docs/training/README.md).

---

## 📁 Structure du dépôt

```
.github/
├── dependabot.yml              # Mise à jour automatique des dépendances
├── ISSUE_TEMPLATE/              # Templates d'issues (5 types + config)
├── PULL_REQUEST_TEMPLATE.md     # Template de PR
├── security-exceptions.yml     # Exceptions de sécurité
└── workflows/                   # Workflows CI/CD
    ├── ai-code-review.yml        # Revue de code IA des PR (non bloquante)
    ├── ai-issue-triage.yml       # Triage IA des issues
    ├── base-image.yml            # Publication de l'image de base `:base` (GHCR)
    ├── ci-code-quality.yml       # Qualité du code (lint, format, actionlint)
    ├── ci-model-performance.yml  # Gate de non-régression des scores du modèle
    ├── ci-security.yml           # Sécurité (SCA, SAST, secrets, IaC)
    ├── ci-test.yml               # Tests unitaires + couverture
    ├── ci-traceability.yml       # Traçabilité issues/PR
    └── release.yml               # Release automatisée (CD)
app/                              # Code source (API FastAPI, base, entraînement)
docs/
├── ci-cd/README.md               # Documentation du pipeline CI/CD
├── training/README.md            # Réentraînement du modèle, MLflow
├── db/
│   ├── README.md                 # Base PostgreSQL : schéma, choix, rôles, requêtes
│   └── schema.sql                # DDL généré par Alembic
├── diagrams/
│   ├── workflow.d2               # Source D2 du diagramme
│   └── workflow.svg              # SVG généré
└── policies/
    ├── semver.md                 # Politique de versionnement sémantique
    └── security-gates.md         # Politique des gates de sécurité
models/                           # Modèle entraîné livré (energy.cbm, emissions.cbm, scores.json) + scores_baseline.json
tests/                            # Tests pytest (unitaires, API, base PostgreSQL)
.example.env                      # Modèle de configuration à copier en .env
alembic.ini                       # Configuration des migrations (app/db/migrations)
docker-compose.yml                # Services db, api et tools (profil)
Dockerfile                        # Image de l'API (construite sur l'image :base)
Dockerfile.base                   # Image de base (dépendances précompilées)
pyproject.toml / uv.lock          # Dépendances (uv)
CONTRIBUTING.md                   # Guide de contribution
RELEASE.md                        # Runbook de release
```

---

## 📚 Documentation

| Document | Description |
|----------|-------------|
| [Pipeline CI/CD](docs/ci-cd/README.md) | Diagramme du flux, workflows CI/IA/CD, sécurité du pipeline |
| [Base de données](docs/db/README.md) | Schéma UML, choix techniques, rôles, mise en route, requêtes SQL |
| [Entraînement](docs/training/README.md) | Réentraînement CatBoost multi-cible, Kumo, suivi MLflow, tests |
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
3. Gates CD bloquantes (cohérence de version + scan container, précédé d'un smoke test d'import de l'image dans `gate-container-scan`)
4. Création GitHub Release + tag `vX.Y.Z`
5. Publication image Docker sur **GHCR** avec attestations SBOM
6. Sérialisation stricte : pas de releases en parallèle

L'image applicative est construite sur l'image `:base` (dépendances précompilées) publiée par `base-image.yml` à chaque modification de `pyproject.toml`, `uv.lock` ou `Dockerfile.base` sur `main` : si cette image est obsolète, le smoke test bloque la release et il faut relancer `base-image` manuellement (`workflow_dispatch`).

## 📄 Licence

MIT
