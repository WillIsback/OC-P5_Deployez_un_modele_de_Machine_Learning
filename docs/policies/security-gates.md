# Politiques de sécurité — Gates et seuils

## 🔒 Vue d'ensemble

Le workflow `ci-security` exécute 4 analyses sur chaque PR :

| Scan | Outil | Seuil d'échec du job |
|------|-------|---------------|
| **SCA** (Software Composition Analysis) | `dependency-review-action` + `trivy fs` | HIGH, CRITICAL |
| **SAST** (Static Analysis) | `codeql` | Nouvelles alertes `error` ou sécurité `high`/`critical`, via la règle `code_scanning` du ruleset (le job lui-même n'échoue pas) |
| **Secret Leak** | `gitleaks` | Fuite détectée (bloquant, après upload SARIF) |
| **IaC / Dockerfile** | `trivy config` | HIGH, CRITICAL |

> Ces quatre jobs sont des status checks requis par le ruleset « Protection de main » : un job en échec bloque le merge. Les gates elles-mêmes restent permissives là où le tableau l'indique (CodeQL, Gitleaks) : un job vert ne garantit donc pas l'absence d'alerte.

## 📊 Analyse

### SCA — Dépendances

- **Écosystème** : pip (Python), Docker, GitHub Actions
- **Licences** : seules les licences de l'allowlist `allow-licenses` de `ci-security.yml` sont autorisées :
  `MIT, Apache-2.0, Apache-2.0 WITH LLVM-exception, BSD-3-Clause, BSD-2-Clause, ISC, Unlicense, 0BSD, MPL-2.0, CC0-1.0, CC-BY-4.0, Python-2.0, Unicode-3.0, BSL-1.0, LGPL-3.0-only`
  - `Apache-2.0 WITH LLVM-exception`, `BSD-2-Clause`, `BSL-1.0` : composants de l'expression SPDX composée de `torch` ;
  - `LGPL-3.0-only` : licence de `psycopg` (ajoutée avec l'intégration PostgreSQL).
- **Scopes** : les dépendances `runtime` sont inspectées ; `dev`/`test` sont exclues

### SAST — Code

- **Langage** : Python (configurable)
- **Requêtes** : `security-and-quality` (CodeQL)
- **Mode** : les résultats sont envoyés à GitHub Code Scanning ; le job `sast` ne fait pas échouer la PR. Le blocage est assuré par la règle `code_scanning` du ruleset de `main` : une PR qui introduit une alerte CodeQL de niveau `error`, ou une alerte de sécurité `high` ou `critical`, ne peut pas être mergée

### Secrets

- **Scan** : `gitleaks detect` couvre la **plage de commits de la PR** (`--log-opts "<base>..<head>"`, checkout `fetch-depth: 0`) ; hors PR, l'historique du dépôt est scanné. Un secret ajouté puis supprimé dans la PR est donc détecté.
- **Bloquant** : une fuite détectée fait échouer le job, **après** l'upload du SARIF (rapport conservé dans Code Scanning).
- **Fichiers d'exclusion** : une étape informative liste les motifs sensibles (`.env`, `*.key`, `*.pem`, `credentials`, `secrets`, `token`) couverts par `.gitignore` et `.dockerignore`. Elle n'échoue jamais ; `.dockerignore` n'existe pas dans le dépôt (l'étape affiche « absent »)
- **Protection complémentaire** : le *push protection* du secret scanning GitHub est activé au niveau du dépôt (paramètres de sécurité, pas un ruleset)

### Container / IaC

- **Dockerfile** : `hadolint` (dans `ci-code-quality`) avec seuil `error`
- **Image** : `trivy image` avec seuil `CRITICAL`
- **IaC** : `trivy config` avec seuil `HIGH`

## 🧾 Exceptions

Les exceptions de sécurité sont recensées dans `.github/security-exceptions.yml`, **validé par la CI** : l'étape « Valider le registre des exceptions de sécurité » de `ci-security` exécute `scripts/check_security_exceptions.py`. Une exception expirée, non datée, non motivée, non signée ou sans identifiant fait échouer le job.

**Règles (appliquées par la CI) :**
1. Chaque exception DOIT avoir une date d'expiration (`expires: YYYY-MM-DD`) postérieure à la date du jour
2. Chaque exception DOIT être motivée (`reason:`)
3. Chaque exception DOIT être signée d'un auteur (`author:`)
4. Chaque exception DOIT porter un identifiant (`cve:`)

**Processus d'exception :**
1. Détection d'une fausse positive ou vulnérabilité non applicable
2. Création d'une entrée dans `security-exceptions.yml` avec expiration
3. Revue dans la PR
4. Mergée, elle est validée (datée, motivée, signée) par la CI ; son **application** automatique par l'outil concerné reste une convention de revue

Les deux exceptions présentes (`S8541`, omission volontaire de `uv --no-build` pour la dépendance git `structured-data-models`) ont été renouvelées au 2027-04-10.

## 🚦 Gates CD (Release)

Les gates de release (`release.yml`) conditionnent le job `publish` :

| Gate / vérification | Seuil | Action |
|------|-------|--------|
| `gate-version-consistency` | Tag inexistant (local et distant), version ≠ dernier tag | Bloque la publication |
| `gate-container-scan` — smoke test | Import de `psycopg`, `sqlalchemy`, `alembic`, `app.main` dans l'image construite | Bloque la publication |
| `gate-container-scan` — `trivy image` | CRITICAL uniquement | Bloque la publication |
| `gate-container-scan` → `publish` | Image construite une fois, retaguée par `publish` (`docker buildx imagetools create`) | L'image publiée est celle scannée (même digest) |
| HEALTHCHECK | Présence affichée | Avertissement seulement |
| Utilisateur non-root | `whoami` affiché | Information seulement, non vérifié |
| Taille d'image | Affichée | Information seulement, aucun plafond |

Il n'existe pas d'allowlist d'image de base : l'image applicative dérive de `ghcr.io/<owner>/<repo>:base` (workflow `base-image`).

## 🔄 Mise à jour des dépendances

Les dépendances sont mises à jour automatiquement via **Dependabot** (`.github/dependabot.yml`) :

- **pip** : hebdomadaire (lundi)
- **Docker** : hebdomadaire (lundi)
- **GitHub Actions** : hebdomadaire (lundi)

Les PR Dependabot sont labelisées `type:chore` et `dependencies`.

## 📝 Rapports

- Les SARIF des scans (CodeQL, Trivy fs/config/image, Gitleaks) sont uploadés dans GitHub Code Scanning
- Un commentaire de synthèse consolidé est posté sur chaque PR (job `summary` de `ci-security`)
- Les alertes Dependabot sont actives