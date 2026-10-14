# Intégration PostgreSQL — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remplacer l'auth en mémoire et la préparation de données à la volée par une base PostgreSQL qui stocke le dataset (brut → features → cibles réelles), les utilisateurs, le registre des modèles et la trace complète de chaque appel API et de chaque prédiction.

**Architecture:** SQLAlchemy 2.0 (déclaratif typé) + Alembic décrivent 9 tables et une vue dans la base `p5` ; MLflow utilise une base `mlflow` séparée de la même instance. Un middleware ASGI journalise chaque requête dans `api_requests` ; les routes de prédiction écrivent `prediction_inputs` **avant** d'appeler le modèle et `predictions` après. Des CLIs (`app.db.create_db|ingest|prepare|evaluate`, `app.training`) alimentent et exploitent la base avec un rôle propriétaire ; l'API tourne avec un rôle restreint sans accès aux PII.

**Tech Stack:** Python 3.11/3.12, FastAPI 0.143, Starlette 1.7, SQLAlchemy ≥ 2.0, Alembic, psycopg 3, PostgreSQL 17, pandas 3, CatBoost, MLflow, pytest, Docker Compose.

**Spec:** `docs/superpowers/specs/2026-10-14-postgresql-integration-design.md`

## Global Constraints

- Toutes les communications, messages d'erreur API, logs et commentaires sont en **français** avec accents ; identifiants de code en anglais/snake_case.
- URLs SQLAlchemy au format `postgresql+psycopg://user:password@host:port/db`.
- Noms de modèles exacts : `catboost-multitarget`, `kumo-tabular-zero-shot`.
- Codes HTTP : bâtiment inconnu → **404** ; année absente → **404** ; hors périmètre → **422** ; modèle en échec / aucun modèle actif / BDD indisponible → **503**.
- Clés masquées dans les traces : `password`, `access_token`, `client_secret` (insensible à la casse) → `"***"`.
- Année d'entraînement : `2016` (variable d'env `TRAINING_YEAR`). Split : `test_size=0.2`, `random_state=42`.
- Jamais de prédiction sans ligne `prediction_inputs` commitée au préalable.
- Le rôle `p5_api` n'a **aucun** accès aux colonnes PII de `building_records_raw` ni à `building_actuals`.
- Aucun secret réel commité ; `.env` reste ignoré par git.
- Commits : messages conventionnels en français, terminés par `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- **Écarts assumés par rapport à la spec** (à reporter dans `docs/db/README.md`) :
  1. `prediction_inputs.api_request_id` : FK **sans** `ON DELETE SET NULL` (incompatible avec le CHECK `(input_source = 'batch') = (api_request_id IS NULL)`).
  2. `/model/predict/compare` reçoit `{"building_id", "data_year"?}` comme `/model/predict`.
  3. `/token` refuse un utilisateur inactif (400), en plus du contrôle `is_active` dans `get_current_user`.
  4. `provision()` accepte un préfixe de rôles (`p5` en prod, `p5test` en test) pour que les tests n'écrasent pas les mots de passe des rôles de dev sur la même instance.
  5. Index `api_requests` en `(user_id, created_at)` / `(path, created_at)` (un btree se parcourt dans les deux sens ; `DESC` inutile).

## Review Focus

1. **Corps de requête inhabituels** (binaire, non UTF-8, > 64 Kio, JSON contenant `\u0000` que JSONB refuse) → la requête est traitée normalement et la trace stocke `{"_raw": "<…>"}` au lieu d'échouer en 503. Testé en Task 4.
2. **Client sans IP valide** (le `TestClient` envoie `"testclient"`, un proxy peut envoyer autre chose) et **chemin > 255 caractères** → `client_ip` NULL et chemin tronqué, pas d'erreur d'insertion. Testé en Task 10.
3. **Ingestion relancée ou fichier avec doublons d'`OSEBuildingID`** → aucune ligne dupliquée, valeurs mises à jour, doublons dédupliqués (dernier gardé) avec avertissement. Testé en Task 6.
4. **Bâtiment de production avec une feature obligatoire manquante** (ex. latitude NULL en 2018) → ignoré par `prepare` avec avertissement ; l'API répond 422 au lieu de planter sur une contrainte NOT NULL. Testé en Task 7.
5. **Token valide d'un utilisateur supprimé ou désactivé après émission** → 401. Testé en Task 9.

---

## File Structure

| Fichier | Rôle |
|---|---|
| `app/db/__init__.py` | Package BDD |
| `app/db/session.py` | Engine API (`DATABASE_URL`), `SessionLocal`, `get_session`, `SessionDep`, `owner_session_factory()` |
| `app/db/models.py` | Tables SQLAlchemy (9) + mixin `FeatureColumns` |
| `app/db/mapping.py` | Correspondances CSV ↔ SQL, conversion de types (`coerce_row`, `features_to_sql`, `features_from_sql`, `feature_values`) |
| `app/db/views.py` | SQL de la vue `v_projected_evaluation` |
| `app/db/migrations/` | Environnement + révision Alembic |
| `app/db/create_db.py` | Provisionnement idempotent (rôles, bases, migrations, grants, seed) |
| `app/db/registry.py` | Noms des modèles, `active_model`, `register_model`, `NoActiveModel` |
| `app/db/redaction.py` | Parsing + masquage des corps pour les traces |
| `app/db/ingest.py` | CLI CSV → `buildings` / `building_records_raw` / `building_actuals` |
| `app/db/prepare.py` | CLI brut → `building_features` |
| `app/db/training_data.py` | Lecture du jeu d'entraînement depuis Postgres |
| `app/db/evaluate.py` | CLI d'évaluation projetée |
| `app/middleware/__init__.py`, `app/middleware/trace.py` | Middleware ASGI de traçabilité |
| `app/core/prediction_service.py` | Résolution bâtiment, écriture inputs/predictions, appel des modèles |
| `app/training/data_processing.py` | + `filter_scope`, `apply_common_corrections`, `flag_training_eligibility`, `assign_split` |
| `app/training/pipeline.py` | + `TrainingData`, chemin `training_data=`, `mlflow_run_id` |
| `app/training/__main__.py` | Entraîne depuis Postgres et enregistre la version dans `ml_models` |
| `app/core/security.py`, `app/routers/auth.py` | Auth sur la table `users`, `sub = id` |
| `app/routers/model.py`, `app/schemas/api.py`, `app/main.py` | Routes de prédiction tracées |
| `app/core/model_service.py` | + `predict_frame` |
| `alembic.ini`, `docker-compose.yml`, `.example.env` | Outillage |
| `docs/db/README.md`, `docs/db/schema.sql` | Livrables documentaires |
| `tests/conftest.py`, `tests/synth.py` | Fixtures BDD + données synthétiques partagées |

Supprimés : `app/core/database_service.py`, `app/schemas/database.py`, `fake_users_db`, dépendance `sqlmodel`.

---

### Task 1: Socle BDD (dépendances, session, nettoyage SQLModel)

**Files:**
- Modify: `pyproject.toml`
- Create: `app/db/__init__.py`, `app/db/session.py`
- Delete: `app/core/database_service.py`, `app/schemas/database.py`
- Test: `tests/test_db_session.py`

**Interfaces:**
- Produces: `app.db.session.DATABASE_URL: str`, `engine`, `SessionLocal: sessionmaker[Session]`, `get_session() -> Iterator[Session]`, `SessionDep`, `owner_session_factory() -> sessionmaker[Session]` (lève `RuntimeError` si `DATABASE_OWNER_URL` absent). Toute ouverture de session côté API passe par `session.SessionLocal` (attribut de module, patché par les tests).

- [ ] **Step 1: Mettre à jour les dépendances**

```bash
uv remove sqlmodel
uv add "sqlalchemy>=2.0" "alembic>=1.13" "psycopg[binary]>=3.2"
```

Puis dans `pyproject.toml`, remplacer le bloc `[tool.coverage.run]` et ajouter la config pytest :

```toml
[tool.coverage.run]
omit = [
    "app/internal/*",
    "app/db/migrations/*",
]

[tool.pytest.ini_options]
markers = [
    "db: nécessite un PostgreSQL de test (TEST_DATABASE_ADMIN_URL)",
]
```

- [ ] **Step 2: Supprimer le scaffolding SQLModel**

```bash
git rm app/core/database_service.py app/schemas/database.py
```

- [ ] **Step 3: Write the failing test**

`tests/test_db_session.py` :

```python
"""Tests unitaires du module de session (sans base)."""

import sys
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db import session as db_session


def test_get_session_yields_session_from_factory():
    gen = db_session.get_session()
    s = next(gen)
    assert isinstance(s, Session)
    gen.close()


def test_owner_session_factory_requires_env(monkeypatch):
    monkeypatch.delenv("DATABASE_OWNER_URL", raising=False)
    with pytest.raises(RuntimeError, match="DATABASE_OWNER_URL"):
        db_session.owner_session_factory()


def test_owner_session_factory_uses_env(monkeypatch):
    monkeypatch.setenv(
        "DATABASE_OWNER_URL", "postgresql+psycopg://u:p@localhost:5432/p5"
    )
    factory = db_session.owner_session_factory()
    assert factory.kw["bind"].url.database == "p5"
```

- [ ] **Step 4: Run test to verify it fails**

Run: `uv run pytest tests/test_db_session.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.db'`

- [ ] **Step 5: Write minimal implementation**

`app/db/__init__.py` :

```python
"""Couche d'accès PostgreSQL (schéma `p5`)."""
```

`app/db/session.py` :

```python
"""Sessions SQLAlchemy : rôle API (requêtes HTTP) et rôle propriétaire (CLIs)."""

from __future__ import annotations

import os
from collections.abc import Iterator
from typing import Annotated

from dotenv import load_dotenv
from fastapi import Depends
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

load_dotenv()

# Rôle restreint `p5_api` : aucune PII, aucune cible réelle (spec §5.2).
DATABASE_URL = os.getenv(
    "DATABASE_URL", "postgresql+psycopg://p5_api:p5_api@localhost:5432/p5"
)

# create_engine est paresseux : aucune connexion n'est ouverte à l'import.
engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


def get_session() -> Iterator[Session]:
    # `SessionLocal` est relu à chaque appel : les tests le remplacent.
    with SessionLocal() as session:
        yield session


SessionDep = Annotated[Session, Depends(get_session)]


def owner_session_factory() -> sessionmaker[Session]:
    """Fabrique de sessions du rôle propriétaire (ingestion, préparation, entraînement)."""
    url = os.getenv("DATABASE_OWNER_URL")
    if not url:
        raise RuntimeError(
            "DATABASE_OWNER_URL non défini : renseignez-le dans .env "
            "(voir .example.env)."
        )
    return sessionmaker(bind=create_engine(url), expire_on_commit=False)
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest tests/test_db_session.py -v`
Expected: 3 PASS. Puis `uv run pytest -q` : la suite existante reste verte.

- [ ] **Step 7: Commit**

```bash
git add pyproject.toml uv.lock app/db tests/test_db_session.py
git commit -m "build: socle SQLAlchemy/Alembic/psycopg, retrait de SQLModel (#26)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: Correspondances de colonnes et modèles ORM

**Files:**
- Create: `app/db/models.py`, `app/db/mapping.py`
- Test: `tests/test_db_models.py`

**Interfaces:**
- Consumes: `app.schemas.api.FEATURE_COLUMNS`, `TARGETS`.
- Produces:
  - `app.db.models`: `Base`, `FeatureColumns`, `User`, `ApiRequest`, `Building`, `BuildingRecordRaw`, `BuildingFeatures`, `BuildingActual`, `MlModel`, `PredictionInput`, `Prediction`.
  - `app.db.mapping`: `FEATURE_SQL: dict[str, str]` (nom `FEATURE_COLUMNS` → colonne SQL, dans l'ordre de `FEATURE_COLUMNS`), `FLAG_COLUMNS: tuple[str, str]`, `TARGET_SQL: dict[str, str]` (colonne CSV cible → colonne `building_actuals`), `RAW_SQL: dict[str, str]` (colonne CSV 2016 → colonne `building_records_raw`), `to_python(value) -> Any`, `coerce_row(model_cls, row: Mapping[str, Any]) -> dict[str, Any]`, `features_to_sql(features: Mapping[str, Any]) -> dict[str, Any]`, `features_from_sql(obj) -> dict[str, Any]` (clés `FEATURE_COLUMNS`, flags en `int`), `feature_values(obj) -> dict[str, Any]` (clés SQL, valeurs telles quelles).

- [ ] **Step 1: Write the failing test**

`tests/test_db_models.py` :

```python
"""Tests unitaires du schéma ORM et des correspondances (sans base)."""

import math
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db import mapping
from app.db.models import (
    Base,
    BuildingActual,
    BuildingFeatures,
    BuildingRecordRaw,
    PredictionInput,
)
from app.schemas.api import FEATURE_COLUMNS


def test_all_tables_declared():
    assert set(Base.metadata.tables) == {
        "users",
        "api_requests",
        "buildings",
        "building_records_raw",
        "building_features",
        "building_actuals",
        "ml_models",
        "prediction_inputs",
        "predictions",
    }


def test_feature_sql_covers_feature_columns_in_order():
    assert list(mapping.FEATURE_SQL) == FEATURE_COLUMNS


def test_feature_block_shared_by_features_and_inputs():
    for col in mapping.FEATURE_SQL.values():
        assert col in BuildingFeatures.__table__.columns
        assert col in PredictionInput.__table__.columns


def test_raw_sql_targets_existing_columns():
    raw_cols = BuildingRecordRaw.__table__.columns
    assert len(mapping.RAW_SQL) == 46
    for sql_col in mapping.RAW_SQL.values():
        assert sql_col in raw_cols


def test_target_sql_targets_actuals():
    for col in mapping.TARGET_SQL.values():
        assert col in BuildingActual.__table__.columns


def test_to_python_handles_numpy_and_nan():
    assert mapping.to_python(np.int64(3)) == 3
    assert type(mapping.to_python(np.int64(3))) is int
    assert mapping.to_python(float("nan")) is None
    assert mapping.to_python(np.float64("nan")) is None
    assert mapping.to_python(None) is None


def test_coerce_row_by_column_type():
    row = mapping.coerce_row(
        BuildingRecordRaw,
        {
            "zip_code": 98101.0,
            "year_built": np.float64(1990.0),
            "default_data": "False",
            "latitude": np.float64(47.6),
            "comments": float("nan"),
        },
    )
    assert row == {
        "zip_code": "98101",
        "year_built": 1990,
        "default_data": False,
        "latitude": 47.6,
        "comments": None,
    }


def test_features_roundtrip():
    features = {
        "BuildingType": "NonResidential",
        "PrimaryPropertyType": "Office",
        "Neighborhood": "DOWNTOWN",
        "Latitude": 47.6,
        "Longitude": -122.3,
        "YearBuilt": 1990,
        "NumberofBuildings": 1.0,
        "NumberofFloors": 4,
        "PropertyGFAParking": 0,
        "PropertyGFABuilding(s)": 15000,
        "LargestPropertyUseType": "Office",
        "SecondLargestPropertyUseType": "UNKNOWN",
        "SecondLargestPropertyUseTypeGFA": float("nan"),
        "ThirdLargestPropertyUseType": "UNKNOWN",
        "ThirdLargestPropertyUseTypeGFA": float("nan"),
        "Has_NaturalGas": 1,
        "Has_Steam": 0,
    }
    sql = mapping.features_to_sql(features)
    assert sql["has_natural_gas"] is True
    assert sql["has_steam"] is False
    assert sql["second_largest_property_use_type_gfa"] is None
    obj = PredictionInput(input_source="manual", **sql)
    back = mapping.features_from_sql(obj)
    assert list(back) == FEATURE_COLUMNS
    assert back["Has_NaturalGas"] == 1
    assert back["Has_Steam"] == 0
    assert back["SecondLargestPropertyUseTypeGFA"] is None
    assert mapping.feature_values(obj)["latitude"] == 47.6
    assert not math.isnan(back["Latitude"])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_db_models.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.db.mapping'`

- [ ] **Step 3: Write `app/db/models.py`**

