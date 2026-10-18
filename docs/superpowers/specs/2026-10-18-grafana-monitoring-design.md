# Design — Monitoring Grafana (issue #64)

- **Date** : 2026-10-18
- **Branche** : `feat/64-grafana-monitoring`
- **Statut** : validé en brainstorming, en attente de relecture

## 1. Contexte et objectifs

Objectif SMART fixé avec le mentor : « mettre en place une db + le monitoring associé ». La base PostgreSQL trace déjà :

- chaque appel API dans `api_requests` (méthode, route, statut, `duration_ms`, `user_id`, horodatage) ;
- chaque prédiction dans `predictions` (modèle, valeurs, origine : `api_request_id` et/ou `building_year_id`) ;
- l'écart prédiction / réel des années de production dans la vue `v_projected_evaluation`.

Aucun outil n'exploite ces données. Objectif : deux tableaux de bord Grafana, **« API »** (santé du service) et **« Modèle »** (suivi du modèle), visibles dès l'installation par le Quickstart.

Hors périmètre : Prometheus / métriques système (CPU, mémoire), alerting, rapport de dérive des features (Evidently).

## 2. Décisions

| # | Sujet | Décision |
|---|---|---|
| D1 | Contenu | Deux tableaux de bord : « API » et « Modèle » |
| D2 | Démarrage | Service toujours démarré (pas de profil), URL affichée par le Quickstart |
| D3 | Accès | Connexion obligatoire : admin / `GRAFANA_ADMIN_PASSWORD` (aléatoire, `.env`) ; anonyme et inscription désactivés |
| D4 | Source de données | Grafana lit PostgreSQL directement (SQL), pas de Prometheus |
| D5 | Droits | Rôle `p5_grafana` en lecture seule, droits **par colonne** ; aucun corps, IP ni PII |
| D6 | État | Service sans état : datasource et tableaux de bord provisionnés par fichiers versionnés, pas de volume |
| D7 | Données « Modèle » | Le Quickstart lance l'évaluation projetée 2019 (`app.db.evaluate --years 2019`) |

## 3. Architecture

```
            ┌──────────┐  SQL (p5_grafana, lecture seule)  ┌──────────────┐
navigateur ─► grafana  ├──────────────────────────────────►│  db (p5)     │
 :3000      └──────────┘                                    │ api_requests │
                                                            │ predictions  │
            ┌──────────┐  SQL (p5_api)                      │ ml_models    │
client ─────►   api    ├──────────────────────────────────►│ v_projected_ │
 :8080      └──────────┘                                    │  evaluation  │
                                                            └──────────────┘
```

### 3.1 Service `grafana` (`docker-compose.yml`)

- Image `grafana/grafana-oss:12.4.3` (version exacte, épinglée comme le reste du dépôt).
- Port `127.0.0.1:${GRAFANA_PORT:-3000}:3000` (local uniquement, comme `db`).
- `depends_on: db` (`service_healthy`) ; healthcheck sur `/api/health`.
- Variables : `GF_SECURITY_ADMIN_PASSWORD=${GRAFANA_ADMIN_PASSWORD:?…}`, `GF_AUTH_ANONYMOUS_ENABLED=false`, `GF_USERS_ALLOW_SIGN_UP=false`, `GF_ANALYTICS_REPORTING_ENABLED=false`, `GF_ANALYTICS_CHECK_FOR_UPDATES=false`, `P5_GRAFANA_PASSWORD` (lu par le fichier de datasource).
- Montage en lecture seule : `./grafana/provisioning:/etc/grafana/provisioning:ro`. Pas de volume de données : un `docker compose up` recrée un état identique.

### 3.2 Fichiers de provisionnement (`grafana/provisioning/`)

| Fichier | Rôle |
|---|---|
| `datasources/postgres.yml` | Datasource `uid: p5-postgres`, `db:5432`, base `p5`, utilisateur `p5_grafana`, mot de passe `$P5_GRAFANA_PASSWORD`, `sslmode: disable`, `editable: false` |
| `dashboards/dashboards.yml` | Fournisseur de fichiers : dossier « P5 », `allowUiUpdates: false` |
| `dashboards/api.json` | Tableau de bord « API » (`uid: p5-api`) |
| `dashboards/model.json` | Tableau de bord « Modèle » (`uid: p5-model`) |

### 3.3 Rôle `p5_grafana` (`app/db/create_db.py`)

