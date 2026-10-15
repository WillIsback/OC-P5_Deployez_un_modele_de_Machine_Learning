# Contribuer au projet

Merci de votre intérêt pour ce projet. Ce document décrit le cycle de contribution, les conventions et les règles à respecter.

---

## 📋 Cycle de contribution

```
Issue (bug | feature | refactor | docs | other)
   │
   ├── Branch A ──┐
   └── Branch B ──┤──► PR(s) ──► checks requis ──► review ──► MERGE (squash) dans main
                   │
                   ▼
            Workflow Release (post-merge)
```

### 1. Ouvrir une Issue

Toute tâche doit être adossée à une **issue** avant son démarrage (**R1**).  
Types d'issues autorisés :

| Type | Label | Description |
|------|-------|-------------|
| Bug | `type:bug` | Rapport de bug |
| Feature | `type:feature` | Nouvelle fonctionnalité |
| Refactor | `type:refactor` | Amélioration du code existant |
| Docs | `type:docs` | Documentation |
| Other | `type:other` | Sujet hors des 4 catégories précédentes |

> **Règle N→N (R3)** : Une issue peut couvrir plusieurs branches/PR, et une PR peut couvrir plusieurs issues.  
> Le formulaire d'issue demande si le travail est scindable.

### 2. Créer une branche

```bash
# Depuis main à jour
git checkout main
git pull origin main
git checkout -b <type>/issue-<num>-<slug>
```

Conventions de nommage :

| Type | Préfixe |
|------|---------|
| Nouvelle fonctionnalité | `feat/` |
| Correction de bug | `fix/` |
| Refactoring | `refactor/` |
| Documentation | `docs/` |
| Maintenance / CI | `chore/` |
| Correction urgente | `hotfix/` |
| Préparation de release | `release/` |

Format complet : `^(feat|fix|refactor|docs|chore|hotfix|release)/[a-z0-9._-]+$`

### 3. Ouvrir une Pull Request

- **Interdiction de push direct sur `main` (R4)** — toute modification passe par une PR.
- Titre de PR en **Conventional Commits** : `feat:`, `fix:`, `refactor:`, `docs:`, `test:`, `chore:`, `perf:`, `ci:`, `build:`, `revert:`, avec `!` pour les breaking changes.
- La PR doit référencer au moins une issue (`Closes #...`, `Related to #...` ou `Task: #...`).
- 5 workflows CI s'exécutent sur chaque PR ; leurs jobs sont des checks **requis** par le ruleset « Protection de main » (liste exacte dans [`docs/ci-cd/README.md`](docs/ci-cd/README.md)) :
  - `ci-code-quality`
  - `ci-test`
  - `ci-security`
  - `ci-traceability`
  - `ci-model-performance` (gate de non-régression du modèle : `models/scores.json` comparé à `models/scores_baseline.json`, voir `app/training/score_validation.py`)
- En complément, une **revue de code IA non bloquante** est postée sur la PR par le workflow `ai-code-review` (déclenché après `ci-test`) via l'action [`WillIsback/code-review`](https://github.com/WillIsback/code-review).
- Projet solo : la règle de revue est désactivée (`required_approving_review_count: 0`) — une PR peut être mergée par son auteur, sans bypass administrateur.
- **Merge en squash uniquement (R6)** — imposé par le ruleset « Protection de main » ; l'historique de `main` est linéaire.

### 4. Après le merge

Le merge dans `main` déclenche automatiquement le workflow `release` qui :
1. Calcule la version (bump semver automatique)
2. Passe les gates CD (cohérence de version + scan container)
3. Crée une GitHub Release + tag `vX.Y.Z`
4. Publie l'image Docker sur GHCR

---

## ✅ Checklist avant de soumettre une PR

- [ ] Le titre suit le format Conventional Commits
- [ ] Les issues liées sont référencées dans le corps de la PR
- [ ] Les tests passent localement (`uv run pytest --cov`) avec PostgreSQL démarré (`docker compose up -d db`) : sans base joignable, les tests qui en dépendent sont **ignorés** (skip), pas exécutés
- [ ] Le linter passe (`uv run ruff check .`)
- [ ] Le formateur passe (`uv run ruff format --check .`)
- [ ] Les dépendances sont à jour (`uv lock --check`)
- [ ] Après un réentraînement, `models/scores.json` est commité : la gate `ci-model-performance` échoue si la MedAPE CatBoost augmente de plus de 5 points (`MAX_MEDAPE_INCREASE`) ou si le R² baisse de plus de 0,05 (`MIN_R2_DROP`) par rapport à `models/scores_baseline.json`
- [ ] La documentation est mise à jour si nécessaire
- [ ] Aucun secret ou token n'est commité

---

## 🔧 Commandes utiles

```bash
# Installer les dépendances
uv sync --frozen

# Linter
uv run ruff check .

# Formateur
uv run ruff format .

# Tests (PostgreSQL requis, sinon les tests de base de données sont ignorés).
# Connexion admin : TEST_DATABASE_ADMIN_URL, sinon postgres:$POSTGRES_PASSWORD@localhost:5432
# (POSTGRES_PASSWORD lu depuis .env) ; REQUIRE_TEST_DB=1 transforme le skip en échec (CI).
docker compose up -d db
uv run pytest --cov=app

# Vérifier le lockfile
uv lock --check
```

---

## 🐳 Docker

Le `Dockerfile` dérive de l'image de base des dépendances (`ARG BASE_IMAGE`, par défaut `ghcr.io/willisback/oc-p5_deployez_un_modele_de_machine_learning:base`, publiée par le workflow `base-image`). Sans accès à cette image, construire la base localement et la passer en argument :

```bash
# Build avec l'image de base GHCR (défaut)
docker build -t <image> .

# Build avec une image de base locale
docker build -f Dockerfile.base -t p5-base .
docker build --build-arg BASE_IMAGE=p5-base -t <image> .
```

Un simple `docker run -p 8080:8080 <image>` ne donne pas une API utilisable : il manque `SECRET_KEY`, `DATABASE_URL` (PostgreSQL) et les modèles `models/*.cbm` (non versionnés, à monter). Utiliser `docker compose` (services `db`, `api` et `tools`), dont la mise en route complète (provisionnement, ingestion, entraînement) est décrite dans [`docs/db/README.md`](docs/db/README.md#4-mise-en-route).

---

## 🔒 Sécurité

- Les workflows CI sont analysés par `actionlint` (bloquant) et `zizmor` (bloquant à partir de la sévérité « high » ; les `dangerous-triggers` justifiés sont listés dans `.github/zizmor.yml`).
- Les dépendances sont scannées par `trivy` et `dependency-review-action`.
- Les secrets sont détectés par `gitleaks` sur la plage de commits de la PR (bloquant).
- Les exceptions de sécurité sont recensées dans `.github/security-exceptions.yml` (datées, motivées, signées). Le registre est **validé par la CI** (`scripts/check_security_exceptions.py`) : une exception expirée fait échouer `ci-security`.

---

## 📚 Ressources

- [Conventional Commits](https://conventionalcommits.org)
- [Semantic Versionning](docs/policies/semver.md)
- [Politiques de sécurité](docs/policies/security-gates.md)
- [Action de revue de code IA `code-review`](https://github.com/WillIsback/code-review)