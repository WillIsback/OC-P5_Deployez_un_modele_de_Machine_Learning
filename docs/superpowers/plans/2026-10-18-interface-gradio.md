# Interface Gradio — plan d'implémentation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal :** une interface Gradio claire et épurée (service `ui`) qui permet de se connecter, trouver un bâtiment jamais vu, voir sa fiche et obtenir sa prédiction, en client HTTP de l'API.

**Architecture :** `app/ui/` : un client HTTP (`client.py`) seul à parler à l'API, un module de mise en forme (`format.py`), des gestionnaires d'événements testables et la construction de l'interface (`app.py`), un point d'entrée (`__main__.py`). Même image Docker que l'API, service Compose `ui` lancé avec `python -m app.ui`.

**Tech Stack :** Gradio 6.29.1, httpx, FastAPI `TestClient` (tests), pytest, Docker Compose, Playwright (recette).

**Spec :** `docs/superpowers/specs/2026-10-18-interface-gradio-design.md`

## Global Constraints

- `gradio==6.29.1` exact, dans les dépendances principales de `pyproject.toml` ; `uv lock` régénéré.
- **Gradio 6** : `theme`, `css`, `js` et `footer_links` sont des paramètres de `Blocks.launch()`, pas de `gr.Blocks()`.
- Le code de `app/ui/` n'importe ni `app.db`, ni `app.core`, ni CatBoost/torch : il ne parle qu'à l'API, via `ApiClient`.
- Le jeton JWT n'est jamais journalisé ni écrit sur disque ; il vit dans un `gr.State`.
- `P5_API_URL` (défaut `http://localhost:8080`) ; port `7860` ; `UI_PORT` côté hôte (défaut `7860`), lié à `127.0.0.1`.
- Taille de page : 20 ; timeout HTTP du client : 60 s.
- Format des nombres : séparateur de milliers **U+00A0** (espace insécable), virgule décimale (`3 088 220`, `99,2`).
- Textes de l'interface, docs et messages en français ; commits Conventional Commits terminés par `Refs #66` (dernier commit : `Closes #66`).
- Couverture : seuil global 98 % et diff-cover 90 % (CI bloquante).

## Review Focus

