# Pipeline CI/CD

## 📊 Diagramme du flux de travail

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="../diagrams/workflow.svg">
  <img alt="Diagramme CI/CD" src="../diagrams/workflow.svg" width="100%">
</picture>

> Diagramme généré avec [D2](https://d2lang.com/) — source : [`docs/diagrams/workflow.d2`](../diagrams/workflow.d2)
>
> ⚠️ Le diagramme D2/SVG est obsolète : il ne représente ni `ci-model-performance`, ni le workflow `base-image`, ni le smoke test de `gate-container-scan`. Le diagramme Mermaid ci-dessous fait foi en attendant sa régénération.

<details>
<summary>Afficher le diagramme Mermaid (fallback)</summary>

```mermaid
graph TD
    Issue["Issue (bug · feature · refactor · docs · other)"] --> BranchA["Branch A"]
    Issue --> BranchB["Branch B"]
    BranchA --> PR["Pull Request (squash merge)"]
    BranchB --> PR
    PR -->|check requis| CI5[ci-model-performance]
    PR --> CI1[ci-code-quality]
    PR --> CI2[ci-test]
    PR --> CI3[ci-security]
    PR --> CI4[ci-traceability]
    CI2 -->|workflow_run| AI["Revue de code IA<br/>(ai-code-review · non bloquant)"]
    AI -.->|commentaire| PR
    PR -->|review| Merge["Merge dans main"]
    Merge -->|"si pyproject.toml / uv.lock / Dockerfile.base modifiés"| Base["Workflow base-image<br/>(image :base sur GHCR)"]
    Merge --> Detect{"Workflow release<br/>detect"}
    Base -.->|"FROM :base (aucune dépendance entre workflows)"| G2
    Detect -->|"version ≠ skipped"| G1["gate-version-consistency"]
    Detect -->|"version ≠ skipped"| G2["gate-container-scan<br/>(build · smoke test · Trivy CRITICAL)"]
    G1 -->|PASS| Publish["publish"]
    G2 -->|PASS| Publish
    Publish --> Release["CHANGELOG → tag vX.Y.Z → GitHub Release"]
    Publish --> Docker["Image Docker GHCR + SBOM + provenance"]
```

</details>

---

## 🔄 Workflows

### CI — Contrôle qualité (PR)

| Workflow | Nom de job (check context) | Responsabilité |
|----------|---------------------------|----------------|
| `ci-code-quality.yml` | `ci-code-quality` | Lint (ruff), format, validation du titre de PR (regex Conventional Commits, pas commitlint), hadolint, actionlint, étape « zizmor » (voir ci-dessous), lockfile |
| `ci-test.yml` | `ci-test` | Tests unitaires + couverture (service PostgreSQL), seuil global 70 % (bloquant), seuil incrémental 80 % (non bloquant), dry-run applicatif, matrice Python 3.11/3.12 |
| `ci-model-performance.yml` | `ci-model-performance` | Gate non-régression du modèle : compare `models/scores.json` (dernier entraînement) à `models/scores_baseline.json` (MedAPE +5 pts / R2 -0,05 par cible) |
| `ci-security.yml` | `SCA (Dependency Review)`, `SAST (CodeQL)`, `Secret Leak (Gitleaks)`, `IaC / Dockerfile Scan (Trivy config)`, `Synthèse de sécurité` (pas de job `ci-security`) | SCA (dep-review + trivy fs), SAST (CodeQL), secret leak (Gitleaks), IaC (trivy config), commentaire de synthèse |
| `ci-traceability.yml` | `ci-traceability` | Référence issue obligatoire (R1/R3), type de PR valide, cohérence semver (Q7) |

> Tous les workflows CI sont déclenchés sur `pull_request` vers `main` (et `workflow_dispatch`), avec une concurrence par ref et `cancel-in-progress: true`.
>
> **Checks requis** : le ruleset « Protection de main » n'exige qu'**un seul** status check, `ci-model-performance`. Les autres workflows CI s'affichent en échec sur la PR mais ne bloquent pas techniquement le merge (voir issue #30).

**Précisions sur l'existant (non corrigé, voir issue #30)** :

- **Titre de PR** : l'étape « commitlint » est une simple regex sur le titre de la PR : `^(feat|fix|refactor|docs|test|chore|perf|ci|build|revert)(\(.+\))?!?: .+`. Le type `style` n'y figure pas.
- **« zizmor »** : malgré son nom, l'étape exécute `ruff check --select S` (via `astral-sh/ruff-action`) sur `.github/workflows/` en `continue-on-error: true`. Elle n'est donc pas bloquante, et ce répertoire ne contient que des fichiers YAML que ruff n'analyse pas : zizmor n'est pas réellement exécuté.
- **Couverture incrémentale** : `diff-cover --fail-under=80 … || true` → le résultat est affiché mais n'échoue jamais.
- **Dry-run release** (`ci-test`) : simulé — le script Python affiche un dernier tag codé en dur (`v0.0.1`) et ne lit ni les tags ni les commits. Seul le « dry-run applicatif » (import de `app.main`) teste réellement quelque chose.
- **PostgreSQL** : `ci-test` démarre un service `postgres:17-alpine` et définit `REQUIRE_TEST_DB=1` : si la base est injoignable, les tests BDD échouent au lieu d'être ignorés.
- **Matrice Python** : `ci-test` tourne sur 3.11 et 3.12, alors que `pyproject.toml` impose `requires-python = ">=3.12"` ; l'entrée 3.11 est incohérente avec le projet.

### IA — Revue de code & triage (non bloquant)

| Workflow | Déclencheur | Responsabilité |
|----------|-------------|----------------|
| `ai-code-review.yml` | `workflow_run` sur `ci-test` | Poste une revue de code IA sur la PR via l'action [`WillIsback/code-review`](https://github.com/WillIsback/code-review) (runner hébergé, fork-safe, aucun checkout/execution du code de la PR) |
| `ai-issue-triage.yml` | `issues: [opened]` | Triage IA des issues (auteurs de confiance uniquement) |

> Non bloquants (ils ne conditionnent pas le merge). Secrets requis : `VLLM_URL`, `VLLM_API_KEY`, `CF_ACCESS_CLIENT_ID`, `CF_ACCESS_CLIENT_SECRET`.

### CD — Release (post-merge)

```yaml
on:
  push:
    branches: [main]
  workflow_dispatch:
    inputs:
      bump: [auto, patch, minor, major, none]
      dry_run: boolean
```

Sérialisation stricte via `concurrency.group: release-main` (pas de releases en parallèle).

| Job | Rôle |
|-----|------|
| `detect` | Calcule la version semver depuis le dernier tag Git (max des bumps). Seuls `feat`, `fix`, `perf` ou un breaking change `type!:` déclenchent une release ; sinon `version=skipped`. Un commit HEAD dont le sujet contient `[skip release]` court-circuite tout |
| `gate-version-consistency` | Vérifie que le tag n'existe pas (local et distant) et que la version avance ; écart avec `pyproject.toml` et CHANGELOG seulement signalés |
| `gate-container-scan` | Build l'image Docker, **smoke test** (import de `psycopg`, `sqlalchemy`, `alembic`, `app.main` dans l'image), scan Trivy (seuil CRITICAL, bloquant) ; HEALTHCHECK, utilisateur et taille seulement affichés (non bloquants) |
| `publish` | CHANGELOG (notes) → tag `vX.Y.Z` → GitHub Release → build & push de l'image GHCR (SBOM + provenance) → `attest-build-provenance` |
| `notify-failure` | Si un job échoue sur un `push` : construit un message récapitulatif et l'affiche dans les logs (`console.log`) ; **rien n'est posté** sur la PR ni sur une issue |

