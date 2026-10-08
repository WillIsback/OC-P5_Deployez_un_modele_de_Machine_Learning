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