1. **API injoignable** (conteneur `api` redémarré, mauvais `P5_API_URL`) : chaque action affiche « API indisponible » au lieu d'une trace Python. → `test_login_api_unreachable` et `test_search_api_unreachable` (Task 3).
2. **Recherche d'un seul caractère** : l'API exige `q` ≥ 2 caractères (422) ; l'interface ignore un `q` trop court au lieu d'afficher une erreur. → `test_search_ignores_short_query` (Task 3).
3. **Aucun résultat** : tableau vide, « Aucun bâtiment trouvé », boutons de pagination désactivés. → `test_search_no_result` (Task 3).
4. **Valeurs manquantes dans la fiche** (surface d'un 2ᵉ usage nulle, `zip_code` absent) : « — » au lieu de « None ». → `test_building_card_missing_values` (Task 1).
5. **Jeton expiré en cours de session** (expiration de 30 min de l'API) : retour à l'écran de connexion avec « Session expirée, reconnectez-vous », sur n'importe quelle action. → `test_expired_session_returns_to_login` (Task 3), paramétré sur recherche, sélection et prédiction.

---

### Task 1 : dépendance Gradio et mise en forme

**Files :**
- Modify : `pyproject.toml` (`gradio==6.29.1`), `uv.lock`
- Create : `app/ui/__init__.py` (vide), `app/ui/format.py`
- Test : `tests/test_ui_format.py`

**Interfaces :**
- Produces :
  - `fr_number(value: float | None, decimals: int = 0) -> str` (`None` → `"—"`)
  - `building_card(detail: dict) -> str` : Markdown de la fiche à partir de la réponse de `/buildings/{id}` (identité + **dernière** année de `years`)
  - `prediction_card(result: dict, label: str) -> str` : Markdown d'une prédiction (`energy_use_kbtu`, `ghg_emissions_tco2e`, `prediction_id`)

- [ ] **Step 1 : tests qui échouent** (`tests/test_ui_format.py`)

```python
NBSP = " "

@pytest.mark.parametrize("value,decimals,expected", [
    (3088219.81, 0, f"3{NBSP}088{NBSP}220"),
    (99.238, 1, "99,2"),
    (1234.5, 1, f"1{NBSP}234,5"),
    (0, 0, "0"),
    (None, 0, "—"),
])
def test_fr_number(value, decimals, expected): ...

def test_building_card():
    # detail : identité de GRAHAM HILL (id 28), years = [2016 (year_built 1961), 2019 (year_built 1961, property_gfa_buildings 56228)]
    # la carte contient "GRAHAM HILL ELEMENTARY SCHOOL (SPS-DISTRICT)", "5101 S GRAHAM ST",
    # "SOUTHEAST", "K-12 School", "1961", f"56{NBSP}228 pi²", et les données 2019 (dernière année)

def test_building_card_missing_values():
    # address None, zip_code None, years[-1]["property_gfa_buildings"] absent/None → "—", jamais "None"

def test_prediction_card():
    # {"energy_use_kbtu": 3088219.81, "ghg_emissions_tco2e": 99.238, "prediction_id": 42}, "CatBoost"
    # → contient f"3{NBSP}088{NBSP}220 kBtu/an", "99,2 t CO2e/an", "CatBoost · prédiction n° 42"
```

- [ ] **Step 2 : vérifier l'échec** — `uv run pytest tests/test_ui_format.py -v` → `ModuleNotFoundError: app.ui`.

- [ ] **Step 3 : implémenter** `app/ui/format.py` ; ajouter `"gradio==6.29.1"` à `[project].dependencies`, puis `uv lock` et `uv sync`.

- [ ] **Step 4 : vérifier** — `uv run pytest tests/test_ui_format.py -v` → PASS ; `uv run python -c "import gradio; print(gradio.__version__)"` → `6.29.1`.

- [ ] **Step 5 : commit** — `feat(ui): dépendance Gradio et mise en forme française`

---

### Task 2 : client HTTP de l'API

**Files :**
- Create : `app/ui/client.py`
- Test : `tests/test_ui_client.py` (`pytestmark = pytest.mark.db`)

**Interfaces :**
- Produces :
  - `class ApiError(Exception)` : attributs `status: int | None`, `message: str` (`str(err) == message`)
  - `class SessionExpired(ApiError)` : `status=401`, `message="Session expirée, reconnectez-vous"`
  - `class ApiClient(http: httpx.Client)` :
    - `login(username: str, password: str) -> str` (jeton) ; 400 → `ApiError(400, "Identifiants incorrects ou compte inactif")`
    - `search_buildings(token: str, *, q: str | None = None, neighborhood: str | None = None, limit: int = 20, offset: int = 0) -> dict` (réponse `BuildingPage`) ; paramètres `None` non envoyés
    - `get_building(token: str, building_id: int) -> dict`
    - `predict(token: str, building_id: int, data_year: int | None = None) -> dict`
    - `compare(token: str, building_id: int, data_year: int | None = None) -> dict`
  - Erreurs : `httpx.TransportError` → `ApiError(None, "API indisponible")` ; 401 hors login → `SessionExpired` ; autres codes ≥ 400 → `ApiError(status, detail)` où `detail` est le `detail` texte de l'API, ou `"Requête invalide"` si `detail` est une liste (422 de validation).
  - `default_client() -> ApiClient` : `httpx.Client(base_url=os.getenv("P5_API_URL", "http://localhost:8080"), timeout=60)`.

- [ ] **Step 1 : tests qui échouent** — fixture `ui_client(client, demo_models, buildings_fixture)` : `ApiClient(client)` où `client` est le `TestClient` de `tests/conftest.py` ; bâtiments créés avec `tests/synth.py` (`add_year(s, 1, 2018)`, comme `tests/test_predict_api.py::buildings`).

```python
def test_login_returns_token(ui_client): ...  # jeton non vide
def test_login_wrong_password(ui_client): ...  # ApiError 400, message exact
def test_login_inactive_user(ui_client): ...  # "alice" → ApiError 400
def test_search_and_paginate(
    ui_client,
): ...  # total, limit=1/offset=0 → 1 item ; neighborhood filtré
def test_get_building(ui_client): ...  # building_id, years non vide
def test_predict(ui_client): ...  # energy_use_kbtu > 0, prediction_id
def test_compare(ui_client): ...  # catboost_prediction et kumo_prediction
def test_unknown_building(ui_client): ...  # ApiError 404, message de l'API ("inconnu")
def test_invalid_token_is_session_expired(
    ui_client,
): ...  # search avec "faux" → SessionExpired
def test_validation_error_message(
    ui_client,
): ...  # search q="x" (1 car.) → ApiError 422 "Requête invalide"
def test_transport_error(): ...  # ApiClient(httpx.Client(base_url="http://127.0.0.1:1")) → ApiError(None, "API indisponible")
def test_prediction_traced_with_user(
    ui_client, db
): ...  # ligne api_requests path /model/predict, user_id == id de johndoe
def test_default_client_reads_env(
    monkeypatch,
): ...  # P5_API_URL=http://api:8080 → base_url
```

- [ ] **Step 2 : vérifier l'échec** — `uv run pytest tests/test_ui_client.py -v` → `ImportError`.
- [ ] **Step 3 : implémenter `app/ui/client.py`** (en-tête `Authorization: Bearer <jeton>` ; `/token` en formulaire `username`/`password`).
- [ ] **Step 4 : vérifier** — `uv run pytest tests/test_ui_client.py -v` → PASS.
- [ ] **Step 5 : commit** — `feat(ui): client HTTP de l'API (erreurs en français, session expirée)`

---

### Task 3 : interface Gradio (gestionnaires et construction)

**Files :**
- Create : `app/ui/app.py`, `app/ui/__main__.py`
- Test : `tests/test_ui_app.py`

**Interfaces :**
- Consumes : `ApiClient`, `ApiError`, `SessionExpired` (Task 2) ; `fr_number`, `building_card`, `prediction_card` (Task 1).
- Produces (`app/ui/app.py`) :
  - `NEIGHBORHOODS: tuple[str, ...]` : les 13 districts de la spec §4.2.
  - `PAGE_SIZE = 20`.
  - `LAUNCH_OPTIONS: dict` : `theme` (`gr.themes.Base`, accent bleu, police Inter), `css`, `js` (force `?__theme=light`), `footer_links=[]`.
  - État de session (`gr.State`, dict) : `{"token": str | None, "username": str | None, "offset": int, "building": dict | None}` ; `new_state() -> dict`.
  - Gestionnaires (fonctions de module, `client` en premier argument). **Chacun renvoie d'abord `(state, login_panel, main_panel, login_message)`**, puis ses sorties propres ; sur `SessionExpired`, un décorateur `@session_guard(n_outputs)` renvoie l'état vidé, l'écran de connexion visible, le message « Session expirée, reconnectez-vous » et `gr.update()` pour les autres sorties.
    - `on_login(client, state, username, password)` → `+ (user_md, table, page_md, prev_btn, next_btn)`
    - `on_search(client, state, query, neighborhood, offset)` → `+ (table, page_md, prev_btn, next_btn, error_md)`
    - `on_page(client, state, query, neighborhood, step: int)` : `offset + step * PAGE_SIZE` borné à `[0, total)` puis `on_search`
    - `on_select(client, state, evt: gr.SelectData)` → `+ (card_md, year_dd, predict_btn, result_md, error_md)` (id = `evt.row_value[0]`)
    - `on_predict(client, state, year, with_kumo: bool)` → `+ (result_md, error_md)`
    - `on_logout(state)` → `(new_state(), login visible, main caché, "")`
  - `build_app(client_factory: Callable[[], ApiClient] = default_client) -> gr.Blocks`.
- `app/ui/__main__.py` : `build_app().launch(server_name="0.0.0.0", server_port=7860, **LAUNCH_OPTIONS)`.

- [ ] **Step 1 : tests qui échouent** (`tests/test_ui_app.py`). `ApiClient` simulé par une classe de test minimale (`FakeClient`) qui renvoie des réponses figées ou lève `ApiError`/`SessionExpired` : les gestionnaires sont testés sans réseau (le vrai client est couvert par la Task 2).

```python
def test_login_success_shows_main(...): ...      # main visible, login caché, "Connecté : johndoe", 1re page chargée
def test_login_failure_message(...): ...          # login visible, message de l'ApiError
def test_login_api_unreachable(...): ...          # ApiError(None, "API indisponible") → message affiché
def test_search_ignores_short_query(...): ...     # query "a" → client appelé avec q=None
def test_search_no_result(...): ...               # total 0 → "Aucun bâtiment trouvé", prev/next interactive=False
def test_search_api_unreachable(...): ...         # error_md contient "API indisponible"
def test_pagination_bounds(...): ...              # step -1 à offset 0 → offset 0 ; step +1 en dernière page → inchangé
def test_select_building_fills_card(...): ...     # card_md (building_card), years dans year_dd, dernière sélectionnée
def test_predict_catboost(...): ...               # result_md = prediction_card(..., "CatBoost")
def test_predict_with_kumo(...): ...              # result_md contient "CatBoost" et "Kumo-Tabular"
def test_predict_error_banner(...): ...           # ApiError(503, "Modèle Kumo-Tabular indisponible") → error_md
@pytest.mark.parametrize("action", ["search", "select", "predict"])
def test_expired_session_returns_to_login(action, ...): ...  # login visible, message session expirée, state["token"] is None
def test_logout(...): ...
def test_build_app_and_light_theme(): ...         # build_app(lambda: FakeClient()) est un gr.Blocks ;
                                                   # "__theme=light" in LAUNCH_OPTIONS["js"] ; footer_links == []
```

- [ ] **Step 2 : vérifier l'échec** — `uv run pytest tests/test_ui_app.py -v` → `ImportError`.
- [ ] **Step 3 : implémenter `app/ui/app.py` et `__main__.py`** selon la maquette de la spec §4 (connexion centrée ; deux colonnes ; bouton « Prédire » avec `.click(...)` suivi d'un état « Calcul… » désactivé pendant l'appel, puis réactivé). Vérifier l'API `gr.SelectData` sur 6.29.1 (`evt.row_value`) avant de s'y fier.
- [ ] **Step 4 : vérifier** — `uv run pytest tests/test_ui_app.py -v` → PASS ; lancement local contre une API de dev : `P5_API_URL=http://localhost:8080 uv run python -m app.ui` puis `curl -s -o /dev/null -w '%{http_code}' localhost:7860/` → `200`.
- [ ] **Step 5 : commit** — `feat(ui): interface Gradio (connexion, recherche, fiche, prédiction)`

---

### Task 4 : service Compose et Quickstart

**Files :**
- Modify : `docker-compose.yml`, `docker-compose.override.yml`, `scripts/quickstart.sh`, `README.md` (prérequis : port `7860`)

**Interfaces :**
- Consumes : `python -m app.ui` (Task 3).

- [ ] **Step 1 : service `ui`** (spec §3.1) : `image: ${P5_IMAGE:-…:latest}`, `command: ["python", "-m", "app.ui"]`, `environment: {P5_API_URL: http://api:8080}`, `ports: ["127.0.0.1:${UI_PORT:-7860}:7860"]`, `depends_on: api: {condition: service_healthy}`, healthcheck `["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:7860/')"]`. Override de dev : `ui: {image: p5-energy:dev}` (même image que `api`, pas de second `build`). Vérifier : `docker compose --env-file .example.env config -q`.
- [ ] **Step 2 : `quickstart.sh`** : `local ui="http://localhost:${UI_PORT:-7860}"` ; `docker compose up -d --wait api grafana ui` ; vérification `curl -fsS "$ui/"` contient `Consommation énergétique` sinon `die "interface injoignable sur $ui"` ; message final : première ligne `Interface de démonstration : $ui  (johndoe / secret)` ; en-tête `-h` : `UI_PORT` dans la ligne des ports.
- [ ] **Step 3 : recette d'installation** (comme la Task 4 du plan Grafana) : `docker build -t p5-energy:ui .` puis `QUICKSTART_CLONE_FROM=$PWD P5_IMAGE=p5-energy:ui P5_PULL=0 API_PORT=18080 DB_PORT=15432 GRAFANA_PORT=13000 UI_PORT=17860 QUICKSTART_KEEP=1 scripts/quickstart_test.sh user README.md "$W"`. Expected : « ✅ Quickstart « Utilisateurs » OK » et l'URL `http://localhost:17860` en tête du message final. Garder l'installation pour la Task 5.
- [ ] **Step 4 : commit** — `feat(install): interface Gradio démarrée et vérifiée par le Quickstart`

---

### Task 5 : recette visuelle et documentation

**Files :**
- Create : `docs/ui/README.md`, `docs/ui/img/login.png`, `docs/ui/img/prediction.png`
- Modify : `README.md` (Quickstart, ports, variables `UI_PORT` / `P5_API_URL`, stack, tableau Documentation, livrables), `docs/monitoring/README.md` (mention : les appels de l'interface y apparaissent au nom de l'utilisateur)

- [ ] **Step 1 : parcours Playwright** sur l'installation de la Task 4 (`http://localhost:17860`, navigateur en mode **sombre** pour vérifier le thème clair forcé) : connexion `johndoe`, recherche « school », filtre quartier, page suivante, sélection d'un bâtiment, prédiction, comparaison Kumo, bâtiment sans résultat, déconnexion. Expected : aucune erreur console Gradio, thème clair, nombres au format français.
- [ ] **Step 2 : captures** `login.png` et `prediction.png` (avec comparaison) ; vérifier à l'œil l'alignement et l'absence de pied de page Gradio.
- [ ] **Step 3 : vérifier Grafana** : `GET /api/ds/query` ou tableau « API » → les appels `/buildings` et `/model/predict*` de la recette ont `user_id` de `johndoe` (requête SQL en `p5_grafana`, ou `docker compose exec db psql`).
- [ ] **Step 4 : docs** : `docs/ui/README.md` (accès, parcours, captures, architecture client de l'API, lancement hors Docker `P5_API_URL=… uv run python -m app.ui`) ; README et monitoring.
- [ ] **Step 5 : vérifier** — liens relatifs valides ; `uv run pytest --cov=app -q` → PASS ≥ 98 % ; `uv run ruff check . && uv run ruff format --check .` → OK.
- [ ] **Step 6 : nettoyer** l'installation de recette (`docker compose --profile tools down -v` avec les variables de ports).
- [ ] **Step 7 : commit** — `docs(ui): parcours, captures et architecture de l'interface` avec `Closes #66`.
