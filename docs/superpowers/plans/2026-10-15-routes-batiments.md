# Routes de consultation des bâtiments (PR 2) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal :** Un utilisateur retrouve un bâtiment par nom, adresse ou quartier, récupère son identifiant, puis prédit dessus ; seuls des bâtiments jamais vus par l'entraînement (ni `train` ni `test`) sont consultables et prédictibles par `building_id`.

**Architecture :** Un service `building_service` porte la seule définition de « consultable » (`buildings.split IS NULL` et au moins une ligne `building_years`). Un router `/buildings` (liste paginée filtrable, détail) l'utilise ; `resolve_features` refuse un bâtiment vu (403) pour `/model/predict` et `/model/predict/compare`. Aucune migration : le schéma de la PR 1 suffit.

**Tech Stack :** Python 3.14, FastAPI, SQLAlchemy 2.0, PostgreSQL 17, pytest, ruff, uv.

Spec : `docs/superpowers/specs/2026-10-15-schema-simplifie-routes-batiments-design.md` (§6, §8). Issue : #45.

---

## Décisions de ce plan

1. **403 sur un bâtiment vu pour la prédiction, 404 pour la consultation** (la consultation ne révèle pas l'existence d'un bâtiment vu ; la prédiction part d'un identifiant déjà connu de l'appelant).
2. **Les lignes 2016 des bâtiments exclus de l'entraînement sont consultables** (validé : `split IS NULL` suffit, aucune borne d'année).
3. **Aucune valeur réelle** (consommation, émissions) n'est exposée ; `building_actuals` reste inaccessible au rôle API.
4. **Recherche par `ILIKE`** sur nom et adresse avec échappement de `%`, `_` et `\` ; pas d'index trigramme (environ 3 200 bâtiments).

## Structure des fichiers

| Fichier | Rôle |
|---|---|
| `app/core/building_service.py` (créer) | `unseen_conditions`, filtres, recherche paginée, détail |
| `app/schemas/buildings.py` (créer) | Modèles de réponse `/buildings` |
| `app/routers/buildings.py` (créer) | Routes `GET /buildings` et `GET /buildings/{building_id}` |
| `app/main.py` | Enregistre le router |
| `app/core/prediction_service.py` | `BuildingSeen`, refus dans `resolve_features` |
| `app/routers/model.py` | 403 dans `_resolve`, documentation OpenAPI |
| `tests/synth.py` | `add_building` accepte l'identité |
| `tests/test_buildings_api.py` (créer) | Tests de la consultation |
| `tests/test_predict_api.py`, `tests/test_api_role_e2e.py` | 403 et routes sous le rôle API |
| `README.md`, `docs/db/README.md` | Documentation |

---

### Task 0 : Branche

La branche `feat/buildings-routes-45` est déjà créée depuis `main` (PR 1 mergée). Vérifier : `git branch --show-current` affiche `feat/buildings-routes-45` et `REQUIRE_TEST_DB=1 uv run pytest -q` est vert avant de commencer.

---

### Task 1 : Prédiction refusée pour un bâtiment vu

**Files :**
- Modify: `app/core/prediction_service.py`
- Modify: `app/routers/model.py`
- Modify: `tests/test_predict_api.py`

- [ ] **Step 1 : Écrire les tests** — dans `tests/test_predict_api.py`, ajouter après la fixture `buildings` :

```python
@pytest.fixture
def seen_buildings(db):
    """Bâtiments 10 (train) et 11 (test) : vus par l'entraînement."""
    with db() as s:
        add_year(s, 10, 2018, split="train")
        add_year(s, 11, 2018, split="test")
        s.commit()
```

et à la fin du fichier :

```python
@pytest.mark.parametrize("building_id", [10, 11])
@pytest.mark.parametrize("payload_extra", [{}, {"data_year": 2018}])
@pytest.mark.parametrize("route", ["/model/predict", "/model/predict/compare"])
def test_seen_building_prediction_403(
    client,
    db,
    auth_headers,
    demo_models,
    seen_buildings,
    route,
    payload_extra,
    building_id,
):
    r = client.post(
        route, json={"building_id": building_id, **payload_extra}, headers=auth_headers
    )
    assert r.status_code == 403, r.text
    assert "entraînement" in r.json()["detail"]
    with db() as s:
        assert s.scalar(select(func.count()).select_from(Prediction)) == 0


