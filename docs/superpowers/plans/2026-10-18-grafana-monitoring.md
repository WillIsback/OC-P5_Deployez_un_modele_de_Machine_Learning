# Monitoring Grafana — plan d'implémentation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal :** deux tableaux de bord Grafana (« API », « Modèle ») sur PostgreSQL, démarrés et vérifiés par le Quickstart.

**Architecture :** un service `grafana` sans état lit la base `p5` avec un rôle `p5_grafana` en lecture seule (droits par colonne). La datasource et les tableaux de bord sont des fichiers versionnés sous `grafana/provisioning/`. Les requêtes des panneaux sont testées en pytest sous ce rôle ; le Quickstart (rejoué par `ci-install`) vérifie Grafana de bout en bout.

**Tech Stack :** Grafana OSS 12.4.3, PostgreSQL 17, psycopg 3, SQLAlchemy 2, pytest, Bash, Docker Compose v2.

**Spec :** `docs/superpowers/specs/2026-10-18-grafana-monitoring-design.md`

## Global Constraints

- Image : `grafana/grafana-oss:12.4.3` (exacte).
- Port : `127.0.0.1:${GRAFANA_PORT:-3000}:3000`.
- Connexion obligatoire : `GF_AUTH_ANONYMOUS_ENABLED=false`, `GF_USERS_ALLOW_SIGN_UP=false`, admin / `GRAFANA_ADMIN_PASSWORD`.
- Pas de volume Grafana : tout état vient de `grafana/provisioning/` (monté `:ro`).
- Rôle `p5_grafana` (`p5test_grafana` en test), mot de passe `P5_GRAFANA_PASSWORD` ; droits exactement ceux de la spec §3.3, rien de plus.
- Datasource `uid: p5-postgres` ; tableaux de bord `uid: p5-api` et `uid: p5-model`, dossier « P5 ».
- Macros SQL autorisées dans les panneaux : `$__timeFilter(col)`, `$__timeGroupAlias(col, <intervalle>)` uniquement ; aucune variable de template.
- Plage par défaut `now-24h` → `now`, rafraîchissement `30s`.
- Le mot de passe admin n'est jamais affiché en clair par le Quickstart.
- Couverture : seuil global 98 % et diff-cover 90 % (CI bloquante).
- Textes (titres de panneaux, docs, messages) en français ; commits Conventional Commits, terminés par `Refs #64` (dernier commit de la PR : `Closes #64`).

## Review Focus

1. **Installation fraîche sans trafic** : tous les panneaux doivent s'exécuter sans erreur sur des tables vides (taux sans division par zéro, percentiles `NULL`). → test `test_panel_queries_run_on_empty_database` (Task 2).
2. **Requête en cours ou plantée** : une ligne `api_requests` avec `status_code` et `duration_ms` à `NULL` ne doit ni casser une requête ni compter comme une erreur. → ligne dédiée dans le jeu de données de `test_panel_queries_run_under_grafana_role` + assertion sur le taux 5xx (Task 2).
3. **Relance du Quickstart sur une installation existante** (`.env` sans les clés `GRAFANA_*`) : les clés manquantes sont ajoutées, les secrets existants inchangés. → étape de vérification « deuxième exécution » (Task 4).
4. **Aucun appel `/compare` dans la période** : le panneau CatBoost vs Kumo renvoie zéro ligne, pas une erreur. → couvert par le test sur base vide (Task 2) et assertion explicite (Task 3).
5. **Port 3000 déjà pris** sur la machine de l'évaluateur : `GRAFANA_PORT` doit être pris en compte de bout en bout (compose, vérification, message final). → recette avec `GRAFANA_PORT=13000` (Task 4).

---

### Task 1 : rôle `p5_grafana`

**Files :**
- Modify : `app/db/create_db.py` (`Roles`, `GRAFANA_GRANTS`, `_apply_grants`, `provision`, `main`)
- Modify : `.example.env`, `tests/conftest.py` (`TEST_PASSWORDS`)
- Create : `tests/test_grafana_role.py`

