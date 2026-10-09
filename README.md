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

La clé `SECRET_KEY` est chargée depuis le fichier `.env` (voir `.gitignore`). Génération : `openssl rand -hex 32`.

---

## ⚡ API de prédiction (CatBoost — Seattle)

La route `POST /model/predict` prédit la consommation d'énergie (`SiteEnergyUse(kBtu)`) d'un bâtiment de Seattle à l'aide d'un `CatBoostRegressor`, en suivant le pipeline du projet de référence [OC-Ai-Engineer-P3](https://github.com/WillIsback/OC-Ai-Engineer-P3) (target transformée `log1p`, prédiction ramenée en unités réelles avec `expm1`).

Exemple d'appel :

```bash
curl -X POST http://localhost:8000/model/predict \
  -H "Authorization: Bearer <TOKEN>" \
  -H "Content-Type: application/json" \
  -d '{"BuildingType":"Commercial","PrimaryPropertyType":"Office","Neighborhood":"Ballard","Latitude":47.62,"Longitude":-122.35,"YearBuilt":1990,"NumberofBuildings":1,"NumberofFloors":4,"PropertyGFAParking":5000,"PropertyGFABuilding":15000,"LargestPropertyUseType":"Office","SecondLargestPropertyUseType":"Retail","SecondLargestPropertyUseTypeGFA":3000,"ThirdLargestPropertyUseType":"Parking","ThirdLargestPropertyUseTypeGFA":2000,"Has_NaturalGas":true,"Has_Steam":false}'
```

Le modèle est chargé depuis `models/energy_use_catboost.cbm` (chemin surchargeable par `MODEL_PATH`).

**Entraînement réel (pipeline P3 + anti-over-fitting + fine-tune restreint)** :

```bash
uv run python scripts/train_model_seattle.py chemin/vers/2016_Building_Energy_Benchmarking.csv \
    --output models/energy_use_catboost.cbm
```

Ce script réplique fidèlement les filtres `F0`→`F11` du notebook, la transformation `log1p`, les marqueurs de raccordement, puis : découpe train / validation / test, parcourt une grille **restreinte** d'hyper-paramètres avec early stopping et `use_best_model`, pénalise l'écart train/validation (anti over-fitting), ré-entraîne final sur l'entraînement et évalue sur le test en unités réelles (kBtu/an).

**Modèle de démonstration (données synthétiques)** :

```bash
uv run python scripts/train_model.py
```

Ce script entraîne un bouchon sur **données synthétiques** pour valider l'API de bout en bout. Utilisez le vrai dataset avec `train_model_seattle.py` pour produire votre modèle de production.

### Suivi d'expérimentation avec MLflow

L'entraînement (`train_model_seattle.py`) journalise automatiquement chaque run dans **MLflow** :
- **Hyper-paramètres** retenus + métadonnées (target, nb features, split).
- **Scores CV sur le jeu d'entraînement** : moyenne, écart-type et valeurs par pli (`cv_train_*`, `cv_train_std_*`, `cv_fold*_*`).
- **Évaluation sur le test** : `test_R2`, `test_MAE`, `test_MedAE`, `test_MedAPE_pct`.
- **Artefact** du modèle `.cbm`.

Configurable par variables d'environnement :
```bash
export MLFLOW_TRACKING_URI="sqlite:///mlflow.db"   # défaut
export MLFLOW_EXPERIMENT="seattle-energy"           # défaut
uv run python scripts/train_model_seattle.py chemin/vers/2016_Building_Energy_Benchmarking.csv
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
├── rulesets/                    # Rulesets GitHub (branches + tags)
├── security-exceptions.yml     # Exceptions de sécurité
└── workflows/                   # Workflows CI/CD
    ├── apply-rulesets.yml        # Application idempotente des rulesets
    ├── ci-code-quality.yml       # Qualité du code (lint, format, actionlint)
    ├── ci-security.yml           # Sécurité (SCA, SAST, secrets, IaC)
    ├── ci-test.yml               # Tests unitaires + couverture
    ├── ci-traceability.yml       # Traçabilité issues/PR
    └── release.yml               # Release automatisée (CD)
app/                              # Code source de l'application FastAPI
docs/
├── ci-cd/README.md               # Documentation du pipeline CI/CD
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
