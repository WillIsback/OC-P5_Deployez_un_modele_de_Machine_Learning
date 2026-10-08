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
- La PR doit référencer au moins une issue (`Closes #...` ou `Related to #...`).
- Les 4 workflows CI sont obligatoires et bloquants :
  - `ci-code-quality`
  - `ci-test`
  - `ci-security`
  - `ci-traceability`
- Une revue de code est requise (1 approveur minimum).
- **Merge en squash uniquement (R6)** — l'historique de `main` est linéaire.

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
- [ ] Les tests passent localement (`uv run pytest --cov`)
- [ ] Le linter passe (`uv run ruff check .`)
- [ ] Le formateur passe (`uv run ruff format --check .`)
- [ ] Les dépendances sont à jour (`uv lock --check`)
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

# Tests
uv run pytest --cov=app

# Vérifier le lockfile
uv lock --check
```

---

## 🐳 Docker

```bash
# Build
docker build -t <image> .

# Run
docker run -p 8080:8080 <image>
```

---

## 🔒 Sécurité

- Les workflows CI sont analysés par `actionlint` et `zizmor`.
- Les dépendances sont scannées par `trivy` et `dependency-review-action`.
- Les secrets sont détectés par `gitleaks`.
- Les exceptions de sécurité sont dans `.github/security-exceptions.yml` (datées, avec expiration).

---

## 📚 Ressources

- [Conventional Commits](https://conventionalcommits.org)
- [Semantic Versionning](docs/policies/semver.md)
- [Politiques de sécurité](docs/policies/security-gates.md)