# Politiques de sécurité — Gates et seuils

## 🔒 Vue d'ensemble

Le workflow `ci-security` exécute 4 analyses sur chaque PR :

| Scan | Outil | Seuil d'échec du job |
|------|-------|---------------|
| **SCA** (Software Composition Analysis) | `dependency-review-action` + `trivy fs` | HIGH, CRITICAL |
| **SAST** (Static Analysis) | `codeql` | Aucun : le job publie les alertes dans Code Scanning sans faire échouer la PR |
| **Secret Leak** | `gitleaks` | Aucun : non bloquant actuellement (voir ci-dessous) |
| **IaC / Dockerfile** | `trivy config` | HIGH, CRITICAL |

> ⚠️ Aucun de ces jobs n'est un status check requis : le ruleset « Protection de main » n'exige que `ci-model-performance` et ne contient pas de règle `code_scanning`. Un échec s'affiche sur la PR (et dans le commentaire de synthèse) mais ne bloque pas techniquement le merge (voir #32).

## 📊 Analyse

### SCA — Dépendances

- **Écosystème** : pip (Python), Docker, GitHub Actions
- **Licences** : seules les licences de l'allowlist `allow-licenses` de `ci-security.yml` sont autorisées :
  `MIT, Apache-2.0, Apache-2.0 WITH LLVM-exception, BSD-3-Clause, BSD-2-Clause, ISC, Unlicense, 0BSD, MPL-2.0, CC0-1.0, CC-BY-4.0, Python-2.0, Unicode-3.0, BSL-1.0, LGPL-3.0-only, LicenseRef-NVIDIA-Proprietary`
  - `Apache-2.0 WITH LLVM-exception`, `BSD-2-Clause`, `BSL-1.0` : composants de l'expression SPDX composée de `torch` ;
  - `LGPL-3.0-only` : licence de `psycopg` (ajoutée avec l'intégration PostgreSQL) ;
  - `LicenseRef-NVIDIA-Proprietary` : ajoutée avec le pipeline d'entraînement (PR #10, qui introduit `torch` et `structured-data-models`, dépendance git hébergée par NVIDIA). Le paquet exact qui la requiert n'est pas identifiable dans `uv.lock` (torch y est en version CPU, sans paquet `nvidia-*`).
- **Scopes** : les dépendances `runtime` sont inspectées ; `dev`/`test` sont exclues

### SAST — Code

- **Langage** : Python (configurable)
- **Requêtes** : `security-and-quality` (CodeQL)
- **Mode** : les résultats sont envoyés à GitHub Code Scanning ; le job `sast` ne fait pas échouer la PR. Un blocage sur les nouvelles alertes nécessiterait une règle `code_scanning` dans le ruleset de `main`, qui n'existe pas actuellement

### Secrets

- **Scan** : `gitleaks detect --no-git` → analyse de l'**arbre de travail** du checkout (pas de l'historique ni du range de commits de la PR), avec la configuration `.gitleaks.toml`
- **Non bloquant** : la commande est lancée avec `--exit-code 1 || EXIT_CODE=$?` ; une fuite est signalée dans les logs et le SARIF est uploadé, mais le job reste vert (voir #34)
- **Fichiers d'exclusion** : une étape informative liste les motifs sensibles (`.env`, `*.key`, `*.pem`, `credentials`, `secrets`, `token`) couverts par `.gitignore` et `.dockerignore`. Elle n'échoue jamais ; `.dockerignore` n'existe pas dans le dépôt (l'étape affiche « absent »)
- **Protection complémentaire** : le *push protection* du secret scanning GitHub est activé au niveau du dépôt (paramètres de sécurité, pas un ruleset)

### Container / IaC

- **Dockerfile** : `hadolint` (dans `ci-code-quality`) avec seuil `error`
- **Image** : `trivy image` avec seuil `CRITICAL`
- **IaC** : `trivy config` avec seuil `HIGH`

## 🧾 Exceptions

Les exceptions de sécurité sont **documentées** dans `.github/security-exceptions.yml`.

> ⚠️ Ce fichier n'est lu par **aucun** workflow : il n'a aucun effet sur les scans. Les règles ci-dessous sont une convention de revue, pas un contrôle automatisé. Les deux exceptions présentes (`S8541`, omission de `uv --no-build`) ont expiré le 2026-04-10 sans conséquence sur la CI (voir #36).

**Règles (convention) :**
1. Chaque exception DOIT avoir une date d'expiration (`expires: YYYY-MM-DD`)
2. Chaque exception DOIT être motivée (`reason:`)
3. Chaque exception DOIT être signée d'un auteur (`author:`)
4. Une exception sans expiration doit être refusée en revue (aucun workflow ne le vérifie)

**Processus d'exception :**
1. Détection d'une fausse positive ou vulnérabilité non applicable
2. Création d'une entrée dans `security-exceptions.yml` avec expiration
3. Revue dans la PR
4. Mergée, elle sert de trace documentaire ; l'analyse CI ne la prend **pas** en compte

## 🚦 Gates CD (Release)

Les gates de release (`release.yml`) conditionnent le job `publish` :

| Gate / vérification | Seuil | Action |
|------|-------|--------|
| `gate-version-consistency` | Tag inexistant (local et distant), version ≠ dernier tag | Bloque la publication |
| `gate-container-scan` — smoke test | Import de `psycopg`, `sqlalchemy`, `alembic`, `app.main` dans l'image construite | Bloque la publication |
| `gate-container-scan` — `trivy image` | CRITICAL uniquement | Bloque la publication |
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