**Interfaces :**
- Produces : `Roles.grafana: str` (`"<prefix>_grafana"`) ; `passwords["grafana"]` requis par `provision()` ; `GRAFANA_GRANTS: tuple[str, ...]` (gabarits `{grafana}`) ; fixture `grafana_conn` dans `tests/conftest.py` : connexion SQLAlchemy dans une transaction annulée, `SET LOCAL ROLE p5test_grafana` déjà exécuté, avec un `owner_factory` (sessions propriétaire sur la même connexion, via `SET LOCAL ROLE p5test_owner`) pour peupler avant de basculer. Elle rend `(conn, switch_to_grafana)` où `switch_to_grafana()` exécute le `SET LOCAL ROLE`.

- [ ] **Step 1 : écrire les tests qui échouent** (`tests/test_grafana_role.py`, `pytestmark = pytest.mark.db`)

```python
ALLOWED = [
    "SELECT id, user_id, method, path, status_code, duration_ms, created_at FROM api_requests",
    "SELECT id, api_request_id, building_year_id, model_id, energy_use_kbtu, "
    "ghg_emissions_tco2e, predicted_at FROM predictions",
    "SELECT * FROM ml_models",
    "SELECT * FROM v_projected_evaluation",
]
DENIED = [
    "SELECT request_body FROM api_requests",
    "SELECT response_body FROM api_requests",
    "SELECT client_ip FROM api_requests",
    "SELECT input_features FROM predictions",
    "SELECT * FROM users",
    "SELECT * FROM buildings",
    "SELECT * FROM building_years",
    "SELECT * FROM building_actuals",
    "INSERT INTO ml_models (name, version) VALUES ('x', 'y')",
]


@pytest.mark.parametrize("query", ALLOWED)
def test_grafana_role_reads_allowed_columns(grafana_conn, query):
    ...
    # exécute sous le rôle, ne lève rien


@pytest.mark.parametrize("query", DENIED)
def test_grafana_role_denied(grafana_conn, query):
    ...
    # pytest.raises(sqlalchemy.exc.ProgrammingError) ; cause psycopg.errors.InsufficientPrivilege
    # chaque requête dans un SAVEPOINT (conn.begin_nested()) pour continuer après l'erreur


def test_roles_with_prefix_includes_grafana():
    assert create_db.Roles.with_prefix("p5").grafana == "p5_grafana"
```

Étendre `test_create_db_main_demo_users_opt_in` (`tests/test_db_schema.py`) : son `env` inclut `P5_GRAFANA_PASSWORD`, et : `main()` lit `P5_GRAFANA_PASSWORD` et le transmet sous `passwords["grafana"]`.

- [ ] **Step 2 : vérifier l'échec** — `uv run pytest tests/test_grafana_role.py -v` → échec (`AttributeError: grafana`, rôle inexistant).

- [ ] **Step 3 : implémenter**
  - `Roles` : champ `grafana`, `with_prefix` → `f"{prefix}_grafana"`.
  - `GRAFANA_GRANTS` : les 5 instructions de la spec §3.3 (hors `GRANT CONNECT`), gabarit `{grafana}`.
  - `_apply_grants` : `GRANT CONNECT` à `roles.grafana` aussi, puis `GRAFANA_GRANTS`.
  - `provision` : `_ensure_role(conn, roles.grafana, passwords["grafana"])`.
  - `main` : `"grafana": os.environ["P5_GRAFANA_PASSWORD"]`.
  - `.example.env` : `P5_GRAFANA_PASSWORD=change-me-grafana` et `GRAFANA_ADMIN_PASSWORD=change-me-grafana-admin` (après `P5_MLFLOW_PASSWORD`).
  - `tests/conftest.py` : `TEST_PASSWORDS["grafana"] = "grafana-test"` ; fixture `grafana_conn` (même mécanique que `api_client` de `tests/test_api_role_e2e.py` : connexion admin sur `TEST_DB`, transaction, `SET LOCAL ROLE`).

