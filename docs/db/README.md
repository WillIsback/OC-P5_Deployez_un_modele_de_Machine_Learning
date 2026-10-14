# Base de données PostgreSQL (issue #26)

Ce document décrit la base PostgreSQL du projet : schéma, choix techniques, rôles, mise en route et requêtes d'exemple. La conception complète est dans [`docs/superpowers/specs/2026-10-14-postgresql-integration-design.md`](../superpowers/specs/2026-10-14-postgresql-integration-design.md).

## 1. Schéma

```mermaid
erDiagram
    users ||--o{ api_requests : "émet"
    api_requests ||--o| prediction_inputs : "déclenche"
    buildings ||--|{ building_records_raw : "1 par année"
    building_records_raw ||--o| building_features : "préparé en"
    building_records_raw ||--o| building_actuals : "cibles réelles"
    building_records_raw ||--o{ prediction_inputs : "cible"
    prediction_inputs ||--|{ predictions : "produit"
    ml_models ||--o{ predictions : "calcule"

    users {
        bigint id PK
        varchar username UK
        varchar email UK
        varchar full_name
        varchar hashed_password
        boolean is_active
        timestamptz created_at
    }
    api_requests {
        bigint id PK
        uuid request_id UK
        bigint user_id FK
        varchar method
        varchar path
        smallint status_code
        integer duration_ms
        inet client_ip
        jsonb request_body
        jsonb response_body
        timestamptz created_at
    }
    buildings {
        integer ose_building_id PK
        timestamptz created_at
    }
    building_records_raw {
        bigint id PK
        integer building_id FK
        smallint data_year
        varchar source_file
        timestamptz ingested_at
    }
    building_features {
        bigint record_id PK,FK
        varchar dataset_role
        boolean is_training_eligible
        varchar exclusion_reason
        varchar split
        varchar prep_version
        timestamptz prepared_at
    }
    building_actuals {
        bigint record_id PK,FK
        double site_energy_use_kbtu
        double total_ghg_emissions_tco2e
    }
    ml_models {
        bigint id PK
        varchar name
        varchar version
        varchar mlflow_run_id
        varchar artifact_path
        boolean is_active
        timestamptz created_at
    }
    prediction_inputs {
        bigint id PK
        bigint api_request_id FK
        varchar input_source
        bigint building_record_id FK
        timestamptz created_at
    }
    predictions {
        bigint id PK
        bigint prediction_input_id FK
        bigint model_id FK
        double energy_use_kbtu
        double ghg_emissions_tco2e
        timestamptz predicted_at
    }
```

Le diagramme omet les colonnes de données de `building_records_raw` (miroir typé du CSV), `building_features` et `prediction_inputs` (bloc des 17 features du modèle). Le DDL complet est dans [`schema.sql`](schema.sql), généré par `alembic upgrade head --sql` (voir §4). Il ne contient ni les rôles ni les `GRANT` (provisionnés par `app.db.create_db`) et inclut la table `alembic_version`.

## 2. Choix techniques

**D1 — Granularité des traces.** Approche hybride : `api_requests` conserve, en JSONB, le corps de requête et de réponse de tous les appels (par utilisateur) ; les tables typées `prediction_inputs` et `predictions` permettent d'interroger efficacement les entrées et sorties du modèle.

**D2 — Rôle du dataset en base.** La base est la source de vérité : `TrainPipeline` lit PostgreSQL et non plus le CSV.

**D3 — Format du brut.** `building_records_raw` contient des colonnes typées, miroir du CSV (snake_case), PII conservées. La PII n'est lisible que par le propriétaire.

**D4 — Modes de prédiction.** Deux modes coexistent : par `building_id` (`POST /model/predict`, lecture des features préparées) et en saisie libre (`POST /model/predict/features`, `input_source = 'manual'`).

**D5 — Périmètre.** Le résidentiel (`Multifamily*`) est stocké en brut mais absent de `building_features` ; une prédiction sur un tel bâtiment renvoie 422.

**D6 — Éligibilité.** Les filtres qualité (outliers, conformité, cibles non positives ou manquantes) ne concernent que l'entraînement (année 2016, variable `TRAINING_YEAR`). Les années de production ne sont pas filtrées.

**D7 — Cibles réelles.** Les cibles vivent dans `building_actuals`, table séparée ; `building_features` ne contient aucune cible, ce qui exclut toute fuite vers l'API. Le rôle `p5_api` n'y a pas accès.

**D8 — JWT.** Le claim `sub` vaut `str(user.id)` ; l'identité est donc stable même si le nom d'utilisateur change.