def test_manual_features_unaffected_by_seen_buildings(
    client, auth_headers, demo_models, seen_buildings
):
    r = client.post(
        "/model/predict/features", json=MANUAL_PAYLOAD, headers=auth_headers
    )
    assert r.status_code == 200, r.text
```

- [ ] **Step 2 : Vérifier l'échec**

Run: `REQUIRE_TEST_DB=1 uv run pytest tests/test_predict_api.py -q -k seen`
Expected: FAIL (`assert 200 == 403`).

- [ ] **Step 3 : Modifier `app/core/prediction_service.py`**

Après la classe `BuildingOutOfScope`, ajouter :

```python
class BuildingSeen(LookupError):
    """Le bâtiment a servi à l'entraînement ou à son évaluation (train ou test)."""
```

Dans `resolve_features`, remplacer

```python
    if session.get(Building, building_id) is None:
        raise BuildingNotFound(building_id)
```

par

```python
    building = session.get(Building, building_id)
    if building is None:
        raise BuildingNotFound(building_id)
    if building.split is not None:
        raise BuildingSeen(building_id)
```

- [ ] **Step 4 : Modifier `app/routers/model.py`**

Dans `BUILDING_RESPONSES`, ajouter l'entrée `403` :

```python
BUILDING_RESPONSES = {
    403: {"description": "Bâtiment déjà vu par l'entraînement"},
    404: {"description": "Bâtiment ou année introuvable"},
    422: {"description": "Bâtiment hors périmètre du modèle"},
    **UNAVAILABLE,
}
```

Dans `_resolve`, ajouter avant `except ps.YearNotFound:` :

```python
    except ps.BuildingSeen:
        raise HTTPException(
            403,
            f"Bâtiment {payload.building_id} déjà vu par l'entraînement : "
            "prédiction par identifiant refusée (voir GET /buildings)",
        )
```

- [ ] **Step 5 : Vérifier**

Run: `uv run ruff format app tests && uv run ruff check app tests && REQUIRE_TEST_DB=1 uv run pytest tests/test_predict_api.py tests/test_trace.py -q`
Expected: PASS.

- [ ] **Step 6 : Commit**

```bash
git add app tests
git commit -m "feat(api): refuser la prédiction par identifiant d'un bâtiment vu (#45)"
```

---

### Task 2 : Router `/buildings`

**Files :**
- Modify: `tests/synth.py`
- Create: `tests/test_buildings_api.py`
- Create: `app/core/building_service.py`
- Create: `app/schemas/buildings.py`
- Create: `app/routers/buildings.py`
- Modify: `app/main.py`

- [ ] **Step 1 : Étendre `add_building` dans `tests/synth.py`** — remplacer la fonction par :

```python
def add_building(
    session: Session, building_id: int, split: str | None = None, **identity
) -> Building:
    """Crée (si besoin) un bâtiment sans année : hors périmètre du modèle."""
    building = session.get(Building, building_id)
    if building is None:
        building = Building(id=building_id, split=split, **identity)
        session.add(building)
        session.flush()
    return building
```

- [ ] **Step 2 : Écrire les tests** — créer `tests/test_buildings_api.py` :

```python
"""Consultation des bâtiments jamais vus : /buildings."""

import pytest
from synth import add_building, add_year

pytestmark = pytest.mark.db


@pytest.fixture
def catalogue(db):
    """1 et 4 jamais vus ; 2 (train) et 3 (test) vus ; 5 sans ligne d'année."""
    with db() as s:
        add_building(
            s,
            1,
            property_name="Space Needle",
            address="400 Broad St",
            zip_code="98109",
            neighborhood="LAKE UNION",
            building_type="NonResidential",
            primary_property_type="Hotel",
        )
        add_year(s, 1, 2017)
        add_year(s, 1, 2018)
        add_building(
            s,
            2,
            "train",
            property_name="Seen Tower",
            address="1 Seen Ave",
            neighborhood="DOWNTOWN",
            building_type="NonResidential",
            primary_property_type="Office",
        )
        add_year(s, 2, 2016)
        add_year(s, 2, 2018)
        add_building(
            s,
            3,
            "test",
            property_name="Test Hall",
            address="3 Test Way",
            neighborhood="BALLARD",
            building_type="NonResidential",
            primary_property_type="Office",
        )
        add_year(s, 3, 2018)
        add_building(
            s,
            4,
            property_name="Pike Place 100% Market_Hall",
            address="85 Pike St",
            neighborhood="DOWNTOWN",
            building_type="Campus",
            primary_property_type="Retail",
        )
        add_year(s, 4, 2019)
        add_building(s, 5, property_name="Sans Annee", neighborhood="BALLARD")
        s.commit()