```python
"""Tables SQLAlchemy 2.0 du schéma `p5` (spec §3)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Double,
    ForeignKey,
    Identity,
    Index,
    Integer,
    MetaData,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import INET, JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# Noms de contraintes déterministes : indispensable pour des migrations stables.
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


def _pk() -> Mapped[int]:
    return mapped_column(BigInteger, Identity(always=True), primary_key=True)


def _created_at() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), server_default=func.now())


class FeatureColumns:
    """Bloc des 17 features (spec §3.2), partagé par features et inputs."""

    building_type: Mapped[str] = mapped_column(String(64))
    primary_property_type: Mapped[str] = mapped_column(String(64))
    neighborhood: Mapped[str] = mapped_column(String(64))
    latitude: Mapped[float] = mapped_column(Double)
    longitude: Mapped[float] = mapped_column(Double)
    year_built: Mapped[int] = mapped_column(SmallInteger)
    number_of_buildings: Mapped[float | None] = mapped_column(Double)
    number_of_floors: Mapped[int] = mapped_column(SmallInteger)
    property_gfa_parking: Mapped[int] = mapped_column(Integer)
    property_gfa_buildings: Mapped[int] = mapped_column(Integer)
    largest_property_use_type: Mapped[str] = mapped_column(String(64))
    second_largest_property_use_type: Mapped[str] = mapped_column(String(64))
    second_largest_property_use_type_gfa: Mapped[float | None] = mapped_column(Double)
    third_largest_property_use_type: Mapped[str] = mapped_column(String(64))
    third_largest_property_use_type_gfa: Mapped[float | None] = mapped_column(Double)
    has_natural_gas: Mapped[bool] = mapped_column(Boolean)
    has_steam: Mapped[bool] = mapped_column(Boolean)


# --- Auth et traçabilité ----------------------------------------------------


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = _pk()
    username: Mapped[str] = mapped_column(String(50), unique=True)
    email: Mapped[str | None] = mapped_column(String(255), unique=True)
    full_name: Mapped[str | None] = mapped_column(String(255))
    hashed_password: Mapped[str] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
    created_at: Mapped[datetime] = _created_at()


class ApiRequest(Base):
    __tablename__ = "api_requests"
    __table_args__ = (
        Index("ix_api_requests_user_created", "user_id", "created_at"),
        Index("ix_api_requests_path_created", "path", "created_at"),
    )

    id: Mapped[int] = _pk()
    request_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), unique=True)
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    method: Mapped[str] = mapped_column(String(10))
    path: Mapped[str] = mapped_column(String(255))
    status_code: Mapped[int | None] = mapped_column(SmallInteger)
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    client_ip: Mapped[str | None] = mapped_column(INET)
    request_body: Mapped[Any | None] = mapped_column(JSONB)
    response_body: Mapped[Any | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = _created_at()


# --- Dataset -----------------------------------------------------------------


class Building(Base):
    __tablename__ = "buildings"

    ose_building_id: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=False
    )
    created_at: Mapped[datetime] = _created_at()


class BuildingRecordRaw(Base):
    """Ligne CSV normalisée d'une année ; PII comprises (spec §3.3)."""

    __tablename__ = "building_records_raw"
    __table_args__ = (
        UniqueConstraint("building_id", "data_year"),
        CheckConstraint("data_year BETWEEN 2015 AND 2100", name="data_year_range"),
        Index("ix_building_records_raw_data_year", "data_year"),
    )

    id: Mapped[int] = _pk()
    building_id: Mapped[int] = mapped_column(ForeignKey("buildings.ose_building_id"))
    data_year: Mapped[int] = mapped_column(SmallInteger)
    building_type: Mapped[str | None] = mapped_column(String(64))
    primary_property_type: Mapped[str | None] = mapped_column(String(64))
    property_name: Mapped[str | None] = mapped_column(String(255))
    address: Mapped[str | None] = mapped_column(String(255))
    city: Mapped[str | None] = mapped_column(String(64))
    state: Mapped[str | None] = mapped_column(String(8))
    zip_code: Mapped[str | None] = mapped_column(String(10))
    tax_parcel_identification_number: Mapped[str | None] = mapped_column(String(64))
    council_district_code: Mapped[int | None] = mapped_column(SmallInteger)
    neighborhood: Mapped[str | None] = mapped_column(String(64))
    latitude: Mapped[float | None] = mapped_column(Double)
    longitude: Mapped[float | None] = mapped_column(Double)
    year_built: Mapped[int | None] = mapped_column(SmallInteger)
    number_of_buildings: Mapped[float | None] = mapped_column(Double)
    number_of_floors: Mapped[int | None] = mapped_column(SmallInteger)
    property_gfa_total: Mapped[int | None] = mapped_column(Integer)
    property_gfa_parking: Mapped[int | None] = mapped_column(Integer)
    property_gfa_buildings: Mapped[int | None] = mapped_column(Integer)
    list_of_all_property_use_types: Mapped[str | None] = mapped_column(Text)
    largest_property_use_type: Mapped[str | None] = mapped_column(String(64))
    largest_property_use_type_gfa: Mapped[float | None] = mapped_column(Double)
    second_largest_property_use_type: Mapped[str | None] = mapped_column(String(64))
    second_largest_property_use_type_gfa: Mapped[float | None] = mapped_column(Double)
    third_largest_property_use_type: Mapped[str | None] = mapped_column(String(64))
    third_largest_property_use_type_gfa: Mapped[float | None] = mapped_column(Double)
    years_energy_star_certified: Mapped[str | None] = mapped_column(String(255))
    energy_star_score: Mapped[float | None] = mapped_column(Double)
    site_eui_kbtu_sf: Mapped[float | None] = mapped_column(Double)
    site_eui_wn_kbtu_sf: Mapped[float | None] = mapped_column(Double)
    source_eui_kbtu_sf: Mapped[float | None] = mapped_column(Double)
    source_eui_wn_kbtu_sf: Mapped[float | None] = mapped_column(Double)
    site_energy_use_kbtu: Mapped[float | None] = mapped_column(Double)
    site_energy_use_wn_kbtu: Mapped[float | None] = mapped_column(Double)
    steam_use_kbtu: Mapped[float | None] = mapped_column(Double)
    electricity_kwh: Mapped[float | None] = mapped_column(Double)
    electricity_kbtu: Mapped[float | None] = mapped_column(Double)
    natural_gas_therms: Mapped[float | None] = mapped_column(Double)
    natural_gas_kbtu: Mapped[float | None] = mapped_column(Double)
    default_data: Mapped[bool | None] = mapped_column(Boolean)
    comments: Mapped[str | None] = mapped_column(Text)
    compliance_status: Mapped[str | None] = mapped_column(String(64))
    outlier: Mapped[str | None] = mapped_column(String(32))
    total_ghg_emissions: Mapped[float | None] = mapped_column(Double)
    ghg_emissions_intensity: Mapped[float | None] = mapped_column(Double)
    source_file: Mapped[str] = mapped_column(String(255))
    ingested_at: Mapped[datetime] = _created_at()


class BuildingFeatures(FeatureColumns, Base):
    """Deuxième temps de la préparation : uniquement le périmètre du modèle."""

    __tablename__ = "building_features"
    __table_args__ = (
        CheckConstraint(
            "dataset_role IN ('training', 'production')", name="dataset_role_values"
        ),
        CheckConstraint("split IN ('train', 'test')", name="split_values"),
        CheckConstraint(
            "exclusion_reason IN ('outlier', 'non_compliant', "
            "'non_positive_target', 'missing_target')",
            name="exclusion_reason_values",
        ),
        CheckConstraint(
            "NOT is_training_eligible OR dataset_role = 'training'",
            name="eligible_only_training",
        ),
        CheckConstraint(
            "(split IS NOT NULL) = is_training_eligible", name="split_iff_eligible"
        ),
        CheckConstraint(
            "(exclusion_reason IS NOT NULL) = "
            "(dataset_role = 'training' AND NOT is_training_eligible)",
            name="reason_iff_excluded",
        ),
        Index(
            "ix_building_features_role_eligible", "dataset_role", "is_training_eligible"
        ),
    )

    record_id: Mapped[int] = mapped_column(
        ForeignKey("building_records_raw.id", ondelete="CASCADE"), primary_key=True
    )
    dataset_role: Mapped[str] = mapped_column(String(16))
    is_training_eligible: Mapped[bool] = mapped_column(Boolean)
    exclusion_reason: Mapped[str | None] = mapped_column(String(32))
    split: Mapped[str | None] = mapped_column(String(8))
    prep_version: Mapped[str] = mapped_column(String(32))
    prepared_at: Mapped[datetime] = _created_at()


class BuildingActual(Base):
    """Cibles réelles, isolées des features (jamais lues par l'API)."""

    __tablename__ = "building_actuals"

    record_id: Mapped[int] = mapped_column(
        ForeignKey("building_records_raw.id", ondelete="CASCADE"), primary_key=True
    )
    site_energy_use_kbtu: Mapped[float | None] = mapped_column(Double)
    total_ghg_emissions_tco2e: Mapped[float | None] = mapped_column(Double)


# --- Modèle ------------------------------------------------------------------


class MlModel(Base):
    __tablename__ = "ml_models"
    __table_args__ = (
        UniqueConstraint("name", "version"),
        # Une seule version active par nom de modèle.
        Index(
            "uq_ml_models_active_name",
            "name",
            unique=True,
            postgresql_where=text("is_active"),
        ),
    )

    id: Mapped[int] = _pk()
    name: Mapped[str] = mapped_column(String(64))
    version: Mapped[str] = mapped_column(String(32))
    mlflow_run_id: Mapped[str | None] = mapped_column(String(64))
    artifact_path: Mapped[str | None] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    created_at: Mapped[datetime] = _created_at()


class PredictionInput(FeatureColumns, Base):
    """Snapshot figé de ce qui est envoyé au modèle."""

    __tablename__ = "prediction_inputs"
    __table_args__ = (
        CheckConstraint(
            "input_source IN ('building_id', 'manual', 'batch')",
            name="input_source_values",
        ),
        CheckConstraint(
            "input_source = 'manual' OR building_record_id IS NOT NULL",
            name="record_required",
        ),
        CheckConstraint(
            "input_source <> 'manual' OR building_record_id IS NULL",
            name="manual_without_record",
        ),
        CheckConstraint(
            "(input_source = 'batch') = (api_request_id IS NULL)",
            name="batch_iff_no_request",
        ),
        Index("ix_prediction_inputs_api_request_id", "api_request_id"),
        Index("ix_prediction_inputs_building_record_id", "building_record_id"),
    )

    id: Mapped[int] = _pk()
    # Pas de ON DELETE SET NULL : incompatible avec le CHECK batch_iff_no_request.
    api_request_id: Mapped[int | None] = mapped_column(ForeignKey("api_requests.id"))
    input_source: Mapped[str] = mapped_column(String(16))
    building_record_id: Mapped[int | None] = mapped_column(
        ForeignKey("building_records_raw.id")
    )
    created_at: Mapped[datetime] = _created_at()


class Prediction(Base):
    __tablename__ = "predictions"
    __table_args__ = (
        UniqueConstraint("prediction_input_id", "model_id"),
        Index("ix_predictions_model_predicted", "model_id", "predicted_at"),
    )

    id: Mapped[int] = _pk()
    prediction_input_id: Mapped[int] = mapped_column(
        ForeignKey("prediction_inputs.id", ondelete="CASCADE")
    )
    model_id: Mapped[int] = mapped_column(ForeignKey("ml_models.id"))
    energy_use_kbtu: Mapped[float] = mapped_column(Double)
    ghg_emissions_tco2e: Mapped[float] = mapped_column(Double)
    predicted_at: Mapped[datetime] = _created_at()
```

- [ ] **Step 4: Write `app/db/mapping.py`**

```python
"""Correspondances CSV ↔ SQL et conversion des valeurs pandas/numpy."""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any

import numpy as np
import pandas as pd
from sqlalchemy import Boolean, Double, Integer, String

from app.db.models import BuildingFeatures
from app.schemas.api import TARGETS

# Ordre identique à FEATURE_COLUMNS (vérifié par les tests).
FEATURE_SQL: dict[str, str] = {
    "BuildingType": "building_type",
    "PrimaryPropertyType": "primary_property_type",
    "Neighborhood": "neighborhood",
    "Latitude": "latitude",
    "Longitude": "longitude",
    "YearBuilt": "year_built",
    "NumberofBuildings": "number_of_buildings",
    "NumberofFloors": "number_of_floors",
    "PropertyGFAParking": "property_gfa_parking",
    "PropertyGFABuilding(s)": "property_gfa_buildings",
    "LargestPropertyUseType": "largest_property_use_type",
    "SecondLargestPropertyUseType": "second_largest_property_use_type",
    "SecondLargestPropertyUseTypeGFA": "second_largest_property_use_type_gfa",
    "ThirdLargestPropertyUseType": "third_largest_property_use_type",
    "ThirdLargestPropertyUseTypeGFA": "third_largest_property_use_type_gfa",
    "Has_NaturalGas": "has_natural_gas",
    "Has_Steam": "has_steam",
}
FLAG_COLUMNS = ("Has_NaturalGas", "Has_Steam")

TARGET_SQL: dict[str, str] = {
    TARGETS["energy"]["column"]: "site_energy_use_kbtu",
    TARGETS["emissions"]["column"]: "total_ghg_emissions_tco2e",
}

# Colonnes du CSV 2016 → colonnes de building_records_raw.
RAW_SQL: dict[str, str] = {
    "OSEBuildingID": "building_id",
    "DataYear": "data_year",
    "BuildingType": "building_type",
    "PrimaryPropertyType": "primary_property_type",
    "PropertyName": "property_name",
    "Address": "address",
    "City": "city",
    "State": "state",
    "ZipCode": "zip_code",
    "TaxParcelIdentificationNumber": "tax_parcel_identification_number",
    "CouncilDistrictCode": "council_district_code",
    "Neighborhood": "neighborhood",
    "Latitude": "latitude",
    "Longitude": "longitude",
    "YearBuilt": "year_built",
    "NumberofBuildings": "number_of_buildings",
    "NumberofFloors": "number_of_floors",
    "PropertyGFATotal": "property_gfa_total",
    "PropertyGFAParking": "property_gfa_parking",
    "PropertyGFABuilding(s)": "property_gfa_buildings",
    "ListOfAllPropertyUseTypes": "list_of_all_property_use_types",
    "LargestPropertyUseType": "largest_property_use_type",
    "LargestPropertyUseTypeGFA": "largest_property_use_type_gfa",
    "SecondLargestPropertyUseType": "second_largest_property_use_type",
    "SecondLargestPropertyUseTypeGFA": "second_largest_property_use_type_gfa",
    "ThirdLargestPropertyUseType": "third_largest_property_use_type",
    "ThirdLargestPropertyUseTypeGFA": "third_largest_property_use_type_gfa",
    "YearsENERGYSTARCertified": "years_energy_star_certified",
    "ENERGYSTARScore": "energy_star_score",
    "SiteEUI(kBtu/sf)": "site_eui_kbtu_sf",
    "SiteEUIWN(kBtu/sf)": "site_eui_wn_kbtu_sf",
    "SourceEUI(kBtu/sf)": "source_eui_kbtu_sf",
    "SourceEUIWN(kBtu/sf)": "source_eui_wn_kbtu_sf",
    "SiteEnergyUse(kBtu)": "site_energy_use_kbtu",
    "SiteEnergyUseWN(kBtu)": "site_energy_use_wn_kbtu",
    "SteamUse(kBtu)": "steam_use_kbtu",
    "Electricity(kWh)": "electricity_kwh",
    "Electricity(kBtu)": "electricity_kbtu",
    "NaturalGas(therms)": "natural_gas_therms",
    "NaturalGas(kBtu)": "natural_gas_kbtu",
    "DefaultData": "default_data",
    "Comments": "comments",
    "ComplianceStatus": "compliance_status",
    "Outlier": "outlier",
    "TotalGHGEmissions": "total_ghg_emissions",
    "GHGEmissionsIntensity": "ghg_emissions_intensity",
}

_TRUE_STRINGS = frozenset({"true", "t", "1", "yes", "y"})


def to_python(value: Any) -> Any:
    """Scalaire numpy/pandas → type Python natif ; NaN/NA → None."""
    if value is None or value is pd.NA:
        return None
    if isinstance(value, np.generic):
        value = value.item()
    if isinstance(value, float) and math.isnan(value):
        return None
    return value


def _coerce(value: Any, sqltype: Any) -> Any:
    value = to_python(value)
    if value is None:
        return None
    if isinstance(sqltype, Boolean):
        if isinstance(value, str):
            return value.strip().lower() in _TRUE_STRINGS
        return bool(value)
    if isinstance(sqltype, String):  # couvre aussi Text
        if isinstance(value, float) and value.is_integer():
            return str(int(value))  # ex. ZipCode lu en float : 98101.0 → "98101"
        return str(value)
    if isinstance(sqltype, Integer):  # couvre SmallInteger et BigInteger
        return int(value)
    if isinstance(sqltype, Double):
        return float(value)
    return value


def coerce_row(model_cls: Any, row: Mapping[str, Any]) -> dict[str, Any]:
    """Convertit chaque valeur selon le type SQL de la colonne cible."""
    columns = model_cls.__table__.columns
    return {key: _coerce(value, columns[key].type) for key, value in row.items()}


def features_to_sql(features: Mapping[str, Any]) -> dict[str, Any]:
    """Features nommées comme FEATURE_COLUMNS → colonnes SQL typées."""
    return coerce_row(
        BuildingFeatures, {col: features[name] for name, col in FEATURE_SQL.items()}
    )


def feature_values(obj: Any) -> dict[str, Any]:
    """Bloc de features d'une ligne ORM, clés SQL (pour copier un snapshot)."""
    return {col: getattr(obj, col) for col in FEATURE_SQL.values()}


def features_from_sql(obj: Any) -> dict[str, Any]:
    """Ligne ORM → dict FEATURE_COLUMNS prêt pour CatBoost (flags en int)."""
    out = {name: getattr(obj, col) for name, col in FEATURE_SQL.items()}
    for flag in FLAG_COLUMNS:
        out[flag] = int(out[flag])
    return out
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_db_models.py -v`
Expected: 8 PASS.

- [ ] **Step 6: Commit**

```bash
git add app/db/models.py app/db/mapping.py tests/test_db_models.py
git commit -m "feat(db): modèles ORM et correspondances CSV/SQL (#26)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: Migration Alembic, provisionnement, fixtures de test et CI Postgres

**Files:**
- Create: `alembic.ini`, `app/db/migrations/env.py`, `app/db/migrations/script.py.mako`, `app/db/migrations/versions/<rev>_schema_initial.py`, `app/db/views.py`, `app/db/registry.py`, `app/db/create_db.py`, `docker-compose.yml`, `tests/conftest.py`, `tests/synth.py`, `tests/test_db_schema.py`
- Modify: `.github/workflows/ci-test.yml`, `.example.env`

**Interfaces:**
- Consumes: `app.db.models.Base`, `User`, `MlModel`; `app.core.security.get_password_hash` (existant).
- Produces:
  - `app.db.views.PROJECTED_EVALUATION_VIEW: str` (SQL `CREATE VIEW`).
  - `app.db.registry`: `CATBOOST_NAME = "catboost-multitarget"`, `KUMO_NAME = "kumo-tabular-zero-shot"`, `class NoActiveModel(LookupError)`, `active_model(session, name) -> MlModel`, `register_model(session, *, name, version, mlflow_run_id, artifact_path) -> MlModel`.
  - `app.db.create_db`: `Roles` (dataclass `owner`, `api`, `mlflow`, `Roles.with_prefix(prefix)`), `dsn(url, **overrides) -> str`, `provision(admin_url, *, passwords: dict[str, str], db_name="p5", mlflow_db="mlflow", role_prefix="p5") -> str` (retourne l'URL propriétaire), `run_migrations(owner_url)`, `seed(session)`, `main()`.
  - Fixtures pytest : `provisioned_db` (session, dict `owner_url` / `api_url`), `owner_engine` (session), `db` (fonction, `sessionmaker` lié à une transaction annulée et patché dans `app.db.session.SessionLocal`).
  - `tests/synth.py` : `make_synth(n=80, seed=0) -> pd.DataFrame` (déplacé depuis `tests/test_training.py`, avec en plus `DataYear=2016`), `EXAMPLE_FEATURES: dict` (clés FEATURE_COLUMNS), `add_record(session, building_id, year, building_type="NonResidential") -> BuildingRecordRaw`.

- [ ] **Step 1: Lancer Postgres en local via Compose**

`docker-compose.yml` (le service `api` et le profil `tools` sont complétés en Task 13) :

```yaml
services:
  db:
    image: postgres:17-alpine
    environment:
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:?définir POSTGRES_PASSWORD dans .env}
    volumes:
      - pgdata:/var/lib/postgresql/data
    ports:
      - "127.0.0.1:5432:5432"
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U postgres"]
      interval: 5s
      timeout: 5s
      retries: 10