**D9 — Modèles.** La table `ml_models` référence le run MLflow par `mlflow_run_id`, sans clé étrangère (bases distinctes). L'API sert les fichiers `models/*.cbm` ; `ml_models` trace le run MLflow qui les a produits. Une seule version active par modèle (index unique partiel).

**D10 — MLflow.** Base `mlflow` séparée dans la même instance PostgreSQL ; pas de troisième conteneur. Le rôle `p5_mlflow` en est propriétaire et n'a aucun droit sur `p5`.

**D11 — Stack.** SQLAlchemy 2.0 (déclaratif typé) et Alembic ; `sqlmodel` est retiré. Driver : `psycopg` 3 (URL `postgresql+psycopg://…`).

### Écarts assumés par rapport à la spec

1. `prediction_inputs.api_request_id` : clé étrangère **sans** `ON DELETE SET NULL`, incompatible avec le CHECK `(input_source = 'batch') = (api_request_id IS NULL)`.
2. `/model/predict/compare` reçoit `{"building_id", "data_year"?}` comme `/model/predict`.
3. `/token` refuse un utilisateur inactif (400), en plus du contrôle `is_active` dans `get_current_user`.
4. `provision()` accepte un préfixe de rôles (`p5` en production, `p5test` en test) pour que les tests n'écrasent pas les mots de passe des rôles de développement sur la même instance.
5. Index `api_requests` en `(user_id, created_at)` et `(path, created_at)` : un btree se parcourt dans les deux sens, `DESC` est inutile.
6. `SELECT` est accordé à `p5_api` sur `api_requests`, `prediction_inputs` et `predictions` (en plus des droits de la spec), nécessaire pour `RETURNING` et `UPDATE`.
7. Le compose comporte un service `tools` séparé (profil `tools`) avec des variables d'environnement explicites au lieu d'un `env_file` : les identifiants admin/propriétaire ne sont jamais transmis au service `api`. Le service `api` ne reçoit que `SECRET_KEY` et `DATABASE_URL`.

### Limites connues

- **`artifact_path` partagé.** Toutes les versions de `catboost-multitarget` pointent vers le même dossier `models/`. Si l'enregistrement dans `ml_models` échoue après l'écriture des fichiers, la version active peut ne pas correspondre aux fichiers `.cbm` servis.
- **Version servie et redémarrage.** L'entraînement écrit `models/version.json` (`name`, `version`, `mlflow_run_id`) après l'enregistrement dans `ml_models`. L'API garde les `.cbm` en mémoire et lit ce fichier au premier chargement : chaque prédiction CatBoost référence la ligne `ml_models` de la version **chargée**, pas forcément la version active. Sans `version.json` (fichiers `.cbm` antérieurs), elle se replie sur la version active ; si la version chargée est absente du registre, la prédiction est refusée (503). **Redémarrer l'API après chaque entraînement** (`docker compose restart api`) pour servir la nouvelle version.
- **`/model/predict/compare` et Kumo.** Si l'appel Kumo échoue, la route renvoie 503 mais conserve la ligne `prediction_inputs` et la prédiction CatBoost déjà calculée : la trace reflète l'appel réellement exécuté.
- **Healthcheck.** Le healthcheck du `Dockerfile` appelle `/docs` toutes les 30 secondes ; ce chemin figure dans `UNTRACED_PATHS` du middleware de trace, il n'écrit donc rien en base.

## 3. Rôles et sécurité

| Rôle | Base | Droits |
|---|---|---|
| `p5_owner` | `p5` | Propriétaire du schéma : migrations, `ingest`, `prepare`, entraînement, `evaluate` |
| `p5_api` | `p5` | `SELECT` : `users`, `buildings`, `building_features`, `ml_models` ; `SELECT (id, building_id, data_year)` sur `building_records_raw` (droit **par colonne**, sans PII) ; `INSERT, UPDATE` : `api_requests` ; `INSERT` : `prediction_inputs`, `predictions` ; `USAGE` sur les séquences d'identité concernées |
| `p5_mlflow` | `mlflow` | Propriétaire de la base `mlflow`, aucun droit sur `p5` |

