# Release & CD — Runbook

## 🔄 Déclenchement

Le workflow `release.yml` est déclenché automatiquement sur **push dans `main`**.  
Il peut aussi être déclenché manuellement via `workflow_dispatch` avec les paramètres :

- `bump` : `auto` (défaut), `patch`, `minor`, `major`, `none`
- `dry_run` : déclaré (défaut `true`) mais **lu par aucun job** — un `workflow_dispatch` qui calcule une version publie **réellement** (tag, release, image). Ne pas compter sur ce paramètre (voir issue #30).

**Court-circuits** (le job `detect` renvoie `version=skipped` et tout le reste est ignoré) :

- le sujet du commit HEAD contient `[skip release]` (insensible à la casse) ;
- aucun commit depuis le dernier tag (même avec un `bump` forcé) ;
- aucun commit éligible (voir ci-dessous) ou `bump: none`.

Sérialisation : `concurrency.group: release-main`, `cancel-in-progress: false`.

## 📦 Calcul de version (Semver)

La version est calculée à partir du **dernier tag Git** (`git describe --tags`), pas d'un fichier de version.  
Seul le **sujet** des commits est analysé (`git log --format=%s <dernier_tag>..HEAD`).

| Sujet du commit | Bump |
|--------|------|
| `<type>!:` ou `<type>(scope)!:` | **Majeure** (X+1.0.0) |
| `feat:` | **Mineure** (x.Y+1.0) |
| `fix:`, `perf:` | **Patch** (x.y.Z+1) |
| `refactor:`, `docs:`, `test:`, `chore:`, `build:`, `ci:`, `revert:` | **Aucune release** (`version=skipped`) |

- Un pied de page `BREAKING CHANGE:` dans le corps du commit n'est **pas** détecté.
- **Règle du max (Q7)** : sur plusieurs commits, le bump le plus élevé est retenu (major > minor > patch). Aucune alerte n'est émise en cas de types mixtes.
- **Version `v0.x`** : aucune règle spécifique — un `type!:` incrémente la majeure (`v0.3.0` → `v1.0.0`).

## 🚦 Gates CD (R8)

Deux gates bloquantes avant toute publication (le job `publish` exige leur succès) :

### 1. `gate-version-consistency`
- Le tag cible `vX.Y.Z` n'existe pas (local et distant) — bloquant
- Version différente du dernier tag — bloquant
- Cohérence avec `pyproject.toml` — non bloquant (avertissement)
- Présence d'une entrée dans `CHANGELOG.md` — non bloquant (le fichier n'existe pas dans le dépôt)

### 2. `gate-container-scan`
- Build de l'image Docker (`Dockerfile`, dérivé de l'image `:base`) — bloquant
- **Smoke test** : `python -c "import psycopg, sqlalchemy, alembic, app.main"` dans l'image — bloquant
- Scan `trivy image` : échec sur **CRITICAL** uniquement (seuil fixe)
- Vérifications informatives, **non bloquantes** :
  - HEALTHCHECK : avertissement s'il est absent
  - Utilisateur : `whoami` affiché, aucune vérification non-root
  - Taille de l'image : affichée, aucun plafond
- Aucune allowlist d'image de base

**Si une gate échoue :** le job `publish` est ignoré, aucun artefact n'est publié. Le job `notify-failure` (uniquement sur `push`) affiche un récapitulatif dans les logs du run (`console.log`) ; **aucun commentaire n'est posté**.

### Dépendance à l'image `:base`

Le `Dockerfile` applicatif part de `ghcr.io/<owner>/<repo>:base`, publiée par le workflow `base-image.yml` (push sur `main` modifiant `pyproject.toml`, `uv.lock` ou `Dockerfile.base`, ou `workflow_dispatch`).  
Les deux workflows démarrent **en parallèle** au merge, sans dépendance entre eux : si la PR modifie les dépendances, `gate-container-scan` peut utiliser l'ancien `:base` et le smoke test échoue. Attendre la fin de `base-image`, puis relancer le run `release` (« Re-run failed jobs »).

## 🏷️ Tag de release (R9)