volumes:
  pgdata:
```

`.example.env` (remplacer le contenu) :

```bash
SECRET_KEY=ta_super_clef
POSTGRES_PASSWORD=change-me
P5_OWNER_PASSWORD=change-me-owner
P5_API_PASSWORD=change-me-api
P5_MLFLOW_PASSWORD=change-me-mlflow
DATABASE_ADMIN_URL=postgresql+psycopg://postgres:change-me@localhost:5432/postgres
DATABASE_OWNER_URL=postgresql+psycopg://p5_owner:change-me-owner@localhost:5432/p5
DATABASE_URL=postgresql+psycopg://p5_api:change-me-api@localhost:5432/p5
MLFLOW_TRACKING_URI=postgresql+psycopg://p5_mlflow:change-me-mlflow@localhost:5432/mlflow
TRAINING_YEAR=2016
```

```bash
cp -n .example.env .env   # puis ajuster les mots de passe si besoin
docker compose up -d db
docker compose ps         # db doit être "healthy"
```

- [ ] **Step 2: Initialiser Alembic**

```bash
uv run alembic init app/db/migrations
```

Dans `alembic.ini` généré, mettre `script_location = %(here)s/app/db/migrations` et `sqlalchemy.url =` (vide). Remplacer `app/db/migrations/env.py` par :

```python
"""Environnement Alembic : URL via config programmatique ou DATABASE_OWNER_URL."""

import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from app.db.models import Base

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _url() -> str:
    return config.get_main_option("sqlalchemy.url") or os.environ["DATABASE_OWNER_URL"]


