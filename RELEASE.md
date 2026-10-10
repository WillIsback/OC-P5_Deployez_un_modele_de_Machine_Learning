# Release & CD — Runbook

## 🔄 Déclenchement

Le workflow `release.yml` est déclenché automatiquement sur **push dans `main`**.  
Il peut aussi être déclenché manuellement via `workflow_dispatch` avec les paramètres :

- `bump` : `auto` (défaut), `patch`, `minor`, `major`, `none`
- `dry_run` : `true` (défaut, aucune publication réelle)

## 📦 Calcul de version (Semver)

La version est calculée à partir du **dernier tag Git `v*`** (pas d'un fichier de version).

| Commit | Bump |
|--------|------|
| `BREAKING CHANGE` ou `<type>!:` | **Majeure** (X+1.0.0) |
| `feat:` | **Mineure** (x.Y+1.0) |
| `fix:`, `perf:`, `refactor:`, `docs:`, `test:`, `chore:`, `build:`, `ci:` | **Patch** (x.y.Z+1) |

**Règle du max (Q7)** : Si une PR mixe des commits de types différents, le bump le plus élevé est appliqué (major > minor > patch).  
Une alerte est émise en cas de types mixtes dans une PR.

**Version `v0.x`** : Les mineurs sont considérées comme cassantes (breaking).

## 🚦 Gates CD (R8)

Deux gates bloquantes avant toute publication :

### 1. `gate:version-consistency`
- Le tag cible `vN` n'existe pas (local et distant)
- Cohérence avec `pyproject.toml` (non bloquant)
- Version strictement supérieure au dernier tag
- Présence d'une entrée CHANGELOG pour la version (non bloquant)

### 2. `gate:container-scan`
- Build de l'image Docker
- Scan `trivy` : échec sur **CRITICAL**, HIGH paramétrable
- Vérifications supply-chain :
  - Base image autorisée
  - HEALTHCHECK présent
  - Utilisateur non-root
  - Taille de l'image

**Si une gate échoue :** la publication est avortée, aucun artefact n'est publié, et un commentaire de notification est posté.

## 🏷️ Tag de release (R9)

- Format : `v<majeur>.<mineur>.<patch>` (ex: `v1.2.3`)
- Un tag publié est **immuable** : toute correction passe par un nouveau tag.
- La création/modification/suppression manuelle des tags est bloquée par le Tag Ruleset.
- Seul le bot de release (GitHub App) peut créer des tags via le bypass.

## 🐳 Publication Docker

- Registre : `ghcr.io/<org>/<repo>`
- Tags poussés : `vN`, `vN.M` (minor), `latest` (sauf prerelease)
- Multi-arch : `linux/amd64`, `linux/arm64` (si configuré)
- Attestations :
  - **Provenance** : `attest-build-provenance` (vérifiable via `cosign verify`)
  - **SBOM** : `attest-sbom` (format SPDX)
- Digest épinglé communiqué dans les notes de release

## 🔄 Atomicité et idempotence

La séquence de publication est :

1. Génération du CHANGELOG (depuis le dernier tag)
2. Création de la GitHub Release (draft → publish)
3. Push du tag Git `vN`
4. Build & push de l'image Docker
5. Attestations (provenance + SBOM)

Toute étape peut être rejouée via `workflow_dispatch bump:none` en cas d'incident.

## 🚨 Procédure d'incident

### Tag bloqué / conflit de version
1. Vérifier l'arbre des tags : `git ls-remote --tags origin | grep 'v[0-9]'`
2. Si collision, incrémenter le patch et relancer avec `bump:patch`
3. Si le tag existe mais la release a échoué, utiliser `workflow_dispatch bump:none`

### Rollback
- Aucun rollback automatique de `main`.
- Pour annuler une release :
  1. `git revert` du commit sur `main` + PR
  2. Nouvelle release patch
  3. L'ancienne release reste sur GHCR (digest épinglé)

### Image compromise
1. Marquer le package comme `deprecated` sur GHCR
2. Créer une issue de sécurité
3. Publier un correctif + nouvelle release

## 🔧 Prérequis

- **Secrets/variables** :
  - L'ID d'App GitHub pour le bypass du tag ruleset (à configurer dans le ruleset)
- **Permissions** du workflow `release.yml` :
  - `contents: write` (push tag + release)
  - `packages: write` (GHCR)
  - `id-token: write` (attestations)
- **Bypass du Tag Ruleset pour l'App de release** :
  Le ruleset de tags bloque la création/modification/suppression de tags pour les humains.
  Le workflow `release.yml` a besoin de pouvoir créer des tags `v*`. Ajoutez manuellement l'App
  (GitHub App utilisée par le workflow) comme `bypass_actor` de type `Integration` dans le
  Tag Ruleset après sa création via l'UI GitHub :
  1. Aller dans Settings > Rules > Rulesets > "Protection des tags de release"
  2. Cliquer sur "Edit" > "Bypass actors"
  3. Ajouter l'App avec `bypass_mode: always`
  4. Sauvegarder

  L'ID de l'App n'étant pas connu au moment de la création du ruleset, cette étape
  manuelle est nécessaire.