- [ ] **Step 4 : vérifier** — `uv run pytest tests/test_grafana_role.py tests/test_db_schema.py -v` → PASS ; puis suite complète `uv run pytest --cov=app -q` → PASS, couverture ≥ 98 %.

- [ ] **Step 5 : commit** — `feat(db): rôle p5_grafana en lecture seule (droits par colonne)`

---

### Task 2 : provisionnement Grafana, tableau de bord « API » et banc de test des requêtes

**Files :**
- Create : `grafana/provisioning/datasources/postgres.yml`, `grafana/provisioning/dashboards/dashboards.yml`, `grafana/provisioning/dashboards/api.json`
- Create : `tests/grafana_sql.py` (rendu des macros + extraction des requêtes), `tests/test_grafana_dashboards.py`

**Interfaces :**
- Consumes : fixture `grafana_conn` (Task 1).
- Produces :
  - `DASHBOARD_DIR: Path` (`grafana/provisioning/dashboards`) ;
  - `iter_panel_queries(dashboard: dict) -> Iterator[tuple[str, str]]` : `(titre du panneau, rawSql)`, panneaux imbriqués dans les lignes (`rows`/`panels`) inclus ;
  - `render_macros(sql: str, start: datetime, end: datetime) -> str` ;
  - fixture `monitoring_data` : peuple la base (sous le rôle propriétaire) et rend un `dict` des volumes insérés.

- [ ] **Step 1 : écrire les tests qui échouent**

```python
def test_render_macros():
    start, end = datetime(2026, 10, 1, tzinfo=UTC), datetime(2026, 10, 2, tzinfo=UTC)
    out = render_macros("WHERE $__timeFilter(created_at) GROUP BY $__timeGroupAlias(created_at, 1m)", start, end)
    assert "created_at BETWEEN '2026-10-01T00:00:00+00:00' AND '2026-10-02T00:00:00+00:00'" in out
    assert "to_timestamp(floor(extract(epoch FROM created_at) / 60) * 60) AS \"time\"" in out
    assert "$__" not in out
# intervalles acceptés : 1m, 5m, 1h, 1d ; tout autre macro `$__x` ou variable `$x` → ValueError

def test_dashboards_structure():
    # chaque JSON de DASHBOARD_DIR : uid unique parmi {p5-api, p5-model}, title non vide,
    # time == {"from": "now-24h", "to": "now"}, refresh == "30s",
    # chaque panneau non-"row" : datasource == {"type": "grafana-postgresql-datasource", "uid": "p5-postgres"},
    # chaque cible : rawQuery True, format in {"table", "time_series"}, rawSql non vide

def test_panel_queries_run_on_empty_database(grafana_conn):
    # base sans api_requests ni predictions : chaque rawSql rendu s'exécute sans erreur

def test_panel_queries_run_under_grafana_role(grafana_conn, monitoring_data):
    # chaque rawSql rendu sur [now-1d, now+1h] s'exécute ; tout panneau listé dans
    # FED_PANELS renvoie au moins une ligne

def test_api_error_rate_ignores_unfinished_requests(grafana_conn, monitoring_data):
    # requête du panneau « Taux 5xx » : 1 seule ligne 5xx sur 10 finies (+ 1 ligne
    # status_code NULL) → 10.0 (%), pas 9.09
```

