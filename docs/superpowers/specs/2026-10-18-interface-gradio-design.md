# Design — Interface Gradio de démonstration (issue #66)

- **Date** : 2026-10-18
- **Branche** : `feat/66-interface-gradio`
- **Statut** : validé en brainstorming, en attente de relecture

## 1. Contexte et objectifs

L'API se consomme aujourd'hui avec `curl` ou Swagger (`/docs`). Pour une démonstration (soutenance, évaluateur), il faut une interface graphique **claire, simple et épurée** couvrant le parcours : se connecter, trouver un bâtiment jamais vu par l'entraînement, voir sa fiche, obtenir sa prédiction (et, en option, la comparaison avec Kumo-Tabular).

Hors périmètre : saisie libre des 17 features (`/model/predict/features`), historique des prédictions, scores du modèle (`/model/metrics`), gestion des comptes.

## 2. Décisions

| # | Sujet | Décision |
|---|---|---|
| D1 | Périmètre | Parcours de démonstration : connexion → recherche → fiche → prédiction (+ comparaison Kumo optionnelle) |
| D2 | Intégration | Service séparé, **client HTTP de l'API** : aucun accès à la base ni au modèle |
| D3 | Authentification | L'utilisateur se connecte avec ses identifiants de l'API ; jeton JWT gardé en `gr.State` (par onglet), jamais écrit ni journalisé |
| D4 | Image | Même image que l'API (`P5_IMAGE`), commande `python -m app.ui` ; aucun changement de la release |
| D5 | Démarrage | Service toujours démarré, `127.0.0.1:${UI_PORT:-7860}`, URL affichée en premier par le Quickstart |
| D6 | Thème | Clair forcé, `gr.themes.Base`, gris neutres + un accent bleu, police Inter, sans ombres ; pied de page Gradio masqué |

## 3. Architecture

```
navigateur ──► ui (Gradio, :7860) ──HTTP + JWT──► api (:8080) ──► db
                                                   │ middleware de traçabilité
                                                   ▼
                                        api_requests (user_id) ──► Grafana
```

### 3.1 Service `ui` (`docker-compose.yml`)

- `image: ${P5_IMAGE:-ghcr.io/…:latest}` (dans un clone, `docker-compose.override.yml` la remplace par le build local, comme `api`).
- `command: ["python", "-m", "app.ui"]`.
- Environnement : `P5_API_URL=http://api:8080` uniquement (ni `SECRET_KEY`, ni `DATABASE_*`).
- Port `127.0.0.1:${UI_PORT:-7860}:7860` ; `depends_on: api` (`service_healthy`) ; healthcheck HTTP sur `/` (python `urllib`, comme le `Dockerfile`).

### 3.2 Code (`app/ui/`)