> L'input `dry_run` est déclaré mais lu par aucun job : un `workflow_dispatch` publie réellement (voir [RELEASE.md](../../RELEASE.md)).

### Image de base — `base-image.yml`

| Élément | Comportement réel |
|---------|------------------|
| Déclencheurs | `push` sur `main` modifiant `pyproject.toml`, `uv.lock` ou `Dockerfile.base` ; `workflow_dispatch` |
| Produit | `ghcr.io/<owner>/<repo>:base` (dépendances précompilées), consommée par le `Dockerfile` applicatif (`ARG BASE_IMAGE=…:base`) |
| Concurrence | `base-image-main`, `cancel-in-progress: true` |

**Course base-image / release au merge** : les deux workflows démarrent en parallèle sur le même push, sans dépendance entre eux. Si la PR modifie les dépendances, `gate-container-scan` peut construire l'image à partir de l'ancien `:base` : le smoke test échoue alors (dépendance manquante) et la release est avortée avant toute publication. Procédure : attendre la fin de `base-image`, puis relancer le run `release` en échec (ou relancer `base-image` via `workflow_dispatch` si nécessaire).


---

## 🔒 Sécurité du pipeline

- **Permissions** : chaque workflow déclare `permissions:` au niveau workflow (lecture par défaut). Seuls les jobs de `ci-security.yml` et les jobs `gate-container-scan`, `publish` et `notify-failure` de `release.yml` redéfinissent leurs permissions ; les autres jobs héritent du niveau workflow.
- **Épinglage des actions** — état réel :
  - épinglées par SHA : `astral-sh/setup-uv`, `astral-sh/ruff-action`, `hadolint/hadolint-action`, `docker/login-action`, `docker/setup-buildx-action`, `docker/build-push-action`, `WillIsback/code-review` ;
  - référencées par tag majeur : `actions/checkout@v4`, `actions/setup-python@v5`, `actions/upload-artifact@v4`, `actions/github-script@v7`, `actions/dependency-review-action@v4`, `actions/attest-build-provenance@v2`, `github/codeql-action/*@v4`.
- **Outils non épinglés** : `uv` (`version: "latest"`), trivy (script `install.sh` de la branche `main` dans `ci-security`, image `ghcr.io/aquasecurity/trivy:latest` dans `release`), actionlint (script de la branche `main`), gitleaks (`go install …@latest`).
- **Analyse du pipeline** : `actionlint` (bloquant) dans `ci-code-quality.yml` ; l'étape « zizmor » n'exécute pas zizmor (voir plus haut).
- **Secrets** : le `GITHUB_TOKEN` est utilisé avec les permissions minimales nécessaires.
- **Scan container avant publication** : gate bloquante `gate-container-scan`.

---

## 📚 Documentation associée

- [Guide de contribution](../../CONTRIBUTING.md) — cycle Issue → Branche → PR
- [Runbook de release](../../RELEASE.md) — semver, gates CD, rollback, incidents
- [Politique de version sémantique](../policies/semver.md)
- [Politique des gates de sécurité](../policies/security-gates.md)
- [Action de revue de code IA `code-review`](https://github.com/WillIsback/code-review) — revue de PR + triage d'issues
- [Source D2 du diagramme](../diagrams/workflow.d2)

---

## 🛠️ Génération du diagramme

```bash
# Installer D2 (macOS / Linux)
brew install d2

# Régénérer le SVG
d2 docs/diagrams/workflow.d2 docs/diagrams/workflow.svg --theme 6 --layout dagre --dark-theme 5
```