`monitoring_data` insère, horodatées dans la dernière heure : 10 `api_requests` finies (6 × 200 sur `/model/predict`, 1 × 200 sur `/buildings/28`, 1 × 401, 1 × 404, 1 × 503, durées distinctes, `user_id` d'un utilisateur de démo pour les authentifiées) + 1 ligne `status_code`/`duration_ms` `NULL`. Les prédictions et l'évaluation sont ajoutées par la Task 3.

- [ ] **Step 2 : vérifier l'échec** — `uv run pytest tests/test_grafana_dashboards.py -v` → échec (module ou fichiers absents).

- [ ] **Step 3 : implémenter**
  - `postgres.yml` : `apiVersion: 1`, datasource `name: P5 PostgreSQL`, `type: grafana-postgresql-datasource`, `uid: p5-postgres`, `url: db:5432`, `user: p5_grafana`, `jsonData: {database: p5, sslmode: disable, postgresVersion: 1700, timescaledb: false}`, `secureJsonData: {password: ${P5_GRAFANA_PASSWORD}}`, `editable: false`, `isDefault: true`.
  - `dashboards.yml` : fournisseur `file`, `folder: P5`, `allowUiUpdates: false`, `options.path: /etc/grafana/provisioning/dashboards`.
  - `api.json` : panneaux de la spec §4.1, titres exacts : « Requêtes », « Taux 5xx », « Taux 4xx », « Latence p95 », « Utilisateurs authentifiés », « Requêtes par minute », « Latence par route », « Par route », « 20 dernières erreurs ». Les taux ne comptent que les lignes `status_code IS NOT NULL` et sont en pourcentage (`100.0 * avg(...)`). Normalisation des routes : `regexp_replace(path, '/[0-9]+(/|$)', '/{id}\1', 'g')`. « 20 dernières erreurs » : `status_code >= 400 ORDER BY created_at DESC LIMIT 20`.
  - `tests/grafana_sql.py` : `$__timeFilter(c)` → `c BETWEEN '<start iso>' AND '<end iso>'` ; `$__timeGroupAlias(c, N<unité>)` → `to_timestamp(floor(extract(epoch FROM c) / S) * S) AS "time"` (S en secondes).
  - `FED_PANELS` (dans le test) : les 9 panneaux « API ».

- [ ] **Step 4 : vérifier** — `uv run pytest tests/test_grafana_dashboards.py -v` → PASS.

- [ ] **Step 5 : commit** — `feat(monitoring): provisionnement Grafana et tableau de bord API`

---

### Task 3 : tableau de bord « Modèle »

**Files :**
- Create : `grafana/provisioning/dashboards/model.json`
- Modify : `tests/test_grafana_dashboards.py` (jeu de données, `FED_PANELS`, assertions)

**Interfaces :**
- Consumes : `iter_panel_queries`, `render_macros`, `monitoring_data`, `grafana_conn` (Task 2) ; modèles seedés par `provision()` (`catboost-multitarget`, `kumo-tabular-zero-shot`).

- [ ] **Step 1 : écrire les tests qui échouent**
  - Étendre `monitoring_data` (via `tests/synth.py` : `add_year`, et `BuildingActual`) : 2 `building_years` 2019 avec cibles réelles ; 2 prédictions par lot CatBoost (`api_request_id` NULL) ; 3 prédictions API par identifiant ; 1 saisie libre ; 1 paire `/compare` (CatBoost + Kumo sur le même `api_request_id`, énergie 1000 et 1200).

```python
def test_model_origin_breakdown(grafana_conn, monitoring_data):
    # panneau « Par origine » → {"Par identifiant": 5, "Saisie libre": 1, "Lot": 2}

def test_catboost_vs_kumo_median_gap(grafana_conn, monitoring_data):
    # panneau « CatBoost vs Kumo » → écart relatif médian 20.0 (%) : |1200 - 1000| / 1000

def test_catboost_vs_kumo_empty_without_compare(grafana_conn):
    # base vide → 0 ligne ou valeur NULL, sans erreur

def test_real_error_by_year(grafana_conn, monitoring_data):
    # panneau « Erreur réelle par année » → une ligne data_year = 2019, n = 2
```

- [ ] **Step 2 : vérifier l'échec** — `uv run pytest tests/test_grafana_dashboards.py -v` → échec (`model.json` absent).

- [ ] **Step 3 : implémenter `model.json`** (`uid: p5-model`), panneaux de la spec §4.2, titres exacts : « Prédictions par modèle », « Par origine », « Prédictions par heure », « Distribution des consommations prédites », « Erreur réelle par année », « Prédit vs réel », « CatBoost vs Kumo ».
  - Origine : `CASE WHEN api_request_id IS NOT NULL AND building_year_id IS NOT NULL THEN 'Par identifiant' WHEN api_request_id IS NOT NULL THEN 'Saisie libre' ELSE 'Lot' END`.
  - MedAPE : `100 * percentile_cont(0.5) WITHIN GROUP (ORDER BY rel_err_energy)` (et `rel_err_ghg`), `WHERE exclusion_reason IS NULL`, groupé par `data_year, model_name`.
  - « Prédit vs réel » : `log10(predicted_energy_kbtu)`, `log10(actual_energy_kbtu)`, `WHERE actual_energy_kbtu > 0 AND predicted_energy_kbtu > 0 LIMIT 2000`.
  - « CatBoost vs Kumo » : auto-jointure de `predictions` sur `api_request_id` entre les deux `model_id`, `$__timeFilter(predicted_at)`.
  - Ajouter les 7 titres à `FED_PANELS`.

- [ ] **Step 4 : vérifier** — `uv run pytest tests/test_grafana_dashboards.py tests/test_grafana_role.py -v` → PASS.

- [ ] **Step 5 : commit** — `feat(monitoring): tableau de bord Modèle`

---

### Task 4 : service Compose et Quickstart

**Files :**
- Modify : `docker-compose.yml`, `scripts/quickstart.sh`, `.github/workflows/ci-install.yml` (`paths`), `README.md` (prérequis : port 3000)

**Interfaces :**
- Consumes : fichiers `grafana/provisioning/**` (Tasks 2–3), rôle et variables (Task 1).

- [ ] **Step 1 : service `grafana`** dans `docker-compose.yml`, selon la spec §3.1 : variables `GF_*` de Global Constraints, `GF_ANALYTICS_REPORTING_ENABLED=false`, `GF_ANALYTICS_CHECK_FOR_UPDATES=false`, `P5_GRAFANA_PASSWORD: ${P5_GRAFANA_PASSWORD:?définir P5_GRAFANA_PASSWORD dans .env}`, `GF_SECURITY_ADMIN_PASSWORD: ${GRAFANA_ADMIN_PASSWORD:?…}`, montage `./grafana/provisioning:/etc/grafana/provisioning:ro`, `depends_on: db: service_healthy`, healthcheck `wget -qO- http://localhost:3000/api/health` (vérifier que `wget` existe dans l'image : `docker run --rm --entrypoint sh grafana/grafana-oss:12.4.3 -c 'command -v wget'` ; sinon `curl`). Vérifier : `docker compose config -q` → aucune sortie.

- [ ] **Step 2 : `quickstart.sh`**
  - Mode image : après `docker-compose.yml`, télécharger `grafana/provisioning/datasources/postgres.yml` et `grafana/provisioning/dashboards/{dashboards.yml,api.json,model.json}` (créer les dossiers).
  - `generate_env` : substitutions `change-me-grafana-admin`, puis `change-me-grafana`, **avant** `change-me` (préfixes communs).
  - `.env` existant : pour `P5_GRAFANA_PASSWORD` et `GRAFANA_ADMIN_PASSWORD`, `grep -q '^CLÉ='` sinon ajouter `CLÉ=<rand>` (même mécanique que `UID`/`GID`), dans les deux modes. En mode source, `cp .example.env .env` reste inchangé : les valeurs de démonstration `change-me-grafana*` suffisent en local.
  - Après la boucle d'ingestion : `step "Évaluation projetée 2019"` puis `docker compose run --rm -T tools python -m app.db.evaluate --years 2019`.
  - `docker compose up -d --wait api grafana`.
  - Vérification, avec `local grafana="http://localhost:${GRAFANA_PORT:-3000}"` et le mot de passe lu dans `.env` (`sed -n 's/^GRAFANA_ADMIN_PASSWORD=//p' .env`) : `curl -fsS "$grafana/api/health"` ; `curl -s -o /dev/null -w '%{http_code}' "$grafana/api/search"` doit valoir `401` ; `curl -fsS -u "admin:$pw" "$grafana/api/datasources/uid/p5-postgres/health"` doit contenir `"status":"OK"` ; sinon `die` avec un message explicite.
  - Message final : ligne `Monitoring (Grafana)      : $grafana  (admin / GRAFANA_ADMIN_PASSWORD dans .env)`.
  - `-h` : mentionner `GRAFANA_PORT` dans la liste des variables (ajuster la plage `sed -n '2,21p'` si l'en-tête s'allonge).

- [ ] **Step 3 : `ci-install.yml`** — ajouter `"grafana/**"` aux `paths`.

- [ ] **Step 4 : recette d'installation (parcours utilisateur, code de la branche)**

```bash
docker build -t p5-energy:grafana .
W=<scratchpad>/recette-grafana
QUICKSTART_CLONE_FROM=$PWD P5_IMAGE=p5-energy:grafana P5_PULL=0 \
  API_PORT=18080 DB_PORT=15432 GRAFANA_PORT=13000 QUICKSTART_KEEP=1 \
  scripts/quickstart_test.sh user README.md "$W"
```

Attendu : « ✅ Quickstart « Utilisateurs » OK », la vérification Grafana passée, l'URL `http://localhost:13000` affichée.

- [ ] **Step 5 : relance sur installation existante** — retirer `GRAFANA_ADMIN_PASSWORD` et `P5_GRAFANA_PASSWORD` du `.env` de `$W/p5-energy`, noter `SECRET_KEY`, relancer `curl …quickstart.sh | bash` équivalent (`P5_RAW_BASE=file://$PWD bash scripts/quickstart.sh` depuis `$W`, mêmes variables). Attendu : succès, les deux clés de nouveau présentes, `SECRET_KEY` inchangée. Garder l'installation pour la Task 5.

- [ ] **Step 6 : commit** — `feat(install): Grafana démarré et vérifié par le Quickstart`

---

### Task 5 : documentation et recette visuelle

**Files :**
- Create : `docs/monitoring/README.md`
- Modify : `README.md` (Quickstart, ports, tableau des variables : `GRAFANA_PORT`, `GRAFANA_ADMIN_PASSWORD`, `P5_GRAFANA_PASSWORD`), `docs/db/README.md` (tableau des rôles : ligne `p5_grafana`, droits exacts de la spec §3.3), `docs/ci-cd/README.md` (`ci-install` vérifie Grafana)

- [ ] **Step 1 : générer du trafic** sur l'installation de la Task 4 : 5 `/model/predict`, 2 `/model/predict/compare` (bâtiment complet et bâtiment à GFA nulle), 1 `/model/predict/features`, 1 bâtiment inconnu (404), 1 appel sans jeton (401).

- [ ] **Step 2 : captures** des deux tableaux de bord (Playwright, connexion admin) dans `docs/monitoring/img/api.png` et `docs/monitoring/img/model.png` ; vérifier à l'œil que chaque panneau affiche des données et aucune erreur.

- [ ] **Step 3 : `docs/monitoring/README.md`** : accès (URL, compte, `GRAFANA_PORT`), une ligne par panneau (ce qu'il montre, comment le lire), droits du rôle, ajout d'un panneau (éditer le JSON, `uv run pytest tests/test_grafana_dashboards.py`), captures.

- [ ] **Step 4 : vérifier** — liens relatifs valides (`grep -o '](\.[^)]*)' docs/monitoring/README.md` → fichiers existants) ; `uv run pytest --cov=app -q` → PASS ≥ 98 % ; `uv run ruff check . && uv run ruff format --check .` → OK.

- [ ] **Step 5 : nettoyer** l'installation de recette (`docker compose --profile tools down -v` dans `$W/p5-energy`).

- [ ] **Step 6 : commit** — `docs(monitoring): accès, lecture des panneaux, droits du rôle` avec `Closes #64`.
