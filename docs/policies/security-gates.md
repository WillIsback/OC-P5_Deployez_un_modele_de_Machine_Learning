# Politiques de sécurité — Gates et seuils

## 🔒 Vue d'ensemble

Le pipeline de sécurité combine 4 analyses obligatoires sur chaque PR :

| Scan | Outil | Seuil d'échec |
|------|-------|---------------|
| **SCA** (Software Composition Analysis) | `dependency-review-action` + `trivy fs` | HIGH, CRITICAL |
| **SAST** (Static Analysis) | `codeql` | Nouvelles alertes uniquement (diff-aware) |
| **Secret Leak** | `gitleaks` | Toute fuite détectée |
| **IaC / Dockerfile** | `trivy config` | HIGH, CRITICAL |

## 📊 Analyse

### SCA — Dépendances

- **Écosystème** : pip (Python), Docker, GitHub Actions
- **Licences** : seules les licences de la allowlist sont autorisées (MIT, Apache-2.0, BSD, ISC, MPL-2.0, CC0-1.0, Python-2.0, Unlicense, etc.)
- **Scopes** : les dépendances `runtime` sont inspectées ; `dev`/`test` sont exclues

### SAST — Code

- **Langage** : Python (configurable)
- **Requêtes** : `security-and-quality` (CodeQL)
- **Mode** : diff-aware — seules les vulnérabilités introduites par la PR sont bloquantes

### Secrets

- **Scan** : sur le range de commits de la PR (`git log origin/main...HEAD`)
- **Fichiers exclus** : `.gitignore` et `.dockerignore` sont vérifiés pour couvrir les chemins sensibles (`.env`, `*.key`, `*.pem`, `credentials`, `secrets`, `token`)
- **Protection complémentaire** : `secret_scanning_push_protection` activée dans le Branch Ruleset

### Container / IaC

- **Dockerfile** : `hadolint` (dans `ci-code-quality`) avec seuil `error`
- **Image** : `trivy image` avec seuil `CRITICAL`
- **IaC** : `trivy config` avec seuil `HIGH`

## 🧾 Exceptions

Les exceptions de sécurité sont gérées dans `.github/security-exceptions.yml`.

**Règles :**
1. Chaque exception DOIT avoir une date d'expiration (`expires: YYYY-MM-DD`)
2. Chaque exception DOIT être motivée (`reason:`)
3. Chaque exception DOIT être signée d'un auteur (`author:`)
4. Une exception sans expiration sera rejetée par le workflow CI

**Processus d'exception :**
1. Détection d'une fausse positive ou vulnérabilité non applicable
2. Création d'une entrée dans `security-exceptions.yml` avec expiration
3. Revue dans la PR
4. Mergée, l'analyse CI l'ignore jusqu'à expiration

## 🚦 Gates CD (Release)

Les gates de release sont plus strictes que l'analyse PR :

| Gate | Seuil | Action |
|------|-------|--------|
| `gate:version-consistency` | Tag inexistant, cohérence semver | Bloque la publication |
| `gate:container-scan` | CRITICAL uniquement | Bloque la publication |
| Image size | Optionnel, plafond configurable | Warning |
| Base image | Allowlist | Bloque si non autorisée |

## 🔄 Mise à jour des dépendances

Les dépendances sont mises à jour automatiquement via **Dependabot** (`.github/dependabot.yml`) :

- **pip** : hebdomadaire (lundi)
- **Docker** : hebdomadaire (lundi)
- **GitHub Actions** : hebdomadaire (lundi)

Les PR Dependabot sont labelisées `type:chore` et `dependencies`.

## 📝 Rapports

- Les SARIF de tous les scans sont uploadés dans GitHub Code Scanning
- Un commentaire de synthèse consolidé est posté sur chaque PR (job `summary` de `ci-security`)
- Les alertes Dependabot sont actives