Le droit par colonne permet à l'API de résoudre `(building_id, data_year)` vers `record_id` sans jamais pouvoir lire une PII. `building_actuals` reste inaccessible à l'API (voir aussi l'écart n°6 pour les `SELECT` supplémentaires).

Les secrets (`password`, `access_token`, `client_secret`, insensible à la casse) sont remplacés par `"***"` à toute profondeur avant stockage dans `api_requests`. Aucun secret réel n'est commité : `.env` est ignoré par git, `.example.env` ne contient que des valeurs factices.

## 4. Mise en route

Prérequis : Docker, et un fichier `.env` créé à partir de l'exemple (`cp .example.env .env`, puis remplacer les valeurs `change-me*` et `SECRET_KEY`). Les mots de passe des rôles sont lus depuis cet environnement.

**Comptes de démonstration.** `create_db` ne crée `johndoe` (actif) et `alice` (inactive), mot de passe `secret`, que si `P5_SEED_DEMO_USERS=1` (valeur de `.example.env`, transmise au service `tools`) ou avec l'option `--demo-users`. Les modèles initiaux de `ml_models` sont créés dans tous les cas. **En production, laisser `P5_SEED_DEMO_USERS` à 0 ou absent** : un compte au mot de passe public donnerait accès à toute l'API.

```bash
docker compose build
docker compose up -d db
docker compose run --rm tools python -m app.db.create_db
docker compose run --rm tools python -m app.db.ingest --year 2016 --csv data/2016_Building_Energy_Benchmarking.csv
docker compose run --rm tools python -m app.db.prepare --year 2016
docker compose up -d api
TOKEN=$(curl -s -X POST localhost:8080/token -d "username=johndoe&password=secret" | python -c "import sys,json;print(json.load(sys.stdin)['access_token'])")
ID=$(docker compose exec -T db psql -U postgres -d p5 -Atc "SELECT r.building_id FROM building_features f JOIN building_records_raw r ON r.id=f.record_id LIMIT 1")
curl -s -X POST localhost:8080/model/predict -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" -d "{\"building_id\": $ID}"
docker compose exec -T db psql -U postgres -d p5 -c "SELECT path, status_code, user_id FROM api_requests ORDER BY id DESC LIMIT 3"
```

La réponse contient `prediction_id` et `request_id`. La table `api_requests` contient une ligne par appel, dont `/model/predict` avec le `user_id` renseigné et `/token` avec le mot de passe masqué. Le port hôte de l'API se change avec `API_PORT` (par défaut `8080`).

Si `docker compose build` échoue faute de nouvelles dépendances dans l'image de base publiée sur GHCR, construire la base localement : `docker build -f Dockerfile.base -t p5-base .` puis `docker compose --profile tools build --build-arg BASE_IMAGE=p5-base`. L'image `:base` devra alors être republiée par le workflow `base-image.yml`.

### Entraînement, évaluation et DDL

```bash
# Entraînement depuis PostgreSQL (écrit models/*.cbm, models/scores.json et
# models/version.json, trace ml_models), puis redémarrage de l'API pour servir la
# nouvelle version
docker compose run --rm tools python -m app.training
docker compose restart api

# Évaluation projetée sur les années de production
docker compose run --rm tools python -m app.db.evaluate --years 2017 2018 2019

# Régénération du DDL livrable (hors conteneur)
DATABASE_OWNER_URL=postgresql+psycopg://x@localhost/p5 uv run alembic upgrade head --sql > docs/db/schema.sql
```

### Années de production 2017–2019

Les fichiers CSV 2017, 2018 et 2019 ne sont **pas** fournis dans `data/` : il faut les y déposer, puis compléter la table `YEAR_COLUMN_RENAMES` de `app/db/ingest.py` (renommage des colonnes source vers les noms du schéma 2016, une entrée par année) avant de les ingérer. Ensuite, pour chaque année :

```bash
docker compose run --rm tools python -m app.db.ingest --year 2017 --csv data/<fichier_2017>.csv
docker compose run --rm tools python -m app.db.prepare --year 2017
```

L'ingestion est idempotente (upsert sur `(building_id, data_year)`) ; les doublons d'`OSEBuildingID` sont dédupliqués (dernier gardé) avec un avertissement.

## 5. Exemples de requêtes SQL

```sql
-- Dernières requêtes d'un utilisateur
SELECT created_at, method, path, status_code, duration_ms
FROM api_requests WHERE user_id = 1 ORDER BY created_at DESC LIMIT 20;

-- Prédictions d'un bâtiment, toutes versions confondues
SELECT r.data_year, m.name, m.version, p.energy_use_kbtu, p.predicted_at
FROM predictions p
JOIN prediction_inputs i ON i.id = p.prediction_input_id
JOIN building_records_raw r ON r.id = i.building_record_id
JOIN ml_models m ON m.id = p.model_id
WHERE r.building_id = 1 ORDER BY p.predicted_at DESC;

-- Erreur médiane relative par année (évaluation projetée)
SELECT data_year, model_version,
       percentile_cont(0.5) WITHIN GROUP (ORDER BY rel_err_energy) AS medape_energy
FROM v_projected_evaluation GROUP BY data_year, model_version ORDER BY data_year;

-- Répartition du jeu d'entraînement
SELECT split, exclusion_reason, count(*) FROM building_features
WHERE dataset_role = 'training' GROUP BY split, exclusion_reason;
```
