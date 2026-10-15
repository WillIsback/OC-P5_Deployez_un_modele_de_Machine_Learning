# P5 — Déployez un modèle de Machine Learning

[![ci-install](https://github.com/WillIsback/OC-P5_Deployez_un_modele_de_Machine_Learning/actions/workflows/ci-install.yml/badge.svg?branch=main)](https://github.com/WillIsback/OC-P5_Deployez_un_modele_de_Machine_Learning/actions/workflows/ci-install.yml)
[![Release](https://img.shields.io/github/v/release/WillIsback/OC-P5_Deployez_un_modele_de_Machine_Learning?sort=semver)](https://github.com/WillIsback/OC-P5_Deployez_un_modele_de_Machine_Learning/releases)
[![Licence MIT](https://img.shields.io/github/license/WillIsback/OC-P5_Deployez_un_modele_de_Machine_Learning)](LICENSE)

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

## 🏗️ Stack technique

| Domaine | Technologies |
|---------|--------------|
| **API** | Python 3.12+, [FastAPI](https://fastapi.tiangolo.com/) (Swagger / OpenAPI), Pydantic |
| **Authentification** | JWT Bearer ([PyJWT](https://pyjwt.readthedocs.io/)), mots de passe hachés Argon2 ([pwdlib](https://github.com/frankie567/pwdlib)) |
| **Modèle** | [CatBoost](https://catboost.ai/) multi-cible (énergie, émissions), scikit-learn, pandas ; comparaison zero-shot Kumo-Tabular ([structured-data-models](https://github.com/NVIDIA/structured-data-models), PyTorch CPU) |
| **Suivi des expériences** | [MLflow](https://mlflow.org/) (métadonnées dans PostgreSQL) |
| **Base de données** | PostgreSQL 17, SQLAlchemy 2, Alembic (migrations), psycopg 3 |
| **Conteneurs** | Docker, Docker Compose, image publiée sur GHCR (modèle embarqué) |
| **Qualité & tests** | [uv](https://github.com/astral-sh/uv), ruff, pytest + pytest-cov, diff-cover, SonarCloud |
| **CI/CD** | GitHub Actions, release semver automatique, revue de code IA |
| **Sécurité** | CodeQL, Trivy, Gitleaks, Dependency Review, hadolint, actionlint, zizmor |
| **Documentation** | Markdown, diagrammes [D2](https://d2lang.com/) |

---

## 🚀 Quickstart

Les deux parcours installent la base PostgreSQL, ingèrent les jeux 2016 (entraînement) et 2019 (bâtiments jamais vus, open data de Seattle).

**Prérequis communs** : Docker avec Compose v2 et `curl` (Linux, macOS ou WSL). Ports `8080` (API) et `5432` (PostgreSQL) : s'ils sont pris, préfixer la commande, par exemple `API_PORT=18080 DB_PORT=15432 …`.

### 🐳 Utilisateurs — image Docker

Aucun clone : l'image publiée sur GHCR est tirée, et le dossier `p5-energy/` reçoit `docker-compose.yml` et un `.env` aux secrets **générés aléatoirement**.

```bash
curl -fsSL https://raw.githubusercontent.com/WillIsback/OC-P5_Deployez_un_modele_de_Machine_Learning/main/scripts/quickstart.sh | bash
```

Épingler une version : `… | P5_IMAGE=ghcr.io/willisback/oc-p5_deployez_un_modele_de_machine_learning:v1.3.2 bash`. Image `linux/amd64` (émulée sur Apple Silicon). Arrêt : `cd p5-energy && docker compose down` (ajouter `-v` pour effacer la base).

### 🧑‍💻 Développeurs — code source

Prérequis supplémentaires : Git, et [uv](https://docs.astral.sh/uv/getting-started/installation/) pour le développement local (voir plus bas). L'image est construite depuis les sources (`docker-compose.override.yml`, qui monte aussi `./models`) et `.env` est copié depuis `.example.env` (secrets de démonstration : à changer hors démo).

```bash
git clone https://github.com/WillIsback/OC-P5_Deployez_un_modele_de_Machine_Learning.git && cd OC-P5_Deployez_un_modele_de_Machine_Learning && scripts/quickstart.sh --source
```

Le détail des étapes (une commande `docker compose` chacune) est dans [`scripts/quickstart.sh`](scripts/quickstart.sh) et dans [`docs/db/README.md`](docs/db/README.md#4-mise-en-route).

### Exemple : 3 bâtiments, 3 prédictions

Une fois l'API lancée ([`jq`](https://jqlang.org/) pour lire les réponses) :

```bash
API=http://localhost:8080
TOKEN=$(curl -fsS -X POST $API/token -d "username=johndoe&password=secret" | jq -r .access_token)

# 3 bâtiments jamais vus par l'entraînement (les seuls prédictibles par identifiant)…
IDS=$(curl -fsS "$API/buildings?limit=3" -H "Authorization: Bearer $TOKEN" | jq '.items[].building_id')

# … puis la prédiction de chacun (consommation en kBtu/an, émissions en t CO2e/an)
for id in $IDS; do
  curl -fsS -X POST $API/model/predict -H "Authorization: Bearer $TOKEN" \
    -H "Content-Type: application/json" -d "{\"building_id\": $id}" \
    | jq -c "{building_id: $id, energy_use_kbtu, ghg_emissions_tco2e}"
done
```

```text
{"building_id":28,"energy_use_kbtu":3088219.81,"ghg_emissions_tco2e":99.24}
{"building_id":34,"energy_use_kbtu":7466845.71,"ghg_emissions_tco2e":159.23}
{"building_id":36,"energy_use_kbtu":8614361.36,"ghg_emissions_tco2e":175.49}
```

Toutes les routes, la saisie libre des features et les codes d'erreur : [`docs/api/README.md`](docs/api/README.md). Jetons, comptes et `SECRET_KEY` : [`docs/api/authentication.md`](docs/api/authentication.md). Documentation interactive : http://localhost:8080/docs.

---

## 🛠️ Développement local

```bash
# Installer les dépendances
uv sync

# Lancer l'application en mode développement (http://localhost:8000) : nécessite
# la base provisionnée par le Quickstart développeur (modèles livrés dans models/)
uv run fastapi dev app/main.py

# Exécuter les tests (les tests PostgreSQL sont ignorés si aucune base n'est joignable)
uv run pytest --cov=app

# Linter
uv run ruff check .

# Formatter
uv run ruff format .

# Rejouer un parcours du Quickstart dans un dossier vide (comme la CI)
scripts/quickstart_test.sh dev    # ou : user
```

Les tests de base de données créent une base `p5_test` via l'URL administrateur `TEST_DATABASE_ADMIN_URL` (par défaut `postgres:$POSTGRES_PASSWORD@localhost:5432`, soit le service `db` de Docker Compose). Sans PostgreSQL joignable, ils sont **ignorés** (skip) ; avec `REQUIRE_TEST_DB=1` (utilisé en CI), ils **échouent** à la place.

---

## 🗄️ Base de données

L'API s'appuie sur **PostgreSQL** : dataset structuré (identité des bâtiments, features par année, cibles réelles), traçabilité de chaque appel API par utilisateur, prédictions versionnées et authentification via la table `users`. Schéma UML, choix techniques, rôles et requêtes d'exemple : voir [`docs/db/README.md`](docs/db/README.md) (DDL : [`docs/db/schema.sql`](docs/db/schema.sql)).

La base est provisionnée et alimentée par le [Quickstart](#-quickstart) (`create_db` puis `ingest` — nettoyage, features et split inclus).

Les comptes de démonstration `johndoe` / `alice` (mot de passe `secret`) ne sont créés que si `P5_SEED_DEMO_USERS=1` : **jamais en production**, voir [`docs/api/authentication.md`](docs/api/authentication.md#comptes).

Le service `tools` (profil Compose, non démarré par `up`) est le seul à recevoir les identifiants administrateur et propriétaire ; le service `api` n'utilise que le rôle restreint `p5_api`. Les années 2017–2019 viennent de l'open data de Seattle et sont ramenées au schéma 2016 à l'ingestion. `./data` étant monté en lecture-écriture dans `tools`, ces CSV peuvent être téléchargés directement dans le conteneur (`--download`) ; depuis l'hôte, par exemple :

```bash
for y in 2017 2018 2019; do
  uv run python -c "from app.db.harmonize import download_open_data_year; download_open_data_year($y, 'data/${y}_Building_Energy_Benchmarking.csv')"
done
```

Ingestion, préparation et évaluation de ces années : voir [`docs/db/README.md`](docs/db/README.md) (section « Années de production 2017–2019 »).

### Variables d'environnement

Lues depuis `.env` (copié de [`.example.env`](.example.env), ou généré par le Quickstart utilisateurs). Seules celles marquées ⚠️ sont obligatoires.

**Secrets et connexions**

| Variable | Rôle | Défaut |
|----------|------|--------|
| `SECRET_KEY` ⚠️ | Signature des jetons JWT | — |
| `DATABASE_URL` | Connexion de l'API (rôle restreint `p5_api`) ; obligatoire hors Compose | — |
| `DATABASE_OWNER_URL` | Rôle propriétaire : ingestion, entraînement, migrations | — |
| `DATABASE_ADMIN_URL` | Rôle administrateur : `create_db` | — |
| `POSTGRES_PASSWORD` ⚠️ | Mot de passe de `postgres` | — |
| `P5_OWNER_PASSWORD` ⚠️ | Mot de passe de `p5_owner` | — |
| `P5_API_PASSWORD` ⚠️ | Mot de passe de `p5_api` | — |
| `P5_MLFLOW_PASSWORD` ⚠️ | Mot de passe de `p5_mlflow` | — |

Les mots de passe sont lus par Docker Compose et `create_db` ; les URL `DATABASE_*` ne servent qu'en dehors de Compose (qui les construit lui-même).

**Docker Compose**

| Variable | Rôle | Défaut |
|----------|------|--------|
| `P5_IMAGE` | Image des services `api` et `tools` (ignorée depuis un clone) | `ghcr.io/…:latest` |
| `API_PORT` | Port hôte de l'API | `8080` |
| `DB_PORT` | Port hôte de PostgreSQL | `5432` |
| `UID` / `GID` | Utilisateur du service `tools` (écriture dans `./data`, `./models`, `./mlruns`) | `1000` / `1000` |
| `P5_SEED_DEMO_USERS` | `1` : `create_db` crée les comptes de démonstration (**jamais en production**) | `0` |

**Modèle et entraînement**

| Variable | Rôle | Défaut |
|----------|------|--------|
| `MODEL_PATH_ENERGY` | Modèle servi pour l'énergie | `models/energy.cbm` |
| `MODEL_PATH_EMISSIONS` | Modèle servi pour les émissions | `models/emissions.cbm` |
| `MODEL_VERSION_PATH` | Version servie | `models/version.json` |
| `MODEL_METRICS_PATH` | Scores renvoyés par `GET /model/metrics` | `models/scores.json` |
| `TRAINING_YEAR` | Année d'entraînement (référence de l'ingestion) | `2016` |
| `MLFLOW_TRACKING_URI` | Suivi MLflow | `sqlite:///mlflow.db` |
| `MLFLOW_EXPERIMENT` | Expérience MLflow | `seattle-energy` |

**Tests**

| Variable | Rôle | Défaut |
|----------|------|--------|
| `TEST_DATABASE_ADMIN_URL` | Serveur PostgreSQL des tests (base `p5_test` créée) | `postgres:$POSTGRES_PASSWORD@localhost:5432` |
| `REQUIRE_TEST_DB` | `1` : les tests BDD échouent au lieu d'être ignorés sans base (CI) | non défini |

---

## 📚 Documentation

| Document | Description |
|----------|-------------|
| [API de prédiction](docs/api/README.md) | Routes, saisie libre, codes d'erreur, modèles servis |
| [Authentification](docs/api/authentication.md) | Jeton JWT, comptes de démonstration, `SECRET_KEY` |
| [Pipeline CI/CD](docs/ci-cd/README.md) | Diagramme du flux, workflows CI/IA/CD, sécurité du pipeline |
| [Base de données](docs/db/README.md) | Schéma UML, choix techniques, rôles, mise en route, requêtes SQL |
| [Entraînement](docs/training/README.md) | Réentraînement CatBoost multi-cible, Kumo, suivi MLflow, tests |
| [Guide de contribution](CONTRIBUTING.md) | Cycle Issue → Branche → PR, conventions |
| [Runbook Release](docs/release/README.md) | Semver, gates CD, rollback, incidents |
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

## 📄 Licence

MIT