def run_migrations_offline() -> None:
    context.configure(
        url=_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        {"sqlalchemy.url": _url()}, prefix="sqlalchemy.", poolclass=pool.NullPool
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
```

- [ ] **Step 3: Générer la révision initiale sur une base jetable**

```bash
docker run --rm -d --name p5-autogen -e POSTGRES_PASSWORD=x -p 127.0.0.1:55432:5432 postgres:17-alpine
sleep 3
DATABASE_OWNER_URL=postgresql+psycopg://postgres:x@localhost:55432/postgres \
  uv run alembic revision --autogenerate -m "schema initial"
docker stop p5-autogen
```

Vérifier que la révision générée contient les 9 `op.create_table`, tous les `sa.CheckConstraint` nommés, et l'index `uq_ml_models_active_name` avec `postgresql_where`.

- [ ] **Step 4: Ajouter la vue**

`app/db/views.py` :

```python
"""Vues SQL (créées par la migration, pas par l'ORM)."""

PROJECTED_EVALUATION_VIEW = """
CREATE VIEW v_projected_evaluation AS
SELECT
    m.name AS model_name,
    m.version AS model_version,
    r.data_year,
    r.building_id,
    p.energy_use_kbtu AS predicted_energy_kbtu,
    a.site_energy_use_kbtu AS actual_energy_kbtu,
    p.ghg_emissions_tco2e AS predicted_ghg_tco2e,
    a.total_ghg_emissions_tco2e AS actual_ghg_tco2e,
    abs(p.energy_use_kbtu - a.site_energy_use_kbtu) AS abs_err_energy_kbtu,
    abs(p.energy_use_kbtu - a.site_energy_use_kbtu)
        / NULLIF(a.site_energy_use_kbtu, 0) AS rel_err_energy,
    abs(p.ghg_emissions_tco2e - a.total_ghg_emissions_tco2e) AS abs_err_ghg_tco2e,
    abs(p.ghg_emissions_tco2e - a.total_ghg_emissions_tco2e)
        / NULLIF(a.total_ghg_emissions_tco2e, 0) AS rel_err_ghg
FROM predictions p
JOIN ml_models m ON m.id = p.model_id
JOIN prediction_inputs i ON i.id = p.prediction_input_id
JOIN building_records_raw r ON r.id = i.building_record_id
JOIN building_actuals a ON a.record_id = r.id
WHERE i.input_source = 'batch'
"""
```

Dans la révision générée, ajouter l'import `from app.db.views import PROJECTED_EVALUATION_VIEW`, puis à la **fin** de `upgrade()` :

```python
    op.execute(PROJECTED_EVALUATION_VIEW)
```

et au **début** de `downgrade()` :

```python
    op.execute("DROP VIEW IF EXISTS v_projected_evaluation")
```

- [ ] **Step 5: Écrire le registre des modèles**

`app/db/registry.py` :

```python
"""Registre des modèles (`ml_models`) : version active et enregistrement."""

from __future__ import annotations

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.db.models import MlModel

CATBOOST_NAME = "catboost-multitarget"
KUMO_NAME = "kumo-tabular-zero-shot"


class NoActiveModel(LookupError):
    """Aucune version active pour ce nom de modèle."""


def active_model(session: Session, name: str) -> MlModel:
    model = session.scalar(
        select(MlModel).where(MlModel.name == name, MlModel.is_active)
    )
    if model is None:
        raise NoActiveModel(name)
    return model


def register_model(
    session: Session,
    *,
    name: str,
    version: str,
    mlflow_run_id: str | None,
    artifact_path: str | None,
) -> MlModel:
    """Insère une version et la rend active (l'ancienne est désactivée)."""
    session.execute(
        update(MlModel)
        .where(MlModel.name == name, MlModel.is_active)
        .values(is_active=False)
    )
    model = MlModel(
        name=name,
        version=version,
        mlflow_run_id=mlflow_run_id,
        artifact_path=artifact_path,
        is_active=True,
    )
    session.add(model)
    session.commit()
    return model
```

- [ ] **Step 6: Écrire le provisionnement**

`app/db/create_db.py` :

```python
"""Provisionnement idempotent de PostgreSQL (spec §5.3).

Usage : ``uv run python -m app.db.create_db`` (ou via le service Compose ``tools``).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import psycopg
from alembic import command
from alembic.config import Config
from psycopg import sql
from sqlalchemy import create_engine, select
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from app.core.security import get_password_hash
from app.db.models import MlModel, User
from app.db.registry import CATBOOST_NAME, KUMO_NAME
from app.lib.tools import get_logger

log = get_logger(__name__)

MIGRATIONS_DIR = Path(__file__).parent / "migrations"

# Droits du rôle API (spec §5.2) ; {api} est remplacé par l'identifiant du rôle.
API_GRANTS = (
    "GRANT USAGE ON SCHEMA public TO {api}",
    "GRANT SELECT ON users, buildings, building_features, ml_models TO {api}",
    "GRANT SELECT (id, building_id, data_year) ON building_records_raw TO {api}",
    "GRANT SELECT, INSERT, UPDATE ON api_requests TO {api}",
    "GRANT SELECT, INSERT ON prediction_inputs, predictions TO {api}",
    "GRANT USAGE ON ALL SEQUENCES IN SCHEMA public TO {api}",
)

DEMO_USERS = (
    {
        "username": "johndoe",
        "full_name": "John Doe",
        "email": "johndoe@example.com",
        "is_active": True,
    },
    {
        "username": "alice",
        "full_name": "Alice Chains",
        "email": "alicechains@example.com",
        "is_active": False,
    },
)

# (nom, version, artifact_path) des modèles disponibles dès l'installation.
SEED_MODELS = (
    (CATBOOST_NAME, "baseline", "models"),
    (KUMO_NAME, "zero-shot", None),
)


@dataclass(frozen=True)
class Roles:
    owner: str
    api: str
    mlflow: str

    @classmethod
    def with_prefix(cls, prefix: str) -> Roles:
        return cls(f"{prefix}_owner", f"{prefix}_api", f"{prefix}_mlflow")


def dsn(url: str, **overrides: object) -> str:
    """URL SQLAlchemy → DSN libpq utilisable par psycopg."""
    return (
        make_url(url)
        .set(drivername="postgresql", **overrides)
        .render_as_string(hide_password=False)
    )


def _ensure_role(conn: psycopg.Connection, name: str, password: str) -> None:
    exists = conn.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (name,))
    verb = "ALTER" if exists.fetchone() else "CREATE"
    conn.execute(
        sql.SQL(verb + " ROLE {} LOGIN PASSWORD {}").format(
            sql.Identifier(name), sql.Literal(password)
        )
    )


def _ensure_database(conn: psycopg.Connection, name: str, owner: str) -> None:
    exists = conn.execute("SELECT 1 FROM pg_database WHERE datname = %s", (name,))
    if exists.fetchone() is None:
        conn.execute(
            sql.SQL("CREATE DATABASE {} OWNER {}").format(
                sql.Identifier(name), sql.Identifier(owner)
            )
        )
    conn.execute(
        sql.SQL("REVOKE ALL ON DATABASE {} FROM PUBLIC").format(sql.Identifier(name))
    )


def run_migrations(owner_url: str) -> None:
    cfg = Config()
    cfg.set_main_option("script_location", str(MIGRATIONS_DIR))
    cfg.set_main_option("sqlalchemy.url", owner_url.replace("%", "%%"))
    command.upgrade(cfg, "head")


def _apply_grants(admin_url: str, db_name: str, roles: Roles) -> None:
    with psycopg.connect(dsn(admin_url, database=db_name), autocommit=True) as conn:
        conn.execute(
            sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(
                sql.Identifier(db_name), sql.Identifier(roles.api)
            )
        )
        for stmt in API_GRANTS:
            conn.execute(sql.SQL(stmt).format(api=sql.Identifier(roles.api)))


def seed(session: Session) -> None:
    """Utilisateurs de démo (hash calculé à l'exécution) et modèles initiaux."""
    for user in DEMO_USERS:
        if session.scalar(select(User).where(User.username == user["username"])):
            continue
        session.add(User(**user, hashed_password=get_password_hash("secret")))
    for name, version, artifact_path in SEED_MODELS:
        if session.scalar(select(MlModel).where(MlModel.name == name)):
            continue
        session.add(
            MlModel(
                name=name, version=version, artifact_path=artifact_path, is_active=True
            )
        )
    session.commit()


def provision(
    admin_url: str,
    *,
    passwords: dict[str, str],
    db_name: str = "p5",
    mlflow_db: str = "mlflow",
    role_prefix: str = "p5",
) -> str:
    """Crée rôles et bases, migre, applique les droits, seed. Retourne l'URL owner."""
    roles = Roles.with_prefix(role_prefix)
    with psycopg.connect(dsn(admin_url), autocommit=True) as conn:
        _ensure_role(conn, roles.owner, passwords["owner"])
        _ensure_role(conn, roles.api, passwords["api"])
        _ensure_role(conn, roles.mlflow, passwords["mlflow"])
        _ensure_database(conn, db_name, roles.owner)
        _ensure_database(conn, mlflow_db, roles.mlflow)
    owner_url = (
        make_url(admin_url)
        .set(username=roles.owner, password=passwords["owner"], database=db_name)
        .render_as_string(hide_password=False)
    )
    run_migrations(owner_url)
    _apply_grants(admin_url, db_name, roles)
    engine = create_engine(owner_url)
    try:
        with Session(engine) as session:
            seed(session)
    finally:
        engine.dispose()
    log.info("Base %s provisionnée (rôles %s_*)", db_name, role_prefix)
    return owner_url


def main() -> None:
    passwords = {
        "owner": os.environ["P5_OWNER_PASSWORD"],
        "api": os.environ["P5_API_PASSWORD"],
        "mlflow": os.environ["P5_MLFLOW_PASSWORD"],
    }
    provision(os.environ["DATABASE_ADMIN_URL"], passwords=passwords)
    print("[create_db] base p5 et base mlflow prêtes")


if __name__ == "__main__":
    main()
```

- [ ] **Step 7: Écrire les fixtures partagées**

`tests/synth.py` : déplacer `make_synth` depuis `tests/test_training.py` **à l'identique**, en ajoutant `"DataYear": [2016] * n,` dans le dict du DataFrame. Ajouter à la suite :

```python
from sqlalchemy.orm import Session

from app.db.models import Building, BuildingRecordRaw

EXAMPLE_FEATURES = {
    "BuildingType": "NonResidential",
    "PrimaryPropertyType": "Office",
    "Neighborhood": "BALLARD",
    "Latitude": 47.62,
    "Longitude": -122.35,
    "YearBuilt": 1990,
    "NumberofBuildings": 1.0,
    "NumberofFloors": 4,
    "PropertyGFAParking": 5000,
    "PropertyGFABuilding(s)": 15000,
    "LargestPropertyUseType": "Office",
    "SecondLargestPropertyUseType": "Retail",
    "SecondLargestPropertyUseTypeGFA": 3000.0,
    "ThirdLargestPropertyUseType": "Parking",
    "ThirdLargestPropertyUseTypeGFA": 2000.0,
    "Has_NaturalGas": 1,
    "Has_Steam": 0,
}


def add_record(
    session: Session,
    building_id: int,
    year: int,
    building_type: str = "NonResidential",
) -> BuildingRecordRaw:
    """Crée (si besoin) le bâtiment puis un enregistrement brut minimal."""
    if session.get(Building, building_id) is None:
        session.add(Building(ose_building_id=building_id))
        session.flush()
    record = BuildingRecordRaw(
        building_id=building_id,
        data_year=year,
        building_type=building_type,
        source_file="test.csv",
    )
    session.add(record)
    session.flush()
    return record
```

Dans `tests/test_training.py`, supprimer la définition de `make_synth` et ajouter `from synth import make_synth` après le `sys.path.insert`.

`tests/conftest.py` :

```python
"""Fixtures PostgreSQL partagées (base `p5_test`, rôles `p5test_*`)."""

import os
import sys
from pathlib import Path

import psycopg
import pytest
from psycopg import sql
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db import create_db
from app.db import session as db_session

ADMIN_URL = os.getenv("TEST_DATABASE_ADMIN_URL") or (
    "postgresql+psycopg://postgres:"
    f"{os.getenv('POSTGRES_PASSWORD', 'postgres')}@localhost:5432/postgres"
)
TEST_DB = "p5_test"
TEST_MLFLOW_DB = "mlflow_test"
TEST_PREFIX = "p5test"
TEST_PASSWORDS = {"owner": "owner-test", "api": "api-test", "mlflow": "mlflow-test"}


@pytest.fixture(scope="session")
def provisioned_db():
    try:
        conn = psycopg.connect(
            create_db.dsn(ADMIN_URL), autocommit=True, connect_timeout=3
        )
    except psycopg.OperationalError as exc:
        pytest.skip(
            f"PostgreSQL de test indisponible ({exc}). "
            "Lancez `docker compose up -d db`."
        )
    with conn:
        for name in (TEST_DB, TEST_MLFLOW_DB):
            conn.execute(
                sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(
                    sql.Identifier(name)
                )
            )
    owner_url = create_db.provision(
        ADMIN_URL,
        passwords=TEST_PASSWORDS,
        db_name=TEST_DB,
        mlflow_db=TEST_MLFLOW_DB,
        role_prefix=TEST_PREFIX,
    )
    api_url = (
        make_url(owner_url)
        .set(username=f"{TEST_PREFIX}_api", password=TEST_PASSWORDS["api"])
        .render_as_string(hide_password=False)
    )
    return {"owner_url": owner_url, "api_url": api_url}


@pytest.fixture(scope="session")
def owner_engine(provisioned_db):
    engine = create_engine(provisioned_db["owner_url"])
    yield engine
    engine.dispose()


@pytest.fixture
def db(owner_engine, monkeypatch):
    """Sessions liées à une transaction annulée en fin de test.

    Chaque ``commit()`` ne relâche qu'un savepoint : le test voit ses écritures,
    la base est intacte après. ``SessionLocal`` est patché pour que l'API et le
    middleware utilisent la même connexion.
    """
    conn = owner_engine.connect()
    trans = conn.begin()
    factory = sessionmaker(
        bind=conn, join_transaction_mode="create_savepoint", expire_on_commit=False
    )
    monkeypatch.setattr(db_session, "SessionLocal", factory)
    try:
        yield factory
    finally:
        trans.rollback()
        conn.close()
```

- [ ] **Step 8: Write the failing schema tests**

`tests/test_db_schema.py` :

```python
"""Tests d'intégration : migration, contraintes, rôles, provisionnement."""

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.exc import IntegrityError, ProgrammingError
from sqlalchemy.orm import Session
from synth import EXAMPLE_FEATURES, add_record

from app.db import create_db, mapping
from app.db.models import Base, BuildingFeatures, MlModel, PredictionInput, User
from app.db.registry import CATBOOST_NAME, active_model, register_model

pytestmark = pytest.mark.db


def test_migrations_match_models(owner_engine):
    with owner_engine.connect() as conn:
        diff = compare_metadata(MigrationContext.configure(conn), Base.metadata)
    assert diff == []


def test_view_exists(owner_engine):
    with owner_engine.connect() as conn:
        conn.execute(text("SELECT * FROM v_projected_evaluation LIMIT 0"))


def test_seed_users_and_models(db):
    with db() as s:
        users = {u.username: u.is_active for u in s.scalars(select(User))}
        assert users == {"johndoe": True, "alice": False}
        assert active_model(s, CATBOOST_NAME).version == "baseline"


def test_provision_is_idempotent(provisioned_db):
    from conftest import ADMIN_URL, TEST_DB, TEST_MLFLOW_DB, TEST_PASSWORDS, TEST_PREFIX

    create_db.provision(
        ADMIN_URL,
        passwords=TEST_PASSWORDS,
        db_name=TEST_DB,
        mlflow_db=TEST_MLFLOW_DB,
        role_prefix=TEST_PREFIX,
    )
    engine = create_engine(provisioned_db["owner_url"])
    with Session(engine) as s:
        assert s.scalar(select(func.count()).select_from(User)) == 2
    engine.dispose()


def _features(**overrides):
    return BuildingFeatures(
        **mapping.features_to_sql(EXAMPLE_FEATURES), prep_version="t", **overrides
    )


def test_split_requires_eligibility(db):
    with db() as s:
        rec = add_record(s, 1, 2016)
        s.add(
            _features(
                record_id=rec.id,
                dataset_role="training",
                is_training_eligible=False,
                exclusion_reason="outlier",
                split="train",
            )
        )
        with pytest.raises(IntegrityError):
            s.commit()


def test_production_rows_cannot_be_eligible(db):
    with db() as s:
        rec = add_record(s, 1, 2018)
        s.add(
            _features(
                record_id=rec.id,
                dataset_role="production",
                is_training_eligible=True,
                split="train",
            )
        )
        with pytest.raises(IntegrityError):
            s.commit()


def test_building_id_input_requires_record(db):
    with db() as s:
        s.add(
            PredictionInput(
                input_source="batch",
                building_record_id=None,
                **mapping.features_to_sql(EXAMPLE_FEATURES),
            )
        )
        with pytest.raises(IntegrityError):
            s.commit()


def test_single_active_version_per_model(db):
    with db() as s:
        s.add(MlModel(name=CATBOOST_NAME, version="dup", is_active=True))
        with pytest.raises(IntegrityError):
            s.commit()


def test_register_model_switches_active_version(db):
    with db() as s:
        new = register_model(
            s,
            name=CATBOOST_NAME,
            version="20261014120000",
            mlflow_run_id="abc",
            artifact_path="models",
        )
        assert active_model(s, CATBOOST_NAME).id == new.id
        assert (
            s.scalar(
                select(func.count())
                .select_from(MlModel)
                .where(MlModel.name == CATBOOST_NAME, MlModel.is_active)
            )
            == 1
        )


def test_api_role_cannot_read_pii_or_actuals(provisioned_db):
    engine = create_engine(provisioned_db["api_url"])
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT id, building_id, data_year FROM building_records_raw"))
        for forbidden in (
            "SELECT address FROM building_records_raw",
            "SELECT * FROM building_actuals",
        ):
            with engine.connect() as conn:
                with pytest.raises(ProgrammingError):
                    conn.execute(text(forbidden))
    finally:
        engine.dispose()
```

- [ ] **Step 9: Run tests to verify they pass**

Run: `uv run pytest tests/test_db_schema.py -v`
Expected: 10 PASS (si un test échoue sur `compare_metadata`, corriger la révision générée, pas le test). Puis `uv run pytest -q` : tout est vert.

- [ ] **Step 10: Ajouter Postgres à la CI**

Dans `.github/workflows/ci-test.yml`, sous `jobs.ci-test` (même niveau que `runs-on`), ajouter :

```yaml
    services:
      postgres:
        image: postgres:17-alpine
        env:
          POSTGRES_PASSWORD: postgres
        ports:
          - 5432:5432
        options: >-
          --health-cmd "pg_isready -U postgres"
          --health-interval 5s
          --health-timeout 5s
          --health-retries 10
```

et sur l'étape « Tests unitaires avec couverture », ajouter :

```yaml
        env:
          TEST_DATABASE_ADMIN_URL: postgresql+psycopg://postgres:postgres@localhost:5432/postgres
```

- [ ] **Step 11: Commit**

```bash
git add alembic.ini app/db docker-compose.yml .example.env tests/conftest.py tests/synth.py tests/test_training.py tests/test_db_schema.py .github/workflows/ci-test.yml
git commit -m "feat(db): migration initiale, provisionnement des rôles et fixtures Postgres (#26)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: Masquage et parsing des corps pour les traces

**Files:**
- Create: `app/db/redaction.py`
- Test: `tests/test_redaction.py`

**Interfaces:**
- Produces: `SECRET_KEYS: frozenset[str]`, `MASK = "***"`, `MAX_TRACE_BYTES = 65536`, `redact(value) -> Any`, `parse_body(body: bytes, content_type: str | None) -> Any | None`, `to_trace(body: bytes, content_type: str | None) -> Any | None` (= `redact(parse_body(...))`).

- [ ] **Step 1: Write the failing test**

`tests/test_redaction.py` :

```python
"""Tests du masquage des secrets dans les traces."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db.redaction import MAX_TRACE_BYTES, parse_body, redact, to_trace

FORM = "application/x-www-form-urlencoded"
JSON = "application/json"


def test_token_form_password_masked():
    body = b"grant_type=password&username=johndoe&password=secret"
    assert to_trace(body, FORM) == {
        "grant_type": "password",
        "username": "johndoe",
        "password": "***",
    }


def test_nested_and_case_insensitive_keys_masked():
    value = {"a": [{"Access_Token": "x"}], "client_secret": "y", "keep": 1}
    assert redact(value) == {"a": [{"Access_Token": "***"}], "client_secret": "***", "keep": 1}


def test_json_with_charset_parsed():
    assert to_trace(b'{"building_id": 1}', "application/json; charset=utf-8") == {
        "building_id": 1
    }


def test_empty_body_is_none():
    assert parse_body(b"", JSON) is None


def test_invalid_json_stored_as_raw_marker():
    assert parse_body(b"{not json", JSON) == {"_raw": "<non-JSON, 9 octets>"}


def test_binary_body_stored_as_raw_marker():
    assert parse_body(b"\xff\xfe\x00", "application/octet-stream") == {
        "_raw": "<non-JSON, 3 octets>"
    }


def test_non_utf8_form_stored_as_raw_marker():
    assert parse_body(b"password=\xff", FORM) == {"_raw": "<non-JSON, 10 octets>"}


def test_null_char_rejected_by_jsonb_stored_as_raw_marker():
    body = json.dumps({"x": "a\u0000b"}).encode()
    assert parse_body(body, JSON) == {"_raw": f"<non-JSON, {len(body)} octets>"}


def test_oversized_body_truncated_marker():
    body = b"{" + b" " * MAX_TRACE_BYTES + b"}"
    assert parse_body(body, JSON) == {"_raw": f"<tronqué, {len(body)} octets>"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_redaction.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.db.redaction'`

- [ ] **Step 3: Write minimal implementation**

`app/db/redaction.py` :

```python
"""Parsing et masquage des corps HTTP avant stockage dans `api_requests`."""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import parse_qsl

SECRET_KEYS = frozenset({"password", "access_token", "client_secret"})
MASK = "***"
MAX_TRACE_BYTES = 65536


def redact(value: Any) -> Any:
    """Remplace récursivement les valeurs des clés sensibles par ``MASK``."""
    if isinstance(value, dict):
        return {
            k: MASK if isinstance(k, str) and k.lower() in SECRET_KEYS else redact(v)
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [redact(v) for v in value]
    return value


def _raw_marker(body: bytes) -> dict[str, str]:
    return {"_raw": f"<non-JSON, {len(body)} octets>"}


def parse_body(body: bytes, content_type: str | None) -> Any | None:
    """Corps HTTP → valeur JSON-sérialisable (ou marqueur ``_raw``)."""
    if not body:
        return None
    if len(body) > MAX_TRACE_BYTES:
        return {"_raw": f"<tronqué, {len(body)} octets>"}
    # JSONB refuse le caractère nul : on ne tente pas de le stocker.
    if b"\\u0000" in body:
        return _raw_marker(body)
    ctype = (content_type or "").split(";")[0].strip().lower()
    try:
        if ctype == "application/x-www-form-urlencoded":
            text = body.decode("utf-8", errors="strict")
            return dict(parse_qsl(text, keep_blank_values=True, errors="strict"))
        if ctype == "application/json" or ctype.endswith("+json"):
            return json.loads(body)
    except (UnicodeDecodeError, ValueError):
        pass
    return _raw_marker(body)


def to_trace(body: bytes, content_type: str | None) -> Any | None:
    return redact(parse_body(body, content_type))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_redaction.py -v`
Expected: 9 PASS.

- [ ] **Step 5: Commit**

```bash
git add app/db/redaction.py tests/test_redaction.py
git commit -m "feat(db): parsing et masquage des corps pour la traçabilité (#26)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: Séparer périmètre et éligibilité dans `data_processing`

**Files:**
- Modify: `app/training/data_processing.py`
- Test: `tests/test_training.py`

**Interfaces:**
- Produces: `filter_scope(df) -> DataFrame`, `apply_common_corrections(df) -> DataFrame`, `flag_training_eligibility(df) -> DataFrame` (colonnes `is_training_eligible: bool`, `exclusion_reason: str | None`, même index), `assign_split(eligible_index, test_size=0.2, seed=42) -> Series` (`"train"`/`"test"`). `build_clean` garde sa signature et son comportement. `OSEBuildingID` sort de `PII_COLUMNS`.

- [ ] **Step 1: Write the failing tests** (ajouter à `tests/test_training.py`)

```python
def test_filter_scope_excludes_only_residential():
    df = make_synth(80)
    scoped = dp.filter_scope(df)
    assert not scoped["BuildingType"].str.startswith("Multifamily").any()
    assert 2 in scoped.index  # l'outlier reste dans le périmètre


def test_apply_common_corrections():
    df = make_synth(40)
    df.loc[0, "NumberofBuildings"] = 0
    out = dp.apply_common_corrections(df)
    assert out.loc[0, "NumberofBuildings"] == 1
    assert (out["Neighborhood"] == out["Neighborhood"].str.upper().str.strip()).all()


def test_flag_training_eligibility_reasons():
    df = dp.filter_scope(make_synth(80))
    df.loc[6, "SiteEnergyUse(kBtu)"] = 0
    df.loc[7, "TotalGHGEmissions"] = np.nan
    flags = dp.flag_training_eligibility(df)
    assert flags.loc[2, "exclusion_reason"] == "outlier"
    assert flags.loc[4, "exclusion_reason"] == "non_compliant"
    assert flags.loc[6, "exclusion_reason"] == "non_positive_target"
    assert flags.loc[7, "exclusion_reason"] == "missing_target"
    assert flags.loc[0, "is_training_eligible"]
    assert flags.loc[0, "exclusion_reason"] is None
    assert (flags["is_training_eligible"] == flags["exclusion_reason"].isna()).all()


def test_assign_split_matches_train_test_split():
    from sklearn.model_selection import train_test_split

    idx = pd.Index(range(100, 150))
    split = dp.assign_split(idx, test_size=0.2, seed=42)
    _, expected_test = train_test_split(idx, test_size=0.2, random_state=42)
    assert set(split.index[split == "test"]) == set(expected_test)
    assert set(split.unique()) == {"train", "test"}


def test_osebuildingid_not_pii():
    assert "OSEBuildingID" not in dp.PII_COLUMNS
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_training.py -k "scope or corrections or eligibility or assign_split or not_pii" -v`
Expected: FAIL — `AttributeError: module 'app.training.data_processing' has no attribute 'filter_scope'`

- [ ] **Step 3: Implement**

Dans `app/training/data_processing.py` : retirer `"OSEBuildingID"` de `PII_COLUMNS`, ajouter `from sklearn.model_selection import train_test_split` aux imports, puis remplacer `build_clean` par :

```python
def filter_scope(df: pd.DataFrame) -> pd.DataFrame:
    """Périmètre du modèle : exclut le résidentiel (Multifamily*)."""
    residential = df["BuildingType"].str.startswith("Multifamily", na=False)
    return df.loc[~residential].copy()


def apply_common_corrections(df: pd.DataFrame) -> pd.DataFrame:
    """Corrections valables pour toutes les années (entraînement et production)."""
    out = df.copy()
    if "Neighborhood" in out.columns:
        out["Neighborhood"] = out["Neighborhood"].str.upper().str.strip()
    if "NumberofBuildings" in out.columns:
        out.loc[out["NumberofBuildings"] == 0, "NumberofBuildings"] = 1
    return out


def flag_training_eligibility(df: pd.DataFrame) -> pd.DataFrame:
    """Filtres qualité de l'entraînement ; la première raison rencontrée l'emporte."""
    reason = pd.Series([None] * len(df), index=df.index, dtype=object)

    def mark(mask: pd.Series, label: str) -> None:
        reason[mask & reason.isna()] = label

    if "Outlier" in df.columns:
        mark(df["Outlier"].isin(["High outlier", "Low outlier"]), "outlier")
    if "ComplianceStatus" in df.columns:
        mark(df["ComplianceStatus"].ne("Compliant"), "non_compliant")
    targets = df[TARGET_COLUMNS]
    mark(targets.isna().any(axis=1), "missing_target")
    mark((targets <= 0).any(axis=1), "non_positive_target")
    return pd.DataFrame(
        {"is_training_eligible": reason.isna(), "exclusion_reason": reason},
        index=df.index,
    )


def assign_split(
    eligible_index: pd.Index, test_size: float = 0.2, seed: int = 42
) -> pd.Series:
    """Split train/test reproductible (identique à l'ancien TrainPipeline.split)."""
    _, idx_test = train_test_split(
        eligible_index, test_size=test_size, random_state=seed
    )
    split = pd.Series("train", index=eligible_index, dtype=object)
    split.loc[idx_test] = "test"
    return split


def build_clean(df: pd.DataFrame) -> pd.DataFrame:
    """Applique la chaîne de nettoyage du notebook (F0 -> F11)."""
    out = filter_scope(df)
    out = out.loc[:, out.nunique() > 1]
    out = out.loc[flag_training_eligibility(out)["is_training_eligible"]]
    out = out.drop(
        columns=[
            "Outlier",
            "ComplianceStatus",
            "DefaultData",
            "YearsENERGYSTARCertified",
            "ENERGYSTARScore",
            "PropertyGFATotal",
            "LargestPropertyUseTypeGFA",
            "ListOfAllPropertyUseTypes",
            *DATA_LEAKAGE_COLUMNS,
            *PII_COLUMNS,
        ],
        errors="ignore",
    )
    return apply_common_corrections(out)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_training.py -v`
Expected: tous PASS, y compris les tests `build_clean` existants (non-régression).

- [ ] **Step 5: Commit**

```bash
git add app/training/data_processing.py tests/test_training.py
git commit -m "refactor(training): sépare périmètre et éligibilité dans le nettoyage (#26)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 6: Ingestion CSV → base

**Files:**
- Create: `app/db/ingest.py`
- Test: `tests/test_db_ingest.py`

**Interfaces:**
- Consumes: `mapping.RAW_SQL`, `mapping.TARGET_SQL`, `mapping.FEATURE_SQL`, `mapping.FLAG_COLUMNS`, `mapping.coerce_row`; `session.owner_session_factory`; `dp.ensure_dataset`.
- Produces: `YEAR_COLUMN_RENAMES: dict[int, dict[str, str]]`, `REQUIRED_SOURCE_COLUMNS: tuple[str, ...]`, `normalize_columns(df, year) -> DataFrame` (colonnes = `list(RAW_SQL)`), `ingest_frame(session, df, *, year, source_file) -> int`, `build_parser()`, `main(argv=None)`.

- [ ] **Step 1: Write the failing test**

`tests/test_db_ingest.py` :

```python
"""Tests de l'ingestion CSV → building_records_raw / building_actuals."""

import logging

import pytest
from sqlalchemy import func, select
from synth import make_synth

from app.db import ingest
from app.db import session as db_session
from app.db.models import Building, BuildingActual, BuildingRecordRaw


def test_normalize_rejects_unknown_year():
    with pytest.raises(ValueError, match="Année non supportée"):
        ingest.normalize_columns(make_synth(10), 2031)


def test_normalize_reports_missing_required_columns():
    with pytest.raises(ValueError, match="Latitude"):
        ingest.normalize_columns(make_synth(10).drop(columns=["Latitude"]), 2016)


def test_normalize_rejects_inconsistent_year():
    with pytest.raises(ValueError, match="DataYear"):
        ingest.normalize_columns(make_synth(10), 2017)


def test_normalize_ignores_unknown_columns(caplog):
    df = make_synth(10).assign(Bonus=1)
    with caplog.at_level(logging.WARNING):
        out = ingest.normalize_columns(df, 2016)
    assert "Bonus" not in out.columns
    assert "Bonus" in caplog.text


@pytest.mark.db
def test_ingest_inserts_and_is_idempotent(db):
    df = make_synth(40)
    with db() as s:
        assert ingest.ingest_frame(s, df, year=2016, source_file="s.csv") == 40
        df.loc[0, "SiteEnergyUse(kBtu)"] = 123.0
        ingest.ingest_frame(s, df, year=2016, source_file="s.csv")
        assert s.scalar(select(func.count()).select_from(BuildingRecordRaw)) == 40
        assert s.scalar(select(func.count()).select_from(Building)) == 40
        rec = s.scalar(
            select(BuildingRecordRaw).where(BuildingRecordRaw.building_id == 0)
        )
        actual = s.get(BuildingActual, rec.id)
        assert actual.site_energy_use_kbtu == 123.0
        assert rec.address == "0 st"  # PII conservée
        assert rec.zip_code in {"98101", "98102", "98103"}


@pytest.mark.db
def test_ingest_deduplicates_building_ids(db, caplog):
    df = make_synth(10)
    df.loc[1, "OSEBuildingID"] = 0
    df.loc[1, "PropertyName"] = "dernier"
    with db() as s, caplog.at_level(logging.WARNING):
        assert ingest.ingest_frame(s, df, year=2016, source_file="s.csv") == 9
        rec = s.scalar(
            select(BuildingRecordRaw).where(BuildingRecordRaw.building_id == 0)
        )
        assert rec.property_name == "dernier"
    assert "doublon" in caplog.text


@pytest.mark.db
def test_ingest_main(db, tmp_path, monkeypatch):
    csv = tmp_path / "x.csv"
    make_synth(12).to_csv(csv, index=False)
    monkeypatch.setattr(db_session, "owner_session_factory", lambda: db)
    ingest.main(["--year", "2016", "--csv", str(csv)])
    with db() as s:
        assert s.scalar(select(func.count()).select_from(BuildingRecordRaw)) == 12
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_db_ingest.py -v`
Expected: FAIL — `ImportError: cannot import name 'ingest'`

- [ ] **Step 3: Write minimal implementation**

`app/db/ingest.py` :

```python
"""Ingestion d'un CSV Seattle (une année) vers le schéma brut.

Usage : ``uv run python -m app.db.ingest --year 2016 --csv data/2016_….csv``
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd
from sqlalchemy import func
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.db import session as db_session
from app.db.mapping import FEATURE_SQL, FLAG_COLUMNS, RAW_SQL, TARGET_SQL, coerce_row
from app.db.models import Building, BuildingActual, BuildingRecordRaw
from app.lib.tools import get_logger
from app.training import data_processing as dp

log = get_logger(__name__)

# Renommages source → noms 2016, par année. Compléter à partir des en-têtes
# réels des fichiers 2017–2019 (voir Step 5).
YEAR_COLUMN_RENAMES: dict[int, dict[str, str]] = {
    2016: {},
    2017: {},
    2018: {},
    2019: {},
}

REQUIRED_SOURCE_COLUMNS: tuple[str, ...] = (
    "OSEBuildingID",
    "DataYear",
    *(c for c in FEATURE_SQL if c not in FLAG_COLUMNS),
    "NaturalGas(kBtu)",
    "SteamUse(kBtu)",
    *TARGET_SQL,
)

CHUNK_SIZE = 500  # 500 × 49 colonnes < limite de 65 535 paramètres


def normalize_columns(df: pd.DataFrame, year: int) -> pd.DataFrame:
    """Ramène un fichier annuel aux colonnes de RAW_SQL (manquantes → NaN)."""
    if year not in YEAR_COLUMN_RENAMES:
        raise ValueError(
            f"Année non supportée : {year} (ajoutez-la à YEAR_COLUMN_RENAMES)"
        )
    out = df.rename(columns=YEAR_COLUMN_RENAMES[year])
    missing = [c for c in REQUIRED_SOURCE_COLUMNS if c not in out.columns]
    if missing:
        raise ValueError(f"Colonnes obligatoires absentes pour {year} : {missing}")
    unknown = sorted(set(out.columns) - set(RAW_SQL))
    if unknown:
        log.warning("Colonnes ignorées pour %s : %s", year, unknown)
    years = {int(y) for y in out["DataYear"].dropna().unique()}
    if years != {year}:
        raise ValueError(f"DataYear incohérent : {sorted(years)} (attendu {year})")
    return out.reindex(columns=list(RAW_SQL))


def _chunks(items: list, size: int = CHUNK_SIZE):
    for start in range(0, len(items), size):
        yield items[start : start + size]


def ingest_frame(
    session: Session, df: pd.DataFrame, *, year: int, source_file: str
) -> int:
    """Upsert buildings / records / actuals ; retourne le nombre de lignes."""
    df = normalize_columns(df, year).dropna(subset=["OSEBuildingID"])
    dup = df["OSEBuildingID"].duplicated(keep="last")
    if dup.any():
        log.warning(
            "%d doublon(s) d'OSEBuildingID pour %s : dernière ligne conservée",
            int(dup.sum()),
            year,
        )
        df = df.loc[~dup]
    records = [
        coerce_row(BuildingRecordRaw, {RAW_SQL[c]: v for c, v in row.items()})
        | {"source_file": source_file}
        for row in df.to_dict("records")
    ]
    for chunk in _chunks(records):
        session.execute(
            pg_insert(Building)
            .values([{"ose_building_id": r["building_id"]} for r in chunk])
            .on_conflict_do_nothing()
        )
        stmt = pg_insert(BuildingRecordRaw).values(chunk)
        updates = {
            c: stmt.excluded[c] for c in chunk[0] if c not in ("building_id", "data_year")
        }
        stmt = stmt.on_conflict_do_update(
            index_elements=["building_id", "data_year"],
            set_=updates | {"ingested_at": func.now()},
        ).returning(BuildingRecordRaw.id, BuildingRecordRaw.building_id)
        ids = {building_id: rid for rid, building_id in session.execute(stmt).all()}
        actuals = [
            {
                "record_id": ids[r["building_id"]],
                "site_energy_use_kbtu": r["site_energy_use_kbtu"],
                "total_ghg_emissions_tco2e": r["total_ghg_emissions"],
            }
            for r in chunk
        ]
        a = pg_insert(BuildingActual).values(actuals)
        session.execute(
            a.on_conflict_do_update(
                index_elements=["record_id"],
                set_={
                    "site_energy_use_kbtu": a.excluded.site_energy_use_kbtu,
                    "total_ghg_emissions_tco2e": a.excluded.total_ghg_emissions_tco2e,
                },
            )
        )
    session.commit()
    return len(records)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Ingestion d'un CSV Seattle")
    parser.add_argument("--year", type=int, required=True)
    parser.add_argument("--csv", required=True, help="Chemin du CSV de l'année")
    parser.add_argument(
        "--download",
        action="store_true",
        help="Télécharge le CSV 2016 s'il est absent",
    )
    return parser


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    path = Path(args.csv)
    if args.download:
        dp.ensure_dataset(path, download=True)
    if not path.exists():
        parser.error(f"CSV introuvable : {path}")
    df = pd.read_csv(path)
    with db_session.owner_session_factory()() as session:
        count = ingest_frame(session, df, year=args.year, source_file=path.name)
    print(f"[ingest] {count} lignes {args.year} depuis {path.name}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_db_ingest.py -v`
Expected: 7 PASS.

- [ ] **Step 5: Compléter les renommages 2017–2019 (dépend des fichiers réels)**

Pour chaque fichier disponible dans `data/` :

```bash
uv run python -c "
import pandas as pd, sys
from app.db.mapping import RAW_SQL
cols = list(pd.read_csv(sys.argv[1], nrows=0).columns)
print('absentes de RAW_SQL :', [c for c in cols if c not in RAW_SQL])
print('RAW_SQL non fournies :', [c for c in RAW_SQL if c not in cols])
" data/<fichier_2017>.csv
```

Pour chaque colonne source qui correspond à une colonne 2016 sous un autre nom, ajouter `"<nom source>": "<nom 2016>"` dans `YEAR_COLUMN_RENAMES[2017]` (idem 2018, 2019). Relancer `uv run python -m app.db.ingest --year 2017 --csv data/<fichier_2017>.csv` jusqu'à ce que `normalize_columns` ne lève plus d'erreur. Si un fichier n'est pas encore disponible, laisser le dictionnaire vide et le signaler dans le rapport de la tâche.

- [ ] **Step 6: Commit**

```bash
git add app/db/ingest.py tests/test_db_ingest.py
git commit -m "feat(db): ingestion idempotente des CSV annuels (#26)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 7: Préparation des features en base

**Files:**
- Create: `app/db/prepare.py`
- Test: `tests/test_db_prepare.py`

**Interfaces:**
- Consumes: `dp.filter_scope`, `dp.apply_common_corrections`, `dp.build_flags`, `dp.prepare_catboost`, `dp.flag_training_eligibility`, `dp.assign_split`; `mapping.RAW_SQL`, `features_to_sql`, `to_python`; `ingest.ingest_frame` (tests).
- Produces: `TRAINING_YEAR: int`, `PREP_VERSION = "1"`, `REQUIRED_FEATURES: tuple[str, ...]`, `load_raw_frame(session, year) -> DataFrame` (colonnes CSV, index `record_id` trié), `build_feature_rows(df_raw, *, training, test_size=0.2, seed=42) -> DataFrame` (colonnes `FEATURE_COLUMNS` + `dataset_role`, `is_training_eligible`, `exclusion_reason`, `split`), `prepare_year(session, year) -> int`, `main(argv=None)`.

- [ ] **Step 1: Write the failing test**

`tests/test_db_prepare.py` :

```python
"""Tests de la préparation brut → building_features."""

import logging

import numpy as np
import pytest
from sqlalchemy import func, select
from synth import make_synth

from app.db import ingest, prepare
from app.db import session as db_session
from app.db.models import BuildingFeatures, BuildingRecordRaw
from app.training.pipeline import TrainPipeline


def test_feature_rows_split_matches_legacy_pipeline():
    df = make_synth(200)
    rows = prepare.build_feature_rows(df, training=True)
    legacy = TrainPipeline(df_raw=df, seed=42, test_size=0.2).split()
    assert set(rows.index[rows["split"] == "train"]) == set(legacy.idx_train)
    assert set(rows.index[rows["split"] == "test"]) == set(legacy.idx_test)


def test_feature_rows_exclude_residential_keep_outliers():
    df = make_synth(80)
    rows = prepare.build_feature_rows(df, training=True)
    residential = df.index[df["BuildingType"].str.startswith("Multifamily")]
    assert not set(residential) & set(rows.index)
    assert rows.loc[2, "exclusion_reason"] == "outlier"
    assert rows.loc[2, "dataset_role"] == "training"


def test_feature_rows_production_has_no_eligibility():
    rows = prepare.build_feature_rows(make_synth(40), training=False)
    assert (rows["dataset_role"] == "production").all()
    assert not rows["is_training_eligible"].any()
    assert rows["split"].isna().all()
    assert rows["exclusion_reason"].isna().all()


def test_feature_rows_skip_missing_required_feature(caplog):
    df = make_synth(40)
    df.loc[0, "Latitude"] = np.nan
    with caplog.at_level(logging.WARNING):
        rows = prepare.build_feature_rows(df, training=False)
    assert 0 not in rows.index
    assert "feature obligatoire manquante" in caplog.text


@pytest.mark.db
def test_prepare_year_writes_features_idempotently(db):
    df = make_synth(80)
    with db() as s:
        ingest.ingest_frame(s, df, year=2016, source_file="s.csv")
        n = prepare.prepare_year(s, 2016)
        assert n == prepare.prepare_year(s, 2016)
        assert s.scalar(select(func.count()).select_from(BuildingFeatures)) == n
        residential = s.scalar(
            select(func.count())
            .select_from(BuildingFeatures)
            .join(BuildingRecordRaw, BuildingRecordRaw.id == BuildingFeatures.record_id)
            .where(BuildingRecordRaw.building_type.like("Multifamily%"))
        )
        assert residential == 0


@pytest.mark.db
def test_prepare_year_without_raw_data_fails(db):
    with db() as s, pytest.raises(RuntimeError, match="ingest"):
        prepare.prepare_year(s, 2018)


@pytest.mark.db
def test_prepare_main(db, monkeypatch):
    with db() as s:
        ingest.ingest_frame(s, make_synth(30), year=2016, source_file="s.csv")
    monkeypatch.setattr(db_session, "owner_session_factory", lambda: db)
    prepare.main(["--year", "2016"])
    with db() as s:
        assert s.scalar(select(func.count()).select_from(BuildingFeatures)) > 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_db_prepare.py -v`
Expected: FAIL — `ImportError: cannot import name 'prepare'`

- [ ] **Step 3: Write minimal implementation**

`app/db/prepare.py` :

```python
"""Préparation brut → building_features (deuxième temps, spec §4.1).

Usage : ``uv run python -m app.db.prepare --year 2016 2017 2018 2019``
"""

from __future__ import annotations

import argparse
import os

import pandas as pd
from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.db import session as db_session
from app.db.mapping import RAW_SQL, features_to_sql, to_python
from app.db.models import BuildingFeatures, BuildingRecordRaw
from app.lib.tools import get_logger
from app.schemas.api import FEATURE_COLUMNS
from app.training import data_processing as dp

log = get_logger(__name__)

TRAINING_YEAR = int(os.getenv("TRAINING_YEAR", "2016"))
PREP_VERSION = "1"
REQUIRED_FEATURES = (
    "Latitude",
    "Longitude",
    "YearBuilt",
    "NumberofFloors",
    "PropertyGFAParking",
    "PropertyGFABuilding(s)",
)
CHUNK_SIZE = 1000


def load_raw_frame(session: Session, year: int) -> pd.DataFrame:
    """Brut d'une année, colonnes CSV, index = record_id (ordre d'ingestion)."""
    rows = session.scalars(
        select(BuildingRecordRaw)
        .where(BuildingRecordRaw.data_year == year)
        .order_by(BuildingRecordRaw.id)
    ).all()
    data = [{csv: getattr(r, col) for csv, col in RAW_SQL.items()} for r in rows]
    index = pd.Index([r.id for r in rows], name="record_id")
    return pd.DataFrame(data, index=index, columns=list(RAW_SQL))


def build_feature_rows(
    df_raw: pd.DataFrame, *, training: bool, test_size: float = 0.2, seed: int = 42
) -> pd.DataFrame:
    scoped = dp.apply_common_corrections(dp.filter_scope(df_raw))
    missing = scoped[list(REQUIRED_FEATURES)].isna().any(axis=1)
    if missing.any():
        log.warning(
            "%d bâtiment(s) ignoré(s) : feature obligatoire manquante",
            int(missing.sum()),
        )
        scoped = scoped.loc[~missing]
    base = [c for c in FEATURE_COLUMNS if c not in ("Has_NaturalGas", "Has_Steam")]
    out = dp.prepare_catboost(scoped[base], dp.build_flags(df_raw, scoped))
    if training:
        eligibility = dp.flag_training_eligibility(scoped)
        out["dataset_role"] = "training"
        out["is_training_eligible"] = eligibility["is_training_eligible"]
        out["exclusion_reason"] = eligibility["exclusion_reason"]
        eligible = out.index[out["is_training_eligible"].to_numpy(dtype=bool)]
        split = dp.assign_split(eligible, test_size=test_size, seed=seed)
        out["split"] = split.reindex(out.index)
    else:
        out["dataset_role"] = "production"
        out["is_training_eligible"] = False
        out["exclusion_reason"] = None
        out["split"] = None
    return out


def prepare_year(session: Session, year: int) -> int:
    df_raw = load_raw_frame(session, year)
    if df_raw.empty:
        raise RuntimeError(
            f"Aucune donnée brute pour {year} : lancez d'abord app.db.ingest."
        )
    rows = build_feature_rows(df_raw, training=(year == TRAINING_YEAR))
    payload = []
    for record_id, row in rows.iterrows():
        values = features_to_sql(row)
        values.update(
            record_id=int(record_id),
            dataset_role=row["dataset_role"],
            is_training_eligible=bool(row["is_training_eligible"]),
            exclusion_reason=to_python(row["exclusion_reason"]),
            split=to_python(row["split"]),
            prep_version=PREP_VERSION,
        )
        payload.append(values)
    for start in range(0, len(payload), CHUNK_SIZE):
        chunk = payload[start : start + CHUNK_SIZE]
        stmt = pg_insert(BuildingFeatures).values(chunk)
        updates = {c: stmt.excluded[c] for c in chunk[0] if c != "record_id"}
        session.execute(
            stmt.on_conflict_do_update(
                index_elements=["record_id"],
                set_=updates | {"prepared_at": func.now()},
            )
        )
    # Lignes devenues hors périmètre depuis la dernière préparation.
    year_records = select(BuildingRecordRaw.id).where(
        BuildingRecordRaw.data_year == year
    )
    session.execute(
        delete(BuildingFeatures).where(
            BuildingFeatures.record_id.in_(year_records),
            BuildingFeatures.record_id.not_in([p["record_id"] for p in payload]),
        )
    )
    session.commit()
    return len(payload)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Préparation des features")
    parser.add_argument("--year", type=int, nargs="+", required=True)
    args = parser.parse_args(argv)
    with db_session.owner_session_factory()() as session:
        for year in args.year:
            try:
                count = prepare_year(session, year)
            except RuntimeError as exc:
                parser.error(str(exc))
            print(f"[prepare] {year} : {count} bâtiments dans le périmètre")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_db_prepare.py -v`
Expected: 7 PASS.

- [ ] **Step 5: Commit**

```bash
git add app/db/prepare.py tests/test_db_prepare.py
git commit -m "feat(db): préparation des features en base avec split figé (#26)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 8: Entraînement depuis Postgres et registre des versions

**Files:**
- Create: `app/db/training_data.py`
- Modify: `app/training/pipeline.py`, `app/training/__main__.py`
- Test: `tests/test_db_training.py`, `tests/test_cli.py`

**Interfaces:**
- Consumes: `mapping.features_from_sql`, `mapping.TARGET_SQL`; `registry.register_model`, `CATBOOST_NAME`; `session.owner_session_factory`.
- Produces:
  - `app.training.pipeline.TrainingData` (dataclass figée : `X: DataFrame` colonnes `FEATURE_COLUMNS`, `Y: DataFrame` colonnes cibles CSV, `split: Series` `"train"`/`"test"`, même index).
  - `TrainPipeline(df_raw=None, *, training_data: TrainingData | None = None, csv_path=None, …)` ; attribut `mlflow_run_id: str | None` renseigné par `run()`.
  - `app.db.training_data.load_training_data(session) -> TrainingData` (lève `RuntimeError` si vide).
  - `app.training.__main__.main(argv=None)` : sans `--csv`/`--download`.

- [ ] **Step 1: Write the failing tests**

`tests/test_db_training.py` :

```python
"""Tests du chargement du jeu d'entraînement depuis Postgres."""

import pytest
from synth import make_synth

from app.db import ingest, prepare
from app.db.training_data import load_training_data
from app.schemas.api import FEATURE_COLUMNS
from app.training.pipeline import TrainPipeline

pytestmark = pytest.mark.db


def test_load_training_data_matches_prepared_split(db):
    df = make_synth(200)
    with db() as s:
        ingest.ingest_frame(s, df, year=2016, source_file="s.csv")
        prepare.prepare_year(s, 2016)
        data = load_training_data(s)
    assert list(data.X.columns) == FEATURE_COLUMNS
    assert list(data.Y.columns) == ["SiteEnergyUse(kBtu)", "TotalGHGEmissions"]
    assert set(data.split.unique()) == {"train", "test"}
    legacy = TrainPipeline(df_raw=df, seed=42, test_size=0.2).split()
    assert (data.split == "train").sum() == len(legacy.idx_train)


def test_load_training_data_empty_raises(db):
    with db() as s, pytest.raises(RuntimeError, match="app.db.prepare"):
        load_training_data(s)


def test_pipeline_accepts_training_data(db):
    with db() as s:
        ingest.ingest_frame(s, make_synth(160), year=2016, source_file="s.csv")
        prepare.prepare_year(s, 2016)
        data = load_training_data(s)
    pipe = TrainPipeline(training_data=data).split().feature_engineering()
    assert len(pipe.X_train) == (data.split == "train").sum()
    assert list(pipe.X_test.columns) == FEATURE_COLUMNS
    assert pipe.Y_train.index.equals(pipe.X_train.index)
```

Dans `tests/test_cli.py`, remplacer `test_build_parser_overrides` et `test_main_missing_dataset_exits` par :

```python
def test_build_parser_overrides():
    args = cli.build_parser().parse_args(
        ["--output-dir", "out", "--no-kumo", "--cv-splits", "3"]
    )
    assert args.output_dir == "out"
    assert args.no_kumo is True
    assert args.cv_splits == 3


@pytest.mark.db
def test_main_without_training_rows_exits(db, monkeypatch):
    from app.db import session as db_session

    monkeypatch.setattr(db_session, "owner_session_factory", lambda: db)
    with pytest.raises(SystemExit) as exc:
        cli.main([])
    assert exc.value.code == 2
```

et retirer `assert args.download is False` de `test_build_parser_defaults`.

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_db_training.py tests/test_cli.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.db.training_data'`

- [ ] **Step 3: Implement `TrainingData` dans `app/training/pipeline.py`**

Ajouter `from dataclasses import dataclass` aux imports, puis avant `class TrainPipeline` :

```python
@dataclass(frozen=True)
class TrainingData:
    """Jeu d'entraînement préparé en base (features, cibles, split figé)."""

    X: pd.DataFrame
    Y: pd.DataFrame
    split: pd.Series
```

Modifier `__init__` : signature `def __init__(self, df_raw=None, *, training_data: TrainingData | None = None, csv_path=…, …)` ; remplacer le contrôle initial par :

```python
        if df_raw is None and csv_path is None and training_data is None:
            raise ValueError("Fournir df_raw, csv_path ou training_data.")
        self.training_data = training_data
        if df_raw is not None:
            self.df_raw = df_raw
        elif csv_path is not None:
            csv_path = Path(csv_path)
            if not csv_path.exists():
                raise FileNotFoundError(f"Dataset introuvable : {csv_path}")
            self.df_raw = pd.read_csv(csv_path)
        else:
            self.df_raw = None
```

et ajouter `self.mlflow_run_id: str | None = None` avec les autres attributs d'état.

Au début de `split()` (après le décorateur et la docstring) :

```python
        if self.training_data is not None:
            td = self.training_data
            self.df_clean = td.X.join(td.Y)
            self.idx_train = td.split.index[td.split == "train"]
            self.idx_test = td.split.index[td.split == "test"]
            log.info(
                "split (base) : %d train / %d test",
                len(self.idx_train),
                len(self.idx_test),
            )
            return self
```

Au début de `feature_engineering()`, après `self._require_split()` :

```python
        if self.training_data is not None:
            td = self.training_data
            self.X_train, self.X_test = td.X.loc[self.idx_train], td.X.loc[self.idx_test]
            self.Y_train, self.Y_test = td.Y.loc[self.idx_train], td.Y.loc[self.idx_test]
            return self
```

Dans `run()`, remplacer `with mlflow.start_run(run_name="p5-multitarget"):` par :

```python
        with mlflow.start_run(run_name="p5-multitarget") as parent_run:
            self.mlflow_run_id = parent_run.info.run_id
```

(le reste du bloc est inchangé, indentation conservée).

- [ ] **Step 4: Implement `app/db/training_data.py`**

```python
"""Lecture du jeu d'entraînement : building_features ⋈ building_actuals."""

from __future__ import annotations

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.mapping import TARGET_SQL, features_from_sql
from app.db.models import BuildingActual, BuildingFeatures
from app.schemas.api import FEATURE_COLUMNS
from app.training.pipeline import TrainingData


def load_training_data(session: Session) -> TrainingData:
    rows = session.execute(
        select(BuildingFeatures, BuildingActual)
        .join(BuildingActual, BuildingActual.record_id == BuildingFeatures.record_id)
        .where(
            BuildingFeatures.dataset_role == "training",
            BuildingFeatures.is_training_eligible,
        )
        .order_by(BuildingFeatures.record_id)
    ).all()
    if not rows:
        raise RuntimeError(
            "Aucune ligne d'entraînement : lancez `python -m app.db.ingest` "
            "puis `python -m app.db.prepare`."
        )
    index = pd.Index([f.record_id for f, _ in rows], name="record_id")
    X = pd.DataFrame([features_from_sql(f) for f, _ in rows], index=index)
    Y = pd.DataFrame(
        [{csv: getattr(a, col) for csv, col in TARGET_SQL.items()} for _, a in rows],
        index=index,
    )
    split = pd.Series([f.split for f, _ in rows], index=index)
    return TrainingData(X=X[FEATURE_COLUMNS], Y=Y, split=split)
```

- [ ] **Step 5: Réécrire `app/training/__main__.py`**

```python
"""Entrée CLI : ``uv run python -m app.training`` (lit le jeu préparé en base)."""

from __future__ import annotations

import argparse
from datetime import UTC, datetime

from app.db import session as db_session
from app.db.registry import CATBOOST_NAME, register_model
from app.db.training_data import load_training_data
from app.training.pipeline import TrainPipeline


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Entraînement CatBoost multi-cible (P5)"
    )
    parser.add_argument("--output-dir", default="models")
    parser.add_argument(
        "--no-kumo", action="store_true", help="N'évalue pas le modèle Kumo"
    )
    parser.add_argument(
        "--cv-splits", type=int, default=5, help="Nombre de plis de validation croisée"
    )
    return parser


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    factory = db_session.owner_session_factory()
    with factory() as session:
        try:
            data = load_training_data(session)
        except RuntimeError as exc:
            parser.error(str(exc))
            return
    pipe = TrainPipeline(
        training_data=data, output_dir=args.output_dir, cv_splits=args.cv_splits
    )
    metrics = pipe.run(include_kumo=not args.no_kumo)
    with factory() as session:
        model = register_model(
            session,
            name=CATBOOST_NAME,
            version=datetime.now(UTC).strftime("%Y%m%d%H%M%S"),
            mlflow_run_id=pipe.mlflow_run_id,
            artifact_path=str(args.output_dir),
        )
    print(f"[done] {model.name} v{model.version} activé — scores: {metrics}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest tests/test_db_training.py tests/test_cli.py tests/test_training.py -v`
Expected: tous PASS.

- [ ] **Step 7: Vérifier MLflow sur Postgres (manuel, une fois)**

```bash
uv run python -m app.db.create_db
uv run python -m app.db.ingest --year 2016 --csv data/2016_Building_Energy_Benchmarking.csv
uv run python -m app.db.prepare --year 2016
uv run python -m app.training --no-kumo --cv-splits 2
```

Expected : `[done] catboost-multitarget v… activé`. Si MLflow refuse le schéma `postgresql+psycopg`, ajouter `psycopg2-binary` (`uv add psycopg2-binary`) et utiliser `MLFLOW_TRACKING_URI=postgresql://…` ; consigner ce choix dans le rapport. Restaurer ensuite les artefacts de référence : `git checkout models/` (ne pas commiter un réentraînement).

- [ ] **Step 8: Commit**

```bash
git add app/db/training_data.py app/training tests/test_db_training.py tests/test_cli.py
git commit -m "feat(training): entraînement depuis Postgres et enregistrement de la version (#26)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 9: Authentification sur la table `users` (`sub = id`)

**Files:**
- Modify: `app/core/security.py`, `app/routers/auth.py`, `app/schemas/security.py`
- Test: `tests/test_jwt.py` (réécrit), `tests/conftest.py` (fixtures `demo_models`, `client`, `auth_headers`)

**Interfaces:**
- Consumes: `app.db.session.SessionDep`, `app.db.models.User`.
- Produces: `get_user_by_username(session, username) -> User | None`, `authenticate_user(session, username, password) -> User | None` (None si mot de passe faux **ou** utilisateur inactif), `create_access_token(data, expires_delta=None) -> str` (inchangée), `get_current_user(request, session, credentials, authorization) -> User` (synchrone ; positionne `request.state.user_id`). `app.schemas.security` ne contient plus que `Token`. Fixtures de test : `demo_models` (CatBoost synthétiques + scores), `client` (`TestClient` dépendant de `db`), `auth_headers` (token de `johndoe`).

- [ ] **Step 1: Déplacer les fixtures communes dans `tests/conftest.py`**

Déplacer depuis `tests/test_jwt.py` vers `tests/conftest.py` : la fonction `train_demo_model`, la constante `_SCORES` et la fixture `_isolated_models`, renommée **`demo_models`** et **sans** `autouse=True`. Ajouter les imports correspondants (`json`, `numpy as np`, `pandas as pd`, `CatBoostRegressor`, `model_service`, `metrics_service`, `CAT_FEATURES`, `FEATURE_COLUMNS`). Ajouter ensuite :

```python
from fastapi.testclient import TestClient


@pytest.fixture
def client(db):
    from app.main import app

    return TestClient(app)


def login(client, username: str, password: str):
    return client.post(
        "/token",
        data={"username": username, "password": password},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )


@pytest.fixture
def auth_headers(client):
    r = login(client, "johndoe", "secret")
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}
```

- [ ] **Step 2: Write the failing test** — remplacer tout `tests/test_jwt.py` par :

```python
"""Authentification JWT sur la table users (sub = id)."""

from datetime import timedelta

import jwt
import pytest
from conftest import login
from sqlalchemy import select

from app.core.security import ALGORITHM, SECRET_KEY, create_access_token
from app.db.models import User

pytestmark = pytest.mark.db


def _johndoe_id(db) -> int:
    with db() as s:
        return s.scalar(select(User.id).where(User.username == "johndoe"))


def test_token_sub_is_user_id(client, db):
    r = login(client, "johndoe", "secret")
    assert r.status_code == 200, r.text
    payload = jwt.decode(r.json()["access_token"], SECRET_KEY, algorithms=[ALGORITHM])
    assert payload["sub"] == str(_johndoe_id(db))


def test_wrong_password(client):
    assert login(client, "johndoe", "wrong").status_code == 400


def test_unknown_user(client):
    assert login(client, "nobody", "secret").status_code == 400


def test_inactive_user_cannot_login(client):
    assert login(client, "alice", "secret").status_code == 400


def test_list_requires_token(client):
    assert client.get("/model/list").status_code == 401


def test_list_with_token(client, auth_headers):
    r = client.get("/model/list", headers=auth_headers)
    assert r.status_code == 200, r.text


def test_bare_token_accepted(client, auth_headers):
    bare = auth_headers["Authorization"].removeprefix("Bearer ")
    assert client.get("/model/list", headers={"Authorization": bare}).status_code == 200


def test_token_with_non_numeric_sub_rejected(client):
    token = create_access_token({"sub": "johndoe"})
    r = client.get("/model/list", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 401


def test_token_of_deleted_user_rejected(client, db):
    with db() as s:
        user = User(username="ephemere", hashed_password="x", is_active=True)
        s.add(user)
        s.commit()
        token = create_access_token(
            {"sub": str(user.id)}, expires_delta=timedelta(minutes=5)
        )
        s.delete(user)
        s.commit()
    r = client.get("/model/list", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 401


def test_token_of_deactivated_user_rejected(client, db, auth_headers):
    with db() as s:
        s.get(User, _johndoe_id(db)).is_active = False
        s.commit()
    assert client.get("/model/list", headers=auth_headers).status_code == 401
```

- [ ] **Step 3: Run test to verify it fails**

Run: `uv run pytest tests/test_jwt.py -v`
Expected: FAIL — `test_token_sub_is_user_id` (sub vaut `"johndoe"`) et `test_inactive_user_cannot_login` (200).

- [ ] **Step 4: Implement**

`app/schemas/security.py` :

```python
from pydantic import BaseModel


class Token(BaseModel):
    access_token: str
    token_type: str
```

`app/core/security.py` : supprimer `fake_users_db`, `get_user`, l'import de `TokenData`/`UserInDB` et `from pydantic import ValidationError`. Ajouter les imports `from fastapi import Request`, `from sqlalchemy import select`, `from sqlalchemy.orm import Session`, `from ..db.models import User`, `from ..db.session import SessionDep`. Remplacer `authenticate_user` et `get_current_user` par :

```python
def get_user_by_username(session: Session, username: str) -> User | None:
    return session.scalar(select(User).where(User.username == username))


def authenticate_user(session: Session, username: str, password: str) -> User | None:
    user = get_user_by_username(session, username)
    if user is None:
        verify_password(password, DUMMY_HASH)  # temps constant
        return None
    if not verify_password(password, user.hashed_password) or not user.is_active:
        return None
    return user
```

```python
def get_current_user(
    request: Request,
    session: SessionDep,
    credentials: Annotated[
        HTTPAuthorizationCredentials | None, Depends(security)
    ] = None,
    authorization: Annotated[str | None, Header()] = None,
) -> User:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    token = _extract_token(credentials, authorization)
    if token is None:
        raise credentials_exception
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id = int(payload.get("sub"))
    except (InvalidTokenError, TypeError, ValueError):
        raise credentials_exception
    user = session.get(User, user_id)
    if user is None or not user.is_active:
        raise credentials_exception
    # Lu par le middleware de trace pour renseigner api_requests.user_id.
    request.state.user_id = user.id
    return user
```

`app/routers/auth.py` : remplacer l'import de `fake_users_db` par `from ..db.session import SessionDep`, puis :

```python
@router.post("/token", response_model=Token)
def login_for_access_token(
    form_data: Annotated[OAuth2PasswordRequestForm, Depends()],
    session: SessionDep,
) -> Token:
    user = authenticate_user(session, form_data.username, form_data.password)
    if user is None:
        raise HTTPException(status_code=400, detail="Incorrect username or password")
    access_token = create_access_token(
        data={"sub": str(user.id), "scope": " ".join(form_data.scopes)},
        expires_delta=timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES),
    )
    return Token(access_token=access_token, token_type="bearer")
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_jwt.py -v`
Expected: 10 PASS. Les tests de prédiction de l'ancien fichier sont réécrits en Task 11 ; `uv run pytest -q` doit rester vert.

- [ ] **Step 6: Commit**

```bash
git add app/core/security.py app/routers/auth.py app/schemas/security.py tests/conftest.py tests/test_jwt.py
git commit -m "feat(auth): utilisateurs en base, sub JWT = id, contrôle is_active (#26)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 10: Middleware de traçabilité

**Files:**
- Create: `app/middleware/__init__.py`, `app/middleware/trace.py`
- Modify: `app/main.py`
- Test: `tests/test_trace.py`

**Interfaces:**
- Consumes: `app.db.session.SessionLocal` (lu à chaque appel), `ApiRequest`, `redaction.to_trace`, `request.state.user_id` (Task 9).
- Produces: `TraceMiddleware` (ASGI pur). Pour les requêtes tracées, place dans `scope["state"]` : `api_request_id: int`, `request_id: str`. Ajoute l'en-tête de réponse `X-Request-ID`. Chemins non tracés : `UNTRACED_PATHS = {"/docs", "/docs/oauth2-redirect", "/redoc", "/openapi.json"}`. Handler global : `OperationalError` → 503 `{"detail": "Base de données indisponible"}`.

- [ ] **Step 1: Write the failing test**

`tests/test_trace.py` :

```python
"""Traçabilité : une ligne api_requests par appel (spec §4.3)."""

import uuid

import pytest
from conftest import login
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from app.db import session as db_session
from app.db.models import ApiRequest, User
from app.middleware.trace import TraceMiddleware

pytestmark = pytest.mark.db


def _trace(db, response) -> ApiRequest:
    rid = uuid.UUID(response.headers["x-request-id"])
    with db() as s:
        return s.scalar(select(ApiRequest).where(ApiRequest.request_id == rid))


def test_token_call_traced_without_secrets(client, db):
    r = login(client, "johndoe", "secret")
    row = _trace(db, r)
    assert row.path == "/token"
    assert row.method == "POST"
    assert row.status_code == 200
    assert row.request_body["password"] == "***"
    assert row.request_body["username"] == "johndoe"
    assert row.response_body["access_token"] == "***"
    assert row.duration_ms is not None
    assert row.client_ip is None  # "testclient" n'est pas une IP


def test_authenticated_call_records_user(client, db, auth_headers):
    r = client.get("/model/list", headers=auth_headers)
    with db() as s:
        johndoe = s.scalar(select(User.id).where(User.username == "johndoe"))
    row = _trace(db, r)
    assert row.user_id == johndoe
    assert row.status_code == 200
    assert isinstance(row.response_body, list)


def test_unauthenticated_call_traced_with_null_user(client, db):
    r = client.get("/model/list")
    row = _trace(db, r)
    assert row.status_code == 401
    assert row.user_id is None


def test_long_path_truncated(client, db):
    r = client.get("/" + "x" * 400)
    row = _trace(db, r)
    assert r.status_code == 404
    assert len(row.path) == 255


def test_docs_not_traced(client, db):
    with db() as s:
        before = s.scalar(select(func.count()).select_from(ApiRequest))
    r = client.get("/openapi.json")
    assert r.status_code == 200
    assert "x-request-id" not in r.headers
    with db() as s:
        assert s.scalar(select(func.count()).select_from(ApiRequest)) == before


def test_unhandled_exception_traced_as_500(db):
    mini = FastAPI()
    mini.add_middleware(TraceMiddleware)

    @mini.get("/boom")
    def boom():
        raise RuntimeError("boom")

    r = TestClient(mini, raise_server_exceptions=False).get("/boom")
    assert r.status_code == 500
    with db() as s:
        row = s.scalar(select(ApiRequest).where(ApiRequest.path == "/boom"))
    assert row.status_code == 500


def test_database_down_returns_503(monkeypatch):
    from app.main import app

    dead = create_engine(
        "postgresql+psycopg://x:y@127.0.0.1:1/none",
        connect_args={"connect_timeout": 1},
    )
    monkeypatch.setattr(db_session, "SessionLocal", sessionmaker(bind=dead))
    r = TestClient(app).get("/model/list")
    assert r.status_code == 503
    assert r.json() == {"detail": "Base de données indisponible"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_trace.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.middleware'`

- [ ] **Step 3: Write the middleware**

`app/middleware/__init__.py` :

```python
"""Middlewares ASGI de l'application."""
```

`app/middleware/trace.py` :

```python
"""Middleware ASGI : une ligne `api_requests` par appel (spec §4.3).

La ligne est insérée dès l'entrée (les prédictions peuvent la référencer et une
requête qui plante laisse une trace), puis complétée à la sortie.
"""

from __future__ import annotations

import ipaddress
import time
import uuid
from typing import Any

from sqlalchemy import update
from sqlalchemy.exc import SQLAlchemyError
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import Headers, MutableHeaders
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.db import session as db_session
from app.db.models import ApiRequest
from app.db.redaction import to_trace
from app.lib.tools import get_logger

log = get_logger(__name__)

UNTRACED_PATHS = frozenset({"/docs", "/docs/oauth2-redirect", "/redoc", "/openapi.json"})
MAX_PATH_LENGTH = 255


def _client_ip(scope: Scope) -> str | None:
    client = scope.get("client")
    if not client:
        return None
    try:
        return str(ipaddress.ip_address(client[0]))
    except ValueError:
        return None


def _insert_request(
    request_id: uuid.UUID,
    method: str,
    path: str,
    client_ip: str | None,
    request_body: Any,
) -> int:
    with db_session.SessionLocal() as session:
        row = ApiRequest(
            request_id=request_id,
            method=method,
            path=path[:MAX_PATH_LENGTH],
            client_ip=client_ip,
            request_body=request_body,
        )
        session.add(row)
        session.commit()
        return row.id


def _finalize_request(api_request_id: int, **values: Any) -> None:
    with db_session.SessionLocal() as session:
        session.execute(
            update(ApiRequest).where(ApiRequest.id == api_request_id).values(**values)
        )
        session.commit()


async def _buffer_body(receive: Receive) -> tuple[bytes, Receive]:
    """Lit tout le corps puis renvoie un ``receive`` qui le rejoue à l'app."""
    messages: list[Message] = []
    body = b""
    while True:
        message = await receive()
        messages.append(message)
        if message["type"] != "http.request":
            break
        body += message.get("body", b"")
        if not message.get("more_body", False):
            break
    pending = iter(messages)

    async def replay() -> Message:
        try:
            return next(pending)
        except StopIteration:
            return await receive()

    return body, replay


class TraceMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["path"] in UNTRACED_PATHS:
            await self.app(scope, receive, send)
            return

        start = time.perf_counter()
        request_id = uuid.uuid4()
        body, replay = await _buffer_body(receive)
        try:
            api_request_id = await run_in_threadpool(
                _insert_request,
                request_id,
                scope["method"],
                scope["path"],
                _client_ip(scope),
                to_trace(body, Headers(scope=scope).get("content-type")),
            )
        except SQLAlchemyError:
            log.exception("Trace impossible : base de données indisponible")
            response = JSONResponse(
                {"detail": "Base de données indisponible"}, status_code=503
            )
            await response(scope, replay, send)
            return

        state = scope.setdefault("state", {})
        state["api_request_id"] = api_request_id
        state["request_id"] = str(request_id)

        status_code: int | None = None
        content_type: str | None = None
        chunks: list[bytes] = []

        async def send_wrapper(message: Message) -> None:
            nonlocal status_code, content_type
            if message["type"] == "http.response.start":
                status_code = message["status"]
                headers = MutableHeaders(scope=message)
                headers["X-Request-ID"] = str(request_id)
                content_type = headers.get("content-type")
            elif message["type"] == "http.response.body":
                chunks.append(message.get("body", b""))
            await send(message)

        try:
            await self.app(scope, replay, send_wrapper)
        except Exception:
            status_code = status_code or 500
            raise
        finally:
            try:
                await run_in_threadpool(
                    _finalize_request,
                    api_request_id,
                    status_code=status_code,
                    duration_ms=int((time.perf_counter() - start) * 1000),
                    user_id=state.get("user_id"),
                    response_body=to_trace(b"".join(chunks), content_type),
                )
            except SQLAlchemyError:
                log.exception("Échec de la finalisation de la trace %s", request_id)
```

`app/main.py` :

```python
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy.exc import OperationalError

from .middleware.trace import TraceMiddleware
from .routers import auth, model

app = FastAPI()
app.add_middleware(TraceMiddleware)


@app.exception_handler(OperationalError)
async def database_unavailable(request: Request, exc: OperationalError) -> JSONResponse:
    return JSONResponse(status_code=503, content={"detail": "Base de données indisponible"})


app.include_router(auth.router)
app.include_router(model.router)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_trace.py tests/test_jwt.py -v`
Expected: tous PASS.

- [ ] **Step 5: Commit**

```bash
git add app/middleware app/main.py tests/test_trace.py
git commit -m "feat(api): middleware de traçabilité des requêtes et réponses (#26)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 11: Prédictions tracées (par ID, saisie libre, comparaison)

**Files:**
- Create: `app/core/prediction_service.py`
- Modify: `app/core/model_service.py`, `app/schemas/api.py`, `app/routers/model.py`
- Test: `tests/test_predict_api.py`, `tests/test_models.py`

**Interfaces:**
- Consumes: `registry.active_model`, `NoActiveModel`, `CATBOOST_NAME`, `KUMO_NAME`; `mapping.features_to_sql`, `features_from_sql`, `feature_values`; `kumo_service.predict_batch`; `request.state.api_request_id`, `request.state.request_id` (Task 10).
- Produces:
  - `model_service.predict_frame(df: DataFrame) -> dict[str, np.ndarray]` (clés `energy`, `emissions`, unités réelles).
  - `prediction_service`: `BuildingNotFound`, `YearNotFound`, `BuildingOutOfScope` (sous-classes de `LookupError`), `resolve_features(session, building_id, data_year=None) -> BuildingFeatures`, `features_from_request(req) -> dict` (clés SQL), `create_input(session, *, features, source, api_request_id, building_record_id=None) -> PredictionInput` (commit), `input_frame(inp) -> DataFrame`, `run_model(session, inp, model_name) -> Prediction` (commit).
  - `schemas.api`: `BuildingPredictionRequest(building_id: int, data_year: int | None = None)` (`extra="forbid"`) ; `EnergyPredictionResponse` + `prediction_id: int | None`, `request_id: str | None` ; `Model` + `version: str`, `is_active: bool`.
  - Routes : `POST /model/predict` (`BuildingPredictionRequest`), `POST /model/predict/features` (`EnergyPredictionRequest`), `POST /model/predict/compare` (`BuildingPredictionRequest`), `GET /model/list` (lit `ml_models`).

- [ ] **Step 1: Write the failing tests**

Ajouter à `tests/test_models.py` :

```python
def test_predict_frame_returns_vector_per_target(tmp_path, monkeypatch):
    for target in ("energy", "emissions"):
        path = tmp_path / f"{target}.cbm"
        _train(path)
        monkeypatch.setitem(model_service.MODEL_PATHS, target, str(path))
    monkeypatch.setattr(model_service, "_models", {})
    row = model_service._to_dataframe(_request())
    df = pd.concat([row, row], ignore_index=True)
    out = model_service.predict_frame(df)
    assert set(out) == {"energy", "emissions"}
    assert out["energy"].shape == (2,)
    assert (out["energy"] > 0).all()
```

(`_train` et `_request` sont les helpers existants de `tests/test_models.py`.)

`tests/test_predict_api.py` :

```python
"""Routes de prédiction : écriture input → prédiction → trace (spec §4.3)."""

import pytest
from sqlalchemy import func, select, update
from synth import EXAMPLE_FEATURES, add_record

from app.core import model_service
from app.db import mapping
from app.db.models import BuildingFeatures, MlModel, Prediction, PredictionInput
from app.db.registry import CATBOOST_NAME

pytestmark = pytest.mark.db

MANUAL_PAYLOAD = {
    "BuildingType": "Commercial",
    "PrimaryPropertyType": "Office",
    "Neighborhood": "Ballard",
    "Latitude": 47.62,
    "Longitude": -122.35,
    "YearBuilt": 1990,
    "NumberofBuildings": 1,
    "NumberofFloors": 4,
    "PropertyGFAParking": 5000,
    "PropertyGFABuilding": 15000,
    "LargestPropertyUseType": "Office",
    "SecondLargestPropertyUseType": "Retail",
    "SecondLargestPropertyUseTypeGFA": 3000,
    "ThirdLargestPropertyUseType": "Parking",
    "ThirdLargestPropertyUseTypeGFA": 2000,
    "Has_NaturalGas": True,
    "Has_Steam": False,
}


@pytest.fixture
def buildings(db):
    """Bâtiment 1 (2016, 2018) dans le périmètre ; bâtiment 2 résidentiel."""
    with db() as s:
        r16 = add_record(s, 1, 2016)
        r18 = add_record(s, 1, 2018)
        add_record(s, 2, 2018, building_type="Multifamily LR (1-4)")
        for rec in (r16, r18):
            s.add(
                BuildingFeatures(
                    record_id=rec.id,
                    dataset_role="production",
                    is_training_eligible=False,
                    prep_version="t",
                    **mapping.features_to_sql(EXAMPLE_FEATURES),
                )
            )
        s.commit()
        return {"2016": r16.id, "2018": r18.id}


def _input(db, prediction_id) -> PredictionInput:
    with db() as s:
        pred = s.get(Prediction, prediction_id)
        return s.get(PredictionInput, pred.prediction_input_id)


def test_predict_by_id_uses_latest_year(client, db, auth_headers, demo_models, buildings):
    r = client.post("/model/predict", json={"building_id": 1}, headers=auth_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["energy_use_kbtu"] > 0
    assert body["request_id"] == r.headers["x-request-id"]
    inp = _input(db, body["prediction_id"])
    assert inp.input_source == "building_id"
    assert inp.building_record_id == buildings["2018"]
    assert inp.api_request_id is not None


def test_predict_by_id_and_year(client, db, auth_headers, demo_models, buildings):
    r = client.post(
        "/model/predict", json={"building_id": 1, "data_year": 2016}, headers=auth_headers
    )
    assert r.status_code == 200, r.text
    assert _input(db, r.json()["prediction_id"]).building_record_id == buildings["2016"]


def test_unknown_building_404(client, auth_headers, buildings):
    r = client.post("/model/predict", json={"building_id": 999}, headers=auth_headers)
    assert r.status_code == 404


def test_missing_year_404(client, auth_headers, buildings):
    r = client.post(
        "/model/predict", json={"building_id": 1, "data_year": 2017}, headers=auth_headers
    )
    assert r.status_code == 404


def test_residential_building_422(client, auth_headers, buildings):
    r = client.post("/model/predict", json={"building_id": 2}, headers=auth_headers)
    assert r.status_code == 422
    assert "hors périmètre" in r.json()["detail"]


def test_predict_rejects_extra_field(client, auth_headers, buildings):
    r = client.post(
        "/model/predict", json={"building_id": 1, "x": 1}, headers=auth_headers
    )
    assert r.status_code == 422


def test_predict_requires_token(client, buildings):
    assert client.post("/model/predict", json={"building_id": 1}).status_code == 401


def test_manual_features_prediction(client, db, auth_headers, demo_models):
    r = client.post("/model/predict/features", json=MANUAL_PAYLOAD, headers=auth_headers)
    assert r.status_code == 200, r.text
    inp = _input(db, r.json()["prediction_id"])
    assert inp.input_source == "manual"
    assert inp.building_record_id is None
    assert inp.property_gfa_buildings == 15000


def test_manual_features_reject_extra_field(client, auth_headers):
    bad = dict(MANUAL_PAYLOAD, extra_field="nope")
    r = client.post("/model/predict/features", json=bad, headers=auth_headers)
    assert r.status_code == 422


def test_compare_one_input_two_predictions(client, db, auth_headers, demo_models, buildings):
    r = client.post(
        "/model/predict/compare", json={"building_id": 1}, headers=auth_headers
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["kumo_prediction"]["model_name"] == "kumo-tabular-zero-shot"
    cb_input = _input(db, body["catboost_prediction"]["prediction_id"])
    km_input = _input(db, body["kumo_prediction"]["prediction_id"])
    assert cb_input.id == km_input.id


def test_model_failure_keeps_input_without_prediction(
    client, db, auth_headers, buildings, monkeypatch
):
    def boom(df):
        raise FileNotFoundError("modèle absent")

    monkeypatch.setattr(model_service, "predict_frame", boom)
    with db() as s:
        before = s.scalar(select(func.count()).select_from(PredictionInput))
    r = client.post("/model/predict", json={"building_id": 1}, headers=auth_headers)
    assert r.status_code == 503
    with db() as s:
        assert s.scalar(select(func.count()).select_from(PredictionInput)) == before + 1
        assert s.scalar(select(func.count()).select_from(Prediction)) == 0


def test_no_active_model_503(client, db, auth_headers, demo_models, buildings):
    with db() as s:
        s.execute(
            update(MlModel).where(MlModel.name == CATBOOST_NAME).values(is_active=False)
        )
        s.commit()
    r = client.post("/model/predict", json={"building_id": 1}, headers=auth_headers)
    assert r.status_code == 503
    assert "Aucun modèle actif" in r.json()["detail"]


def test_model_list_reads_registry(client, auth_headers):
    r = client.get("/model/list", headers=auth_headers)
    assert r.status_code == 200
    names = {m["name"]: m for m in r.json()}
    assert names[CATBOOST_NAME]["version"] == "baseline"
    assert names[CATBOOST_NAME]["is_active"] is True
    assert "kumo-tabular-zero-shot" in names


def test_metrics_with_token(client, auth_headers, demo_models):
    r = client.get("/model/metrics", headers=auth_headers)
    assert r.status_code == 200, r.text
    assert r.json()["targets"]["energy"]["unit"] == "kBtu/an"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_predict_api.py tests/test_models.py -v`
Expected: FAIL — `AttributeError: module 'app.core.model_service' has no attribute 'predict_frame'` et 422 sur `/model/predict` (ancien schéma).

- [ ] **Step 3: Ajouter `predict_frame` à `app/core/model_service.py`**

```python
def predict_frame(df: pd.DataFrame) -> dict[str, np.ndarray]:
    """Prédit toutes les cibles pour un DataFrame FEATURE_COLUMNS (unités réelles)."""
    X = df[FEATURE_COLUMNS].copy()
    for col in CAT_FEATURES:
        X[col] = X[col].astype(str)
    pool = Pool(X, cat_features=CAT_FEATURES)
    return {target: np.expm1(load_model(target).predict(pool)) for target in TARGETS}
```

- [ ] **Step 4: Mettre à jour `app/schemas/api.py`**

Ajouter `version: str` et `is_active: bool` à `Model` ; ajouter à `EnergyPredictionResponse` :

```python
    prediction_id: int | None = None
    request_id: str | None = None
```

et la nouvelle classe :

```python
class BuildingPredictionRequest(BaseModel):
    """Prédiction d'un bâtiment connu ; année la plus récente si absente."""

    model_config = ConfigDict(extra="forbid")

    building_id: int
    data_year: int | None = None
```

- [ ] **Step 5: Écrire `app/core/prediction_service.py`**

```python
"""Prédictions tracées : snapshot de l'input en base, puis appel du modèle."""

from __future__ import annotations

from typing import Any

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import kumo_service, model_service
from app.db.mapping import features_from_sql, features_to_sql
from app.db.models import Building, BuildingFeatures, BuildingRecordRaw, Prediction, PredictionInput
from app.db.registry import KUMO_NAME, active_model
from app.schemas.api import FEATURE_COLUMNS, TARGETS, EnergyPredictionRequest


class BuildingNotFound(LookupError):
    pass


class YearNotFound(LookupError):
    pass


class BuildingOutOfScope(LookupError):
    pass


def resolve_features(
    session: Session, building_id: int, data_year: int | None = None
) -> BuildingFeatures:
    """Features du bâtiment pour l'année demandée (ou la plus récente).

    Ne lit que id/building_id/data_year de building_records_raw (droit par
    colonne du rôle API, aucune PII).
    """
    if session.get(Building, building_id) is None:
        raise BuildingNotFound(building_id)
    base = (
        select(BuildingFeatures)
        .join(BuildingRecordRaw, BuildingRecordRaw.id == BuildingFeatures.record_id)
        .where(BuildingRecordRaw.building_id == building_id)
    )
    if data_year is None:
        row = session.scalars(
            base.order_by(BuildingRecordRaw.data_year.desc()).limit(1)
        ).first()
        if row is None:
            raise BuildingOutOfScope(building_id)
        return row
    row = session.scalars(base.where(BuildingRecordRaw.data_year == data_year)).first()
    if row is None:
        if session.scalars(base.limit(1)).first() is None:
            raise BuildingOutOfScope(building_id)
        raise YearNotFound(data_year)
    return row


def features_from_request(request: EnergyPredictionRequest) -> dict[str, Any]:
    data = request.model_dump()
    data["PropertyGFABuilding(s)"] = data.pop("PropertyGFABuilding")
    return features_to_sql(data)


def create_input(
    session: Session,
    *,
    features: dict[str, Any],
    source: str,
    api_request_id: int | None,
    building_record_id: int | None = None,
) -> PredictionInput:
    """Enregistre et commit le snapshot AVANT tout appel au modèle."""
    inp = PredictionInput(
        input_source=source,
        api_request_id=api_request_id,
        building_record_id=building_record_id,
        **features,
    )
    session.add(inp)
    session.commit()
    return inp


def input_frame(inp: PredictionInput) -> pd.DataFrame:
    return pd.DataFrame([features_from_sql(inp)])[FEATURE_COLUMNS]


def run_model(session: Session, inp: PredictionInput, model_name: str) -> Prediction:
    """Prédit depuis la ligne stockée (pas depuis le payload HTTP)."""
    model = active_model(session, model_name)
    frame = input_frame(inp)
    if model_name == KUMO_NAME:
        values = {t: float(kumo_service.predict_batch(frame, t)[0]) for t in TARGETS}
    else:
        values = {t: float(v[0]) for t, v in model_service.predict_frame(frame).items()}
    prediction = Prediction(
        prediction_input_id=inp.id,
        model_id=model.id,
        energy_use_kbtu=values["energy"],
        ghg_emissions_tco2e=values["emissions"],
    )
    session.add(prediction)
    session.commit()
    return prediction
```

- [ ] **Step 6: Réécrire `app/routers/model.py`**

```python
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..core import metrics_service
from ..core import prediction_service as ps
from ..core.security import get_current_user
from ..db.mapping import feature_values
from ..db.models import BuildingFeatures, MlModel, Prediction, PredictionInput
from ..db.registry import CATBOOST_NAME, KUMO_NAME, NoActiveModel
from ..db.session import SessionDep
from ..schemas.api import (
    BuildingPredictionRequest,
    ComparisonPredictionResponse,
    EnergyPredictionRequest,
    EnergyPredictionResponse,
    MetricsResponse,
    Model,
)

router = APIRouter(
    prefix="/model",
    tags=["model"],
    dependencies=[Depends(get_current_user)],
    responses={404: {"description": "Not found"}},
)

PREDICT_RESPONSES = {
    404: {"description": "Bâtiment ou année introuvable"},
    422: {"description": "Bâtiment hors périmètre du modèle"},
    503: {"description": "Modèle ou base indisponible"},
}


@router.get("/list", response_model=list[Model])
def read_models_list(session: SessionDep):
    models = session.scalars(select(MlModel).order_by(MlModel.id))
    return [
        Model(
            id=m.id,
            name=m.name,
            version=m.version,
            is_active=m.is_active,
            created_at=m.created_at,
        )
        for m in models
    ]


@router.get(
    "/metrics",
    response_model=MetricsResponse,
    responses={404: {"description": "Metrics file not found"}},
)
async def read_metrics():
    try:
        return MetricsResponse(**metrics_service.get_metrics())
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


def _resolve(session: Session, payload: BuildingPredictionRequest) -> BuildingFeatures:
    try:
        return ps.resolve_features(session, payload.building_id, payload.data_year)
    except ps.BuildingNotFound:
        raise HTTPException(404, f"Bâtiment {payload.building_id} inconnu")
    except ps.YearNotFound:
        raise HTTPException(
            404,
            f"Aucune donnée {payload.data_year} pour le bâtiment {payload.building_id}",
        )
    except ps.BuildingOutOfScope:
        raise HTTPException(
            422,
            f"Bâtiment {payload.building_id} hors périmètre du modèle "
            "(résidentiel ou données incomplètes)",
        )


def _input_from_building(
    session: Session, request: Request, payload: BuildingPredictionRequest
) -> PredictionInput:
    features = _resolve(session, payload)
    return ps.create_input(
        session,
        features=feature_values(features),
        source="building_id",
        api_request_id=request.state.api_request_id,
        building_record_id=features.record_id,
    )


def _run(session: Session, inp: PredictionInput, model_name: str) -> Prediction:
    try:
        return ps.run_model(session, inp, model_name)
    except NoActiveModel:
        raise HTTPException(503, f"Aucun modèle actif : {model_name}")
    except FileNotFoundError as exc:
        raise HTTPException(503, f"{model_name}: {exc}")
    except Exception as exc:  # noqa: BLE001
        if model_name != KUMO_NAME:
            raise
        raise HTTPException(503, f"Kumo-Tabular: {exc}")


def _response(
    prediction: Prediction, model_name: str, request: Request
) -> EnergyPredictionResponse:
    return EnergyPredictionResponse(
        model_name=model_name,
        energy_use_kbtu=prediction.energy_use_kbtu,
        ghg_emissions_tco2e=prediction.ghg_emissions_tco2e,
        predicted_at=prediction.predicted_at,
        prediction_id=prediction.id,
        request_id=request.state.request_id,
    )


@router.post(
    "/predict", response_model=EnergyPredictionResponse, responses=PREDICT_RESPONSES
)
def write_prediction(
    payload: BuildingPredictionRequest, request: Request, session: SessionDep
):
    inp = _input_from_building(session, request, payload)
    return _response(_run(session, inp, CATBOOST_NAME), CATBOOST_NAME, request)


@router.post(
    "/predict/features",
    response_model=EnergyPredictionResponse,
    responses={503: {"description": "Modèle ou base indisponible"}},
)
def write_prediction_from_features(
    payload: EnergyPredictionRequest, request: Request, session: SessionDep
):
    inp = ps.create_input(
        session,
        features=ps.features_from_request(payload),
        source="manual",
        api_request_id=request.state.api_request_id,
    )
    return _response(_run(session, inp, CATBOOST_NAME), CATBOOST_NAME, request)


@router.post(
    "/predict/compare",
    response_model=ComparisonPredictionResponse,
    responses=PREDICT_RESPONSES,
)
def write_comparison(
    payload: BuildingPredictionRequest, request: Request, session: SessionDep
):
    inp = _input_from_building(session, request, payload)
    catboost = _run(session, inp, CATBOOST_NAME)
    kumo = _run(session, inp, KUMO_NAME)
    return ComparisonPredictionResponse(
        catboost_prediction=_response(catboost, CATBOOST_NAME, request),
        kumo_prediction=_response(kumo, KUMO_NAME, request),
    )
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `uv run pytest tests/test_predict_api.py tests/test_models.py -v`
Expected: tous PASS. Puis `uv run pytest -q` : suite complète verte.

- [ ] **Step 8: Commit**

```bash
git add app/core/prediction_service.py app/core/model_service.py app/schemas/api.py app/routers/model.py tests/test_predict_api.py tests/test_models.py
git commit -m "feat(api): prédiction par building_id tracée en base (#26)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 12: Évaluation projetée 2017–2019

**Files:**
- Create: `app/db/evaluate.py`
- Test: `tests/test_db_evaluate.py`

**Interfaces:**
- Consumes: `registry.active_model`, `CATBOOST_NAME`; `mapping.feature_values`, `features_from_sql`; `model_service.predict_frame`; vue `v_projected_evaluation`; `metrics_reelles`.
- Produces: `evaluate_years(session, years, *, batch_size=500) -> pd.DataFrame` (colonnes `data_year`, `target`, `n`, `R2`, `MAE`, `MedAE`, `MedAPE_%`), `projected_metrics(session, model, years) -> pd.DataFrame`, `main(argv=None)`.

- [ ] **Step 1: Write the failing test**

`tests/test_db_evaluate.py` :

```python
"""Évaluation projetée : prédictions batch + métriques depuis la vue."""

import pytest
from sqlalchemy import func, select
from synth import make_synth

from app.db import evaluate, ingest, prepare
from app.db import session as db_session
from app.db.models import Prediction, PredictionInput

pytestmark = pytest.mark.db


def _production_year(db, year=2018, n=40):
    df = make_synth(n).assign(DataYear=year)
    with db() as s:
        ingest.ingest_frame(s, df, year=year, source_file=f"{year}.csv")
        return prepare.prepare_year(s, year)


def test_evaluate_creates_batch_predictions_once(db, demo_models):
    n = _production_year(db)
    with db() as s:
        metrics = evaluate.evaluate_years(s, [2018], batch_size=7)
        assert s.scalar(select(func.count()).select_from(Prediction)) == n
        inputs = s.scalars(select(PredictionInput)).all()
        assert {i.input_source for i in inputs} == {"batch"}
        assert all(i.api_request_id is None for i in inputs)
        evaluate.evaluate_years(s, [2018])
        assert s.scalar(select(func.count()).select_from(Prediction)) == n
    assert set(metrics["target"]) == {"energy", "emissions"}
    assert (metrics["data_year"] == 2018).all()
    assert (metrics["n"] > 0).all()


def test_evaluate_without_data_returns_empty(db, demo_models):
    with db() as s:
        assert evaluate.evaluate_years(s, [2019]).empty


def test_evaluate_main(db, demo_models, monkeypatch, capsys):
    _production_year(db, year=2017, n=20)
    monkeypatch.setattr(db_session, "owner_session_factory", lambda: db)
    evaluate.main(["--years", "2017"])
    assert "2017" in capsys.readouterr().out
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_db_evaluate.py -v`
Expected: FAIL — `ImportError: cannot import name 'evaluate'`

- [ ] **Step 3: Write minimal implementation**

`app/db/evaluate.py` :

```python
"""Évaluation projetée du modèle actif sur les années de production.

Usage : ``uv run python -m app.db.evaluate --years 2017 2018 2019``
"""

from __future__ import annotations

import argparse

import pandas as pd
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.core import model_service
from app.db import session as db_session
from app.db.mapping import feature_values, features_from_sql
from app.db.models import (
    BuildingFeatures,
    BuildingRecordRaw,
    MlModel,
    Prediction,
    PredictionInput,
)
from app.db.registry import CATBOOST_NAME, active_model
from app.lib.tools import metrics_reelles
from app.schemas.api import FEATURE_COLUMNS

TARGET_PAIRS = {
    "energy": ("predicted_energy_kbtu", "actual_energy_kbtu"),
    "emissions": ("predicted_ghg_tco2e", "actual_ghg_tco2e"),
}


def _pending_features(
    session: Session, model: MlModel, years: list[int]
) -> list[BuildingFeatures]:
    """Bâtiments de production pas encore prédits en batch par ce modèle."""
    done = (
        select(PredictionInput.building_record_id)
        .join(Prediction, Prediction.prediction_input_id == PredictionInput.id)
        .where(Prediction.model_id == model.id, PredictionInput.input_source == "batch")
    )
    return session.scalars(
        select(BuildingFeatures)
        .join(BuildingRecordRaw, BuildingRecordRaw.id == BuildingFeatures.record_id)
        .where(
            BuildingFeatures.dataset_role == "production",
            BuildingRecordRaw.data_year.in_(years),
            BuildingFeatures.record_id.not_in(done),
        )
        .order_by(BuildingFeatures.record_id)
    ).all()


def projected_metrics(
    session: Session, model: MlModel, years: list[int]
) -> pd.DataFrame:
    rows = session.execute(
        text(
            "SELECT * FROM v_projected_evaluation "
            "WHERE model_name = :name AND model_version = :version "
            "AND data_year = ANY(:years)"
        ),
        {"name": model.name, "version": model.version, "years": years},
    ).mappings().all()
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    out = []
    for year, group in df.groupby("data_year"):
        for target, (pred_col, actual_col) in TARGET_PAIRS.items():
            ok = group[actual_col] > 0
            scores = metrics_reelles(group.loc[ok, actual_col], group.loc[ok, pred_col])
            out.append({"data_year": int(year), "target": target, "n": int(ok.sum()), **scores})
    return pd.DataFrame(out)


def evaluate_years(
    session: Session, years: list[int], *, batch_size: int = 500
) -> pd.DataFrame:
    model = active_model(session, CATBOOST_NAME)
    pending = _pending_features(session, model, years)
    for start in range(0, len(pending), batch_size):
        chunk = pending[start : start + batch_size]
        inputs = [
            PredictionInput(
                input_source="batch",
                building_record_id=f.record_id,
                **feature_values(f),
            )
            for f in chunk
        ]
        session.add_all(inputs)
        session.flush()  # inputs écrits avant l'appel au modèle
        frame = pd.DataFrame([features_from_sql(i) for i in inputs])[FEATURE_COLUMNS]
        preds = model_service.predict_frame(frame)
        session.add_all(
            Prediction(
                prediction_input_id=inp.id,
                model_id=model.id,
                energy_use_kbtu=float(energy),
                ghg_emissions_tco2e=float(ghg),
            )
            for inp, energy, ghg in zip(inputs, preds["energy"], preds["emissions"])
        )
        session.commit()
    return projected_metrics(session, model, years)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Évaluation projetée")
    parser.add_argument("--years", type=int, nargs="+", required=True)
    args = parser.parse_args(argv)
    with db_session.owner_session_factory()() as session:
        metrics = evaluate_years(session, args.years)
    if metrics.empty:
        print("[evaluate] aucune donnée de production pour ces années")
        return
    print(metrics.to_string(index=False))


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_db_evaluate.py -v`
Expected: 3 PASS.

- [ ] **Step 5: Commit**

```bash
git add app/db/evaluate.py tests/test_db_evaluate.py
git commit -m "feat(db): évaluation projetée sur les années de production (#26)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 13: Docker Compose complet, documentation et livrables

**Files:**
- Modify: `docker-compose.yml`, `README.md`
- Create: `docs/db/README.md`, `docs/db/schema.sql`

**Interfaces:**
- Consumes: toutes les CLIs (`app.db.create_db|ingest|prepare|evaluate`, `app.training`).
- Produces: `docker compose up` démarre `db` + `api` ; `docker compose run --rm tools …` exécute les CLIs avec les identifiants propriétaire/admin, jamais exposés au service `api`.

- [ ] **Step 1: Compléter `docker-compose.yml`**

Ajouter sous `services:` :

```yaml
  api:
    build: .
    environment:
      SECRET_KEY: ${SECRET_KEY:?définir SECRET_KEY dans .env}
      DATABASE_URL: postgresql+psycopg://p5_api:${P5_API_PASSWORD}@db:5432/p5
    depends_on:
      db:
        condition: service_healthy
    ports:
      - "8080:8080"
    volumes:
      - ./models:/app/models:ro

  # Outillage (non démarré par `up`) : provisionnement, ingestion, préparation,
  # évaluation. Seul ce service reçoit les identifiants admin/propriétaire.
  tools:
    build: .
    profiles: ["tools"]
    environment:
      SECRET_KEY: ${SECRET_KEY}
      DATABASE_ADMIN_URL: postgresql+psycopg://postgres:${POSTGRES_PASSWORD}@db:5432/postgres
      DATABASE_OWNER_URL: postgresql+psycopg://p5_owner:${P5_OWNER_PASSWORD}@db:5432/p5
      P5_OWNER_PASSWORD: ${P5_OWNER_PASSWORD}
      P5_API_PASSWORD: ${P5_API_PASSWORD}
      P5_MLFLOW_PASSWORD: ${P5_MLFLOW_PASSWORD}
      TRAINING_YEAR: ${TRAINING_YEAR:-2016}
    depends_on:
      db:
        condition: service_healthy
    volumes:
      - ./data:/app/data:ro
      - ./models:/app/models:ro
```

- [ ] **Step 2: Vérifier le parcours complet**

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

Expected : réponse 200 avec `prediction_id` et `request_id` ; 3 lignes de trace, dont `/model/predict` avec un `user_id` renseigné et `/token` avec un `password` masqué. Si `docker compose build` échoue faute de nouvelles dépendances dans l'image de base GHCR, construire l'image de base localement (`docker build -f Dockerfile.base -t p5-base .`) puis `docker compose build --build-arg BASE_IMAGE=p5-base`, et le signaler dans le rapport : l'image `:base` devra être republiée par `base-image.yml`.

- [ ] **Step 3: Générer le DDL livrable**

```bash
DATABASE_OWNER_URL=postgresql+psycopg://x@localhost/p5 uv run alembic upgrade head --sql > docs/db/schema.sql
```

Vérifier que le fichier contient les `CREATE TABLE`, les `CHECK` et `CREATE VIEW v_projected_evaluation`.

- [ ] **Step 4: Écrire `docs/db/README.md`**

Contenu obligatoire, dans cet ordre :
1. **Schéma** : le bloc `mermaid` `erDiagram` du §3.1 de la spec (copié tel quel) et un lien vers `schema.sql`.
2. **Choix techniques** : un paragraphe par décision D1–D11 de la spec, plus les 5 écarts listés dans « Global Constraints » de ce plan.
3. **Rôles et sécurité** : le tableau du §5.2 de la spec.
4. **Mise en route** : les commandes du Step 2 de cette tâche.
5. **Exemples de requêtes SQL** :

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

- [ ] **Step 5: Mettre à jour `README.md`**

Ajouter une section « Base de données » qui renvoie vers `docs/db/README.md` et résume le démarrage (`cp .example.env .env`, `docker compose up -d db`, `create_db`, `ingest`, `prepare`, `up -d api`). Remplacer les exemples `curl` de `/model/predict` basés sur les features par `{"building_id": …}` et mentionner `/model/predict/features` pour la saisie libre.

- [ ] **Step 6: Vérification finale**

```bash
uv run ruff check app tests
uv run ruff format --check app tests
uv run pytest --cov=app -q
```

Expected : aucune erreur ruff ; tous les tests passent (aucun `skipped` quand Postgres tourne) ; couverture ≥ 70 %.

- [ ] **Step 7: Commit**

```bash
git add docker-compose.yml docs/db README.md
git commit -m "docs(db): schéma UML, DDL, guide de mise en route et compose complet (#26)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```