Ajouté à `Roles` (`grafana`) et créé par `provision()` comme les autres rôles (idempotent : relancer `create_db` sur une installation existante l'ajoute). Mot de passe `P5_GRAFANA_PASSWORD` (`.example.env`, généré par le Quickstart). Droits :

```sql
GRANT CONNECT ON DATABASE p5 TO p5_grafana;
GRANT USAGE ON SCHEMA public TO p5_grafana;
GRANT SELECT (id, user_id, method, path, status_code, duration_ms, created_at)
  ON api_requests TO p5_grafana;
GRANT SELECT (id, api_request_id, building_year_id, model_id,
              energy_use_kbtu, ghg_emissions_tco2e, predicted_at)
  ON predictions TO p5_grafana;
GRANT SELECT ON ml_models, v_projected_evaluation TO p5_grafana;
```

Refusés : `api_requests.request_body`, `response_body`, `client_ip` ; `predictions.input_features` ; `users`, `buildings`, `building_years`, `building_actuals` ; toute écriture. La vue s'exécute avec les droits de son propriétaire : Grafana obtient les erreurs sans accès direct à `building_actuals`.

### 3.4 Quickstart (`scripts/quickstart.sh`)

- Mode image : télécharge `grafana/provisioning/**` (4 fichiers) à côté de `docker-compose.yml`.
- `generate_env` : remplace `change-me-grafana` (`P5_GRAFANA_PASSWORD`) et `change-me-grafana-admin` (`GRAFANA_ADMIN_PASSWORD`) par des valeurs aléatoires ; un `.env` existant sans ces clés les reçoit (relance après mise à jour).
- Après l'ingestion : étape « Évaluation projetée 2019 » (`app.db.evaluate --years 2019`).
- `docker compose up -d --wait api grafana`.
- Vérification ajoutée : `GET /api/health` → 200 ; appel anonyme `GET /api/search` → 401 ; `GET /api/datasources/uid/p5-postgres/health` avec le compte admin → `status: OK`.
- Message final : URL Grafana et « admin / mot de passe : `GRAFANA_ADMIN_PASSWORD` dans `.env` » (jamais affiché en clair).

`ci-install` rejoue le Quickstart du README : ces vérifications y sont donc exécutées sans commande supplémentaire. Ajouter `grafana/**` à ses `paths`.

## 4. Tableaux de bord

Plage par défaut : dernières 24 h ; rafraîchissement 30 s. Les filtres temporels utilisent les macros Grafana (`$__timeFilter(created_at)`, `$__timeGroupAlias(created_at, 1m)`).

### 4.1 « API » (`p5-api`)

| Panneau | Type | Requête (principe) |
|---|---|---|
| Requêtes | stat | `count(*)` sur la période |
| Taux 5xx / taux 4xx | stat (%) | `avg((status_code >= 500)::int)`, idem 4xx |
| Latence p95 | stat (ms) | `percentile_cont(0.95) WITHIN GROUP (ORDER BY duration_ms)` |
| Utilisateurs authentifiés | stat | `count(DISTINCT user_id)` |
| Requêtes / minute par classe | time series | `$__timeGroupAlias`, `CASE` 2xx / 4xx / 5xx |
| Latence p50 / p95 par route | time series | percentiles groupés par `path` (routes `/model/*`, `/buildings`, `/token`) |
| Par route | table | appels, % erreurs, p95, max |
| 20 dernières erreurs | table | `status_code >= 400` : date, méthode, route, code, durée |

Les routes paramétrées (`/buildings/28`) sont regroupées en `/buildings/{id}` par `regexp_replace`.

### 4.2 « Modèle » (`p5-model`)

| Panneau | Type | Requête (principe) |
|---|---|---|
| Prédictions par modèle | stat | `count(*)` joint à `ml_models.name` |
| Par origine | bar gauge | `CASE` : par identifiant (requête + année), saisie libre (requête seule), lot (année seule) |
| Prédictions / heure par modèle | time series | `$__timeGroupAlias(predicted_at, 1h)` |
| Distribution des consommations prédites | histogram | `log10(energy_use_kbtu)` |
| Erreur réelle par année | table | `v_projected_evaluation` hors exclus : MedAPE énergie, MedAPE émissions, `n` par `data_year` et modèle |
| Prédit vs réel | XY chart | `log10` prédit / réel (énergie), échantillon ≤ 2000 points |
| CatBoost vs Kumo | stat + table | paires de prédictions d'un même `api_request_id` : écart relatif médian |

Les panneaux issus de la vue ne dépendent pas de la plage de temps (évaluation par lot).

## 5. Tests

### 5.1 Pytest (base de test existante, marqueur `db`)

- `tests/test_grafana_role.py` : connecté en `p5test_grafana`, lecture des colonnes autorisées OK ; `SELECT request_body`, `client_ip`, `input_features`, `users`, `building_actuals` → `InsufficientPrivilege` ; `INSERT` → refusé.
- `tests/test_grafana_dashboards.py` :
  - structure : JSON valides, `uid` uniques, chaque panneau référence la datasource `p5-postgres`, chaque cible a un `rawSql` ;
  - exécution : chaque `rawSql` est rendu (macros remplacées par du SQL équivalent sur une fenêtre fixe) puis **exécuté sous `p5test_grafana`** sur une base peuplée (requêtes tracées, prédictions API et lot, évaluation projetée) ; aucune erreur, au moins une ligne pour les panneaux alimentés.
- `create_db` : `Roles.with_prefix` et `provision()` créent le rôle `grafana` (tests existants étendus).

### 5.2 Installation

`ci-install` (user et dev) via la vérification du Quickstart (§3.4).

### 5.3 Recette manuelle

Installation vierge, quelques appels (`/predict`, `/compare`, erreurs), captures d'écran des deux tableaux de bord jointes à la PR.

## 6. Documentation

- `docs/monitoring/README.md` : accès, lecture de chaque panneau, droits du rôle, ajout d'un panneau (édition du JSON, test).
- `README.md` : Quickstart (Grafana), ports (`3000`), variables `GRAFANA_PORT`, `GRAFANA_ADMIN_PASSWORD`, `P5_GRAFANA_PASSWORD`.
- `docs/db/README.md` : rôle `p5_grafana` et ses droits.
- `docs/ci-cd/README.md` : `ci-install` vérifie Grafana.

## 7. Risques

| Risque | Parade |
|---|---|
| Rendu des macros dans le test ≠ rendu Grafana | Macros limitées à `$__timeFilter` / `$__timeGroupAlias`, remplacées par leur équivalent documenté ; la vérification de la datasource en `ci-install` et la recette manuelle couvrent le reste |
| Installations existantes sans le rôle | `create_db` idempotent, relancé par le Quickstart ; documenté |
| `.env` existant sans les nouvelles clés | Le Quickstart ajoute les clés manquantes au lieu de régénérer le fichier |
| Ports déjà pris | `GRAFANA_PORT` surchargeable, comme `API_PORT` / `DB_PORT` |