| Fichier | Rôle |
|---|---|
| `client.py` | `ApiClient(http: httpx.Client)` : `login`, `search_buildings`, `get_building`, `predict`, `compare` ; erreurs HTTP converties en `ApiError(status, message)` en français (le `detail` de l'API est repris) ; `401` → `SessionExpired` |
| `format.py` | Format français des nombres (`3 088 220`, `99,2`) et de la fiche bâtiment |
| `app.py` | `build_app(client_factory) -> gr.Blocks` : composants et câblage ; gestionnaires d'événements = fonctions de module testables, sans appel réseau direct |
| `__main__.py` | `build_app(...).launch(server_name="0.0.0.0", server_port=7860)` |

`client_factory` construit un `ApiClient` sur `httpx.Client(base_url=P5_API_URL, timeout=60)` ; en test, un `ApiClient` sur le `TestClient` FastAPI (sous-classe de `httpx.Client`).

Dépendance : `gradio==6.29.1` dans les dépendances principales (`uv.lock` modifié → l'image de base est reconstruite, déjà géré par `base-image.yml`). `httpx` est déjà présent (via FastAPI).

## 4. Parcours et écrans

### 4.1 Connexion

Titre « ⚡ Consommation énergétique — Seattle », sous-titre « Prédiction pour les bâtiments non résidentiels » ; champs identifiant / mot de passe ; bouton « Se connecter » ; aide « Démo : johndoe / secret (si les comptes de démonstration sont activés) ». Échec → message sous le formulaire (« Identifiants incorrects ou compte inactif » ; API injoignable → « API indisponible »).

### 4.2 Recherche et prédiction (deux colonnes)

En-tête : « Connecté : <identifiant> » et « Se déconnecter » (efface le jeton, retour à la connexion).

**Colonne gauche — Trouver un bâtiment**
- Champ texte (nom ou adresse, `q`, 2 caractères minimum, sinon ignoré) ; liste « Quartier » : « Tous » + les 13 districts (`BALLARD`, `CENTRAL`, `DELRIDGE`, `DOWNTOWN`, `EAST`, `GREATER DUWAMISH`, `LAKE UNION`, `MAGNOLIA / QUEEN ANNE`, `NORTH`, `NORTHEAST`, `NORTHWEST`, `SOUTHEAST`, `SOUTHWEST`).
- Tableau (ID, nom, quartier) de 20 lignes ; « ◀ Précédent » / « Suivant ▶ » et « 1–20 / 238 ». Chargé dès la connexion.

**Colonne droite — Bâtiment**
- Clic sur une ligne → `/buildings/{id}` : nom, adresse, quartier, type, année de construction, surface (`property_gfa_buildings`, pi²).
- Liste « Année » (années disponibles, la plus récente sélectionnée) ; case « Comparer avec Kumo-Tabular » (note : « le premier appel peut prendre ~15 s ») ; bouton « Prédire » (texte « Calcul… » et désactivé pendant l'appel).
- Résultat : énergie (kBtu/an) et émissions (t CO2e/an) CatBoost, ligne « CatBoost · prédiction n° <id> » ; si comparaison, mêmes valeurs Kumo en dessous.
- Erreurs : bandeau au-dessus du résultat avec le message de l'API (404, 403, 422, 503). `SessionExpired` → retour à la connexion, message « Session expirée, reconnectez-vous ».

## 5. Tests

### 5.1 Pytest (couverture ≥ 98 %)

- `tests/test_ui_client.py` (marqueur `db`) : `ApiClient` sur le `TestClient` de l'application, avec la base de test et les modèles de démo. Connexion OK / mauvais mot de passe / compte inactif ; recherche paginée et filtrée ; fiche ; prédiction ; comparaison ; bâtiment inconnu (`ApiError` 404, message de l'API) ; jeton invalide → `SessionExpired` ; **traçabilité** : une prédiction via le client crée une ligne `api_requests` dont `user_id` est celui de `johndoe`.
- `tests/test_ui_app.py` : gestionnaires (connexion, recherche, pagination, sélection, prédiction, déconnexion) appelés directement ; on vérifie valeurs, visibilité et messages. API injoignable (`httpx.ConnectError`) → « API indisponible ».
- `tests/test_ui_format.py` : nombres et fiche au format français.
- `build_app()` construit un `gr.Blocks` (thème clair forcé) sans erreur.

### 5.2 Installation

`scripts/quickstart.sh` : `docker compose up -d --wait api grafana ui` ; vérification `GET http://localhost:${UI_PORT:-7860}/` → 200 et contient le titre ; message final avec l'URL de l'interface en premier. `ci-install` l'exécute (chemins `app/**` déjà surveillés).

### 5.3 Recette manuelle

Installation vierge ; parcours complet dans un navigateur (Playwright) : connexion, recherche, fiche, prédiction, comparaison, bâtiment inexistant, déconnexion ; captures en thème clair (`docs/ui/img/`) ; vérification dans Grafana que les appels sont attribués à `johndoe`.

## 6. Documentation

- `docs/ui/README.md` : accès, parcours, captures, architecture (client de l'API), lancement hors Docker (`P5_API_URL=… uv run python -m app.ui`).
- `README.md` : Quickstart (interface en premier), ports (`7860`), variables `UI_PORT`, `P5_API_URL`, stack (Gradio), documentation.

## 7. Risques

| Risque | Parade |
|---|---|
| Image plus lourde (~100 Mo) | Accepté (D4) ; torch domine déjà la taille |
| Gradio change d'API entre versions | Version exacte épinglée ; `build_app()` testé |
| Mode sombre du navigateur | Thème clair forcé (JS `?__theme=light` au chargement) ; vérifié en recette |
| Premier appel Kumo lent (~15 s) | Bouton en « Calcul… », note sous la case, timeout client 60 s |
| Port 7860 pris | `UI_PORT` surchargeable |