- Format : `v<majeur>.<mineur>.<patch>` (ex: `v1.2.3`), tag annoté créé par `github-actions[bot]`
- Poussé avec le `GITHUB_TOKEN` du workflow (aucune GitHub App).
- Le Tag Ruleset « Protection des tags de release » bloque la **modification** et la **suppression** des tags ; la création reste autorisée (c'est ce qui permet au `GITHUB_TOKEN` de pousser le tag). Bypass : rôle Admin du dépôt.
- Un tag publié est donc **immuable** : toute correction passe par un nouveau tag.

## 🐳 Publication Docker

- Registre : `ghcr.io/<owner>/<repo>` (en minuscules)
- Tags poussés : `vX.Y.Z`, `vX.Y.Z.0` (superflu, signalé dans l'issue #30) et `latest` ; pas de tag `vX.Y`
- Plateforme : celle du runner (`linux/amd64`) ; pas de build multi-arch
- Attestations :
  - **SBOM** et provenance BuildKit : `sbom: true` et `provenance: mode=max` de `docker/build-push-action`, attachés à l'image
  - **Provenance GitHub** : `actions/attest-build-provenance` sur le digest de l'image (vérifiable via `gh attestation verify`)
- Le digest n'est **pas** communiqué dans les notes de release
- L'image publiée est reconstruite dans `publish` (avec le cache GHA) : ce n'est pas le même build que celui scanné par `gate-container-scan`

## 🔄 Séquence de publication et idempotence

Ordre réel des étapes du job `publish` :

1. Génération des notes de release (`git log --format="* %s"` depuis le dernier tag, non groupé ; aucun `CHANGELOG.md` écrit)
2. Push du tag Git `vX.Y.Z` (ignoré si le tag existe déjà)
3. Création de la GitHub Release (`gh release create --latest`, ou `gh release edit` si elle existe déjà)
4. Build & push de l'image Docker (SBOM + provenance BuildKit)
5. Attestation de provenance (`actions/attest-build-provenance`)

Ces étapes ne sont pas atomiques : le tag est poussé avant la release. Les étapes 2 et 3 sont idempotentes, ce qui permet de **relancer le run en échec** (« Re-run failed jobs ») : les sorties de `detect` sont conservées.  
Un **nouveau** run, lui, ne rejoue rien : il ne voit aucun commit depuis le tag et renvoie `version=skipped`. De même, `workflow_dispatch bump:none` produit toujours `version=skipped`.

## 🚨 Procédure d'incident

### Tag bloqué / conflit de version
1. Vérifier l'arbre des tags : `git ls-remote --tags origin | grep 'v[0-9]'`
2. Si `gate-version-consistency` signale un tag existant, la reprise passe par un nouveau commit éligible sur `main` (ou un `workflow_dispatch` avec `bump` forcé, s'il existe des commits depuis le dernier tag)
3. Si le tag existe mais que la release ou l'image a échoué, utiliser « Re-run failed jobs » sur le run d'origine (un `workflow_dispatch bump:none` ne fait rien)

### Rollback
- Aucun rollback automatique de `main`.
- Pour annuler une release :
  1. `git revert` du commit sur `main` + PR
  2. Nouvelle release (le titre de la PR doit être de type `fix:` pour déclencher un patch : `revert:` ne déclenche aucune release)
  3. L'ancienne image reste sur GHCR (tag `vX.Y.Z`)

### Image compromise
1. Marquer le package comme `deprecated` sur GHCR
2. Créer une issue de sécurité
3. Publier un correctif + nouvelle release

## 🔧 Prérequis

- **Secrets** : aucun secret dédié — le workflow utilise `GITHUB_TOKEN`.
- **Permissions** du workflow `release.yml` :
  - niveau workflow : `contents: read`, `packages: read`
  - job `publish` : `contents: write` (push du tag + release), `packages: write` (GHCR), `id-token: write` et `attestations: write` (attestations)
  - job `gate-container-scan` : `security-events: write` (upload SARIF Trivy)
- **Tag Ruleset** : aucune configuration de bypass n'est nécessaire pour la release, la création de tags n'étant pas restreinte.