def ids(response) -> list[int]:
    return [item["building_id"] for item in response.json()["items"]]


def test_requires_token(client, catalogue):
    assert client.get("/buildings").status_code == 401
    assert client.get("/buildings/1").status_code == 401


def test_list_returns_only_unseen_buildings_with_years(client, auth_headers, catalogue):
    r = client.get("/buildings", headers=auth_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert ids(r) == [1, 4]
    assert body["total"] == 2
    assert (body["limit"], body["offset"]) == (20, 0)
    assert body["items"][0]["years"] == [2017, 2018]
    assert body["items"][0]["property_name"] == "Space Needle"


@pytest.mark.parametrize(
    ("params", "expected"),
    [
        ({"q": "needle"}, [1]),
        ({"q": "PIKE st"}, [4]),
        ({"q": "100%"}, [4]),
        ({"q": "%%"}, []),
        ({"q": "__"}, []),
        ({"year": 2019}, [4]),
        ({"year": 2016}, []),
        ({"neighborhood": "downtown"}, [4]),
        ({"building_type": "campus"}, [4]),
        ({"q": "tower"}, []),
        ({"q": "annee"}, []),
    ],
)
def test_filters(client, auth_headers, catalogue, params, expected):
    r = client.get("/buildings", params=params, headers=auth_headers)
    assert r.status_code == 200, r.text
    assert ids(r) == expected
    assert r.json()["total"] == len(expected)


def test_pagination(client, auth_headers, catalogue):
    first = client.get("/buildings", params={"limit": 1}, headers=auth_headers).json()
    second = client.get(
        "/buildings", params={"limit": 1, "offset": 1}, headers=auth_headers
    ).json()
    beyond = client.get(
        "/buildings", params={"limit": 1, "offset": 5}, headers=auth_headers
    ).json()
    assert [i["building_id"] for i in first["items"]] == [1]
    assert [i["building_id"] for i in second["items"]] == [4]
    assert beyond["items"] == []
    assert first["total"] == second["total"] == beyond["total"] == 2


@pytest.mark.parametrize(
    "params",
    [
        {},
        {"q": "seen"},
        {"q": "test hall"},
        {"year": 2018},
        {"year": 2016},
        {"limit": 100},
        {"limit": 1, "offset": 1},
    ],
)
def test_seen_buildings_are_never_listed(client, auth_headers, catalogue, params):
    r = client.get("/buildings", params=params, headers=auth_headers)
    assert r.status_code == 200, r.text
    assert not {2, 3} & set(ids(r))


def test_detail_returns_features_without_actuals(client, auth_headers, catalogue):
    r = client.get("/buildings/1", headers=auth_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["property_name"] == "Space Needle"
    assert [y["data_year"] for y in body["years"]] == [2017, 2018]
    assert body["years"][0]["property_gfa_buildings"] == 15000
    text = r.text.lower()
    assert "energy_use" not in text
    assert "ghg" not in text
    assert "actual" not in text


@pytest.mark.parametrize("building_id", [2, 3, 5, 999])
def test_detail_of_unavailable_building_is_404(
    client, auth_headers, catalogue, building_id
):
    assert (
        client.get(f"/buildings/{building_id}", headers=auth_headers).status_code == 404
    )


@pytest.mark.parametrize(
    "params",
    [
        {"limit": 0},
        {"limit": 101},
        {"offset": -1},
        {"q": "a"},
        {"year": 1999},
        {"year": 2101},
    ],
)
def test_invalid_parameters_422(client, auth_headers, catalogue, params):
    r = client.get("/buildings", params=params, headers=auth_headers)
    assert r.status_code == 422, r.text


def test_detail_rejects_out_of_range_id(client, auth_headers, catalogue):
    r = client.get("/buildings/99999999999", headers=auth_headers)
    assert r.status_code == 422
```

- [ ] **Step 3 : Vérifier l'échec**

Run: `REQUIRE_TEST_DB=1 uv run pytest tests/test_buildings_api.py -q`
Expected: FAIL (404 partout : route absente).

- [ ] **Step 4 : Créer `app/core/building_service.py`**

```python
"""Consultation des bâtiments jamais vus par l'entraînement (ni train ni test)."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from sqlalchemy import exists, func, or_, select
from sqlalchemy.orm import Session

from app.db.models import Building, BuildingYear

MAX_PAGE_SIZE = 100


@dataclass(frozen=True)
class BuildingFilters:
    q: str | None = None
    year: int | None = None
    neighborhood: str | None = None
    building_type: str | None = None


def unseen_conditions() -> list:
    """Seule définition de « consultable » : jamais vu, avec au moins une année."""
    return [
        Building.split.is_(None),
        exists().where(BuildingYear.building_id == Building.id),
    ]


def _escape_like(term: str) -> str:
    return term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _conditions(filters: BuildingFilters) -> list:
    conditions = unseen_conditions()
    if filters.q:
        pattern = f"%{_escape_like(filters.q.strip())}%"
        conditions.append(
            or_(
                Building.property_name.ilike(pattern, escape="\\"),
                Building.address.ilike(pattern, escape="\\"),
            )
        )
    if filters.year is not None:
        conditions.append(
            exists().where(
                BuildingYear.building_id == Building.id,
                BuildingYear.data_year == filters.year,
            )
        )
    if filters.neighborhood:
        conditions.append(
            func.upper(Building.neighborhood) == filters.neighborhood.strip().upper()
        )
    if filters.building_type:
        conditions.append(
            func.lower(Building.building_type) == filters.building_type.strip().lower()
        )
    return conditions


def _years_by_building(session: Session, ids: list[int]) -> dict[int, list[int]]:
    rows = session.execute(
        select(BuildingYear.building_id, BuildingYear.data_year)
        .where(BuildingYear.building_id.in_(ids))
        .order_by(BuildingYear.data_year)
    ).all()
    years: dict[int, list[int]] = defaultdict(list)
    for building_id, year in rows:
        years[building_id].append(year)
    return years


def search_buildings(
    session: Session, filters: BuildingFilters, *, limit: int, offset: int
) -> tuple[list[tuple[Building, list[int]]], int]:
    """Page de bâtiments consultables avec leurs années, et le total filtré."""
    conditions = _conditions(filters)
    total = session.scalar(
        select(func.count()).select_from(Building).where(*conditions)
    )
    buildings = session.scalars(
        select(Building)
        .where(*conditions)
        .order_by(Building.id)
        .limit(limit)
        .offset(offset)
    ).all()
    years = _years_by_building(session, [b.id for b in buildings])
    return [(b, years[b.id]) for b in buildings], total


def get_building(
    session: Session, building_id: int
) -> tuple[Building, list[BuildingYear]] | None:
    """Bâtiment consultable et ses lignes d'année ; None s'il est vu ou inconnu."""
    building = session.scalar(
        select(Building).where(Building.id == building_id, *unseen_conditions())
    )
    if building is None:
        return None
    years = session.scalars(
        select(BuildingYear)
        .where(BuildingYear.building_id == building_id)
        .order_by(BuildingYear.data_year)
    ).all()
    return building, list(years)
```

- [ ] **Step 5 : Créer `app/schemas/buildings.py`**

```python
"""Réponses de la consultation des bâtiments : aucune valeur réelle exposée."""

from pydantic import BaseModel, ConfigDict


class BuildingIdentity(BaseModel):
    building_id: int
    property_name: str | None
    address: str | None
    zip_code: str | None
    neighborhood: str | None
    building_type: str | None
    primary_property_type: str | None


class BuildingSummary(BuildingIdentity):
    years: list[int]


class BuildingYearFeatures(BaseModel):
    """Les 17 features du modèle pour une année (noms des colonnes SQL)."""

    model_config = ConfigDict(from_attributes=True)

    data_year: int
    building_type: str
    primary_property_type: str
    neighborhood: str
    latitude: float
    longitude: float
    year_built: int
    number_of_buildings: float | None
    number_of_floors: int
    property_gfa_parking: int
    property_gfa_buildings: int
    largest_property_use_type: str
    second_largest_property_use_type: str
    second_largest_property_use_type_gfa: float | None
    third_largest_property_use_type: str
    third_largest_property_use_type_gfa: float | None
    has_natural_gas: bool
    has_steam: bool


class BuildingDetail(BuildingIdentity):
    years: list[BuildingYearFeatures]


class BuildingPage(BaseModel):
    items: list[BuildingSummary]
    total: int
    limit: int
    offset: int
```

- [ ] **Step 6 : Créer `app/routers/buildings.py`**

```python
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Path, Query

from ..core import building_service as bs
from ..core.security import get_current_user
from ..db.models import Building
from ..db.session import SessionDep
from ..schemas.api import INTEGER_MAX
from ..schemas.buildings import (
    BuildingDetail,
    BuildingPage,
    BuildingSummary,
    BuildingYearFeatures,
)

router = APIRouter(
    prefix="/buildings",
    tags=["buildings"],
    dependencies=[Depends(get_current_user)],
)


def _identity(building: Building) -> dict[str, Any]:
    return {
        "building_id": building.id,
        "property_name": building.property_name,
        "address": building.address,
        "zip_code": building.zip_code,
        "neighborhood": building.neighborhood,
        "building_type": building.building_type,
        "primary_property_type": building.primary_property_type,
    }


@router.get("", response_model=BuildingPage)
def read_buildings(
    session: SessionDep,
    q: Annotated[
        str | None,
        Query(min_length=2, max_length=100, description="Nom ou adresse"),
    ] = None,
    year: Annotated[int | None, Query(ge=2015, le=2100)] = None,
    neighborhood: Annotated[str | None, Query(max_length=64)] = None,
    building_type: Annotated[str | None, Query(max_length=64)] = None,
    limit: Annotated[int, Query(ge=1, le=bs.MAX_PAGE_SIZE)] = 20,
    offset: Annotated[int, Query(ge=0, le=100_000)] = 0,
) -> BuildingPage:
    """Bâtiments jamais vus par l'entraînement, seuls prédictibles par identifiant."""
    filters = bs.BuildingFilters(
        q=q, year=year, neighborhood=neighborhood, building_type=building_type
    )
    found, total = bs.search_buildings(session, filters, limit=limit, offset=offset)
    return BuildingPage(
        items=[
            BuildingSummary(**_identity(building), years=years)
            for building, years in found
        ],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/{building_id}",
    response_model=BuildingDetail,
    responses={404: {"description": "Bâtiment inconnu ou déjà vu par l'entraînement"}},
)
def read_building(
    building_id: Annotated[int, Path(ge=0, le=INTEGER_MAX)], session: SessionDep
) -> BuildingDetail:
    found = bs.get_building(session, building_id)
    if found is None:
        raise HTTPException(404, f"Bâtiment {building_id} introuvable")
    building, years = found
    return BuildingDetail(
        **_identity(building),
        years=[BuildingYearFeatures.model_validate(year) for year in years],
    )
```

- [ ] **Step 7 : Enregistrer le router dans `app/main.py`** — remplacer `from .routers import auth, model` par `from .routers import auth, buildings, model` et ajouter `app.include_router(buildings.router)` avant `app.include_router(model.router)`.

- [ ] **Step 8 : Vérifier**

Run: `uv run ruff format app tests && uv run ruff check app tests && REQUIRE_TEST_DB=1 uv run pytest tests/test_buildings_api.py tests/test_predict_api.py -q`
Expected: PASS. Si `test_filters[%%]` ou `test_filters[__]` renvoie des bâtiments, l'échappement `LIKE` est cassé (vérifier `escape="\\"`).

- [ ] **Step 9 : Commit**

```bash
git add app tests
git commit -m "feat(api): routes /buildings de consultation des bâtiments jamais vus (#45)"
```

---

### Task 3 : Rôle API restreint et documentation

**Files :**
- Modify: `tests/test_api_role_e2e.py`
- Modify: `README.md`
- Modify: `docs/db/README.md`

- [ ] **Step 1 : Étendre le test sous le rôle API**

Dans la fixture `api_client`, ajouter dans le bloc `with factory() as s:` (avant `s.commit()`) :

```python
            add_year(s, 3, 2018, split="train")  # vu par l'entraînement
```

Dans la liste de `test_prediction_routes_under_api_role`, ajouter :

```python
(("/model/predict", {"building_id": 3}, 403),)
(("/model/predict/compare", {"building_id": 3}, 403),)
```

Remplacer la paramétrisation de `test_read_routes_under_api_role` par :

```python
@pytest.mark.parametrize(
    "route", ["/model/list", "/model/metrics", "/buildings", "/buildings/1"]
)
```

et ajouter :

```python
def test_seen_building_hidden_under_api_role(api_client):
    assert api_client.get("/buildings/3").status_code == 404
    listed = api_client.get("/buildings").json()["items"]
    assert [item["building_id"] for item in listed] == [1]
```

- [ ] **Step 2 : Vérifier**

Run: `REQUIRE_TEST_DB=1 uv run pytest tests/test_api_role_e2e.py -q`
Expected: PASS (les droits `SELECT` sur `buildings` et `building_years` suffisent).

- [ ] **Step 3 : README.md** — dans la section décrivant `POST /token` et `/model/predict` (`grep -n "model/predict" README.md`), ajouter avant l'exemple de `/model/predict` :

````markdown
**Retrouver un bâtiment avant de prédire.** `GET /buildings` cherche parmi les bâtiments **jamais vus par l'entraînement** (ni `train` ni `test`) : seuls ceux-là sont consultables et prédictibles par `building_id` (`/model/predict` et `/model/predict/compare` répondent 403 pour un bâtiment vu). Filtres : `q` (nom ou adresse), `year`, `neighborhood`, `building_type`, `limit` (100 au plus), `offset`. Aucune valeur réelle (consommation, émissions) n'est exposée.

```bash
curl "http://localhost:8080/buildings?q=needle&year=2018" -H "Authorization: Bearer <TOKEN>"
curl http://localhost:8080/buildings/1 -H "Authorization: Bearer <TOKEN>"   # identité et features par année
```
````

- [ ] **Step 4 : docs/db/README.md** — dans §2 « Choix techniques », après D11, ajouter :

```markdown
**D12 — Consultation.** `GET /buildings` et `GET /buildings/{id}` ne renvoient que les bâtiments `buildings.split IS NULL` ayant au moins une ligne `building_years` (définition unique : `building_service.unseen_conditions`). Un bâtiment vu répond 404 en consultation et 403 sur `/model/predict` et `/model/predict/compare`. Les lignes 2016 des bâtiments exclus de l'entraînement sont consultables (le modèle ne les a jamais vues). La saisie libre (`/model/predict/features`) n'est pas concernée.
```

- [ ] **Step 5 : Vérifier et commiter**

Run: `uv run ruff check . && uv run ruff format --check . && REQUIRE_TEST_DB=1 uv run pytest -q`
Expected: tout PASS.

```bash
git add README.md docs/db/README.md tests/test_api_role_e2e.py
git commit -m "docs(api): consultation des bâtiments jamais vus, tests sous le rôle API (#45)"
```

---

### Task 4 : Recette et PR

- [ ] **Step 1 : Recette sur la base de développement** (déjà migrée et ingérée lors de la PR 1)

```bash
uv run fastapi run app/main.py --port 8000 &
TOKEN=$(curl -s -X POST localhost:8000/token -d "username=johndoe&password=secret" | python3 -c "import sys,json;print(json.load(sys.stdin)['access_token'])")
curl -s "localhost:8000/buildings?limit=2" -H "Authorization: Bearer $TOKEN"
```

Expected : `total` égal au nombre de bâtiments jamais vus ayant une année (vérifier avec `SELECT count(*) FROM buildings b WHERE b.split IS NULL AND EXISTS (SELECT 1 FROM building_years y WHERE y.building_id = b.id)`). Prendre un `building_id` de la liste : `POST /model/predict` répond 200. Prendre un bâtiment vu (`SELECT id FROM buildings WHERE split = 'train' LIMIT 1`) : `GET /buildings/<id>` répond 404 et `POST /model/predict` répond 403. Arrêter le serveur (`pkill -f "fastapi run app/main.py"`).

- [ ] **Step 2 : Pousser, ouvrir la PR, attendre la CI**

```bash
git push -u origin feat/buildings-routes-45
gh pr create --title "feat(api): consultation des bâtiments jamais vus (/buildings)" --body "Closes #45. Chantier 2 de docs/superpowers/specs/2026-10-15-schema-simplifie-routes-batiments-design.md. GET /buildings (recherche paginée) et GET /buildings/{id}, bâtiments vus invisibles (404) ; /model/predict et /model/predict/compare refusent un bâtiment vu (403)."
gh pr checks <PR> --watch
```

Si des fils de revue CodeQL restent ouverts et sont des faux positifs, les résoudre avant de merger (règle de `main`).
