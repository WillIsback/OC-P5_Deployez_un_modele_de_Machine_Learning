"""Interface Gradio de démonstration : connexion, recherche, fiche, prédiction.

Les gestionnaires sont des fonctions de module (client en premier argument),
testables sans réseau. Chacun renvoie d'abord ``(state, login_panel,
main_panel, login_message)`` : une session expirée ramène ainsi à la connexion
depuis n'importe quelle action. Le jeton ne vit que dans le ``gr.State``.
"""

from __future__ import annotations

import functools
import os
from collections.abc import Callable
from typing import Any

# Avant l'import de gradio : ni statistiques d'usage ni vérification de version
# auprès de api.gradio.app (l'interface fonctionne hors ligne).
os.environ.setdefault("GRADIO_ANALYTICS_ENABLED", "False")

import gradio as gr

from .client import ApiClient, ApiError, SessionExpired, default_client
from .format import building_card, prediction_card

TITLE = "Consommation énergétique — Seattle"
PAGE_SIZE = 20
ALL = "Tous"
NEIGHBORHOODS = (
    "BALLARD",
    "CENTRAL",
    "DELRIDGE NEIGHBORHOODS",
    "DOWNTOWN",
    "EAST",
    "GREATER DUWAMISH",
    "LAKE UNION",
    "MAGNOLIA / QUEEN ANNE",
    "NORTH",
    "NORTHEAST",
    "NORTHWEST",
    "SOUTHEAST",
    "SOUTHWEST",
)
COLUMNS = ["ID", "Nom", "Quartier"]

_FONT = ["Inter", "system-ui", "sans-serif"]

# Thème clair forcé (même si le navigateur est en mode sombre) : gris neutres,
# un seul accent bleu, sans ombres.
_THEME = gr.themes.Base(
    primary_hue="blue",
    neutral_hue="slate",
    radius_size="sm",
    font=_FONT,
    font_mono=_FONT,  # tableau et code dans la même police que le texte
).set(
    block_shadow="none",
    button_primary_shadow="none",
    block_border_width="1px",
)
_FORCE_LIGHT = """
() => {
  const url = new URL(window.location.href);
  if (url.searchParams.get("__theme") !== "light") {
    url.searchParams.set("__theme", "light");
    window.location.replace(url.href);
  }
}
"""
_CSS = """
.gradio-container { max-width: 1180px !important; margin: auto; }
#login-box { max-width: 420px; margin: 8vh auto 0; }
#error-banner { color: #b42318; }
.subtitle { color: #64748b; }
"""
LAUNCH_OPTIONS: dict[str, Any] = {
    "theme": _THEME,
    "css": _CSS,
    "js": _FORCE_LIGHT,
    "footer_links": [],
    # Par défaut, Gradio enregistre les entrées de chaque événement (dont le mot
    # de passe) dans le localStorage du navigateur (/gradio_api/runs).
    "run_history": False,
}
# Événements non exposés en API Gradio (/gradio_api/call/…) : l'interface est
# le seul client prévu.
PRIVATE = {"api_visibility": "private"}
SELECT_PROMPT = "Sélectionnez un bâtiment dans la liste."


def launch_options() -> dict[str, Any]:
    """Options de ``launch()`` ; ``GRADIO_SERVER_NAME=0.0.0.0`` dans Compose."""
    return {
        **LAUNCH_OPTIONS,
        "server_name": os.getenv("GRADIO_SERVER_NAME", "127.0.0.1"),
        "server_port": 7860,
    }


def new_state() -> dict:
    return {"token": None, "username": None, "offset": 0, "total": 0, "building": None}


def _panels(logged_in: bool, message: str = "") -> tuple:
    return gr.update(visible=not logged_in), gr.update(visible=logged_in), message


def _building_reset() -> tuple:
    """Colonne droite vide : fiche, année, bouton, résultat, bandeau."""
    return (
        SELECT_PROMPT,
        gr.update(choices=[], value=None),
        gr.update(interactive=False),
        "",
        _error(None),
    )


def _error(message: str | None) -> dict:
    if message:
        return gr.update(visible=True, value=f"⚠️ {message}")
    return gr.update(visible=False, value="")


def session_guard(n_outputs: int):
    """Sur ``SessionExpired`` : retour à la connexion, autres sorties inchangées."""

    def decorator(handler):
        @functools.wraps(handler)
        def wrapper(*args, **kwargs):
            try:
                return handler(*args, **kwargs)
            except SessionExpired as err:
                return (
                    new_state(),
                    *_panels(False, err.message),
                    *[gr.update() for _ in range(n_outputs)],
                )

        return wrapper

    return decorator


def _page(client: ApiClient, state: dict, query: str, neighborhood: str, offset: int):
    """Recherche ; renvoie (state, table, page_md, prev_btn, next_btn)."""
    q = query.strip() if query and len(query.strip()) >= 2 else None
    page = client.search_buildings(
        state["token"],
        q=q,
        neighborhood=None if neighborhood in (None, "", ALL) else neighborhood,
        limit=PAGE_SIZE,
        offset=offset,
    )
    items, total = page["items"], page["total"]
    rows = [
        [b["building_id"], b.get("property_name"), b.get("neighborhood")] for b in items
    ]
    state = {**state, "offset": offset, "total": total}
    page_md = (
        f"{offset + 1}–{offset + len(items)} / {total}"
        if items
        else "Aucun bâtiment trouvé"
    )
    return (
        state,
        gr.update(value=rows),
        page_md,
        gr.update(interactive=offset > 0),
        gr.update(interactive=offset + len(items) < total),
    )


def on_login(client: ApiClient, state: dict, username: str, password: str):
    if not (username or "").strip() or not password:
        return (
            state,
            *_panels(False, "Saisissez votre identifiant et votre mot de passe."),
            *[gr.update() for _ in range(10)],
        )
    try:
        token = client.login(username, password)
    except ApiError as err:
        return (state, *_panels(False, err.message), *[gr.update() for _ in range(10)])
    state = {**new_state(), "token": token, "username": username}
    state, table, page_md, prev_btn, next_btn = _page(client, state, "", ALL, 0)
    return (
        state,
        *_panels(True),
        f"Connecté : {username}",
        table,
        page_md,
        prev_btn,
        next_btn,
        *_building_reset(),
    )


@session_guard(5)
def on_search(
    client: ApiClient, state: dict, query: str, neighborhood: str, offset: int
):
    try:
        state, *page = _page(client, state, query, neighborhood, offset)
    except SessionExpired:
        raise
    except ApiError as err:
        return (
            state,
            *_panels(True),
            *[gr.update() for _ in range(4)],
            _error(err.message),
        )
    return (state, *_panels(True), *page, _error(None))


def on_page(client: ApiClient, state: dict, query: str, neighborhood: str, step: int):
    offset = state["offset"] + step * PAGE_SIZE
    if offset < 0:
        offset = 0
    elif offset >= state.get("total", 0):
        offset = state["offset"]
    return on_search(client, state, query, neighborhood, offset)


@session_guard(5)
def on_select(client: ApiClient, state: dict, evt: gr.SelectData):
    building_id = int(evt.row_value[0])
    try:
        detail = client.get_building(state["token"], building_id)
    except SessionExpired:
        raise
    except ApiError as err:
        return (
            state,
            *_panels(True),
            *[gr.update() for _ in range(4)],
            _error(err.message),
        )
    years = [y["data_year"] for y in detail["years"]]
    return (
        {**state, "building": detail},
        *_panels(True),
        building_card(detail),
        gr.update(choices=years, value=years[-1] if years else None),
        gr.update(interactive=bool(years)),
        "",
        _error(None),
    )


@session_guard(2)
def on_predict(client: ApiClient, state: dict, year: int | None, with_kumo: bool):
    if not state.get("building"):
        return (state, *_panels(True), "", _error(SELECT_PROMPT))
    building_id = state["building"]["building_id"]
    try:
        if with_kumo:
            result = client.compare(state["token"], building_id, year)
            result_md = "\n\n".join(
                [
                    prediction_card(result["catboost_prediction"], "CatBoost"),
                    prediction_card(result["kumo_prediction"], "Kumo-Tabular"),
                ]
            )
        else:
            result_md = prediction_card(
                client.predict(state["token"], building_id, year), "CatBoost"
            )
    except SessionExpired:
        raise
    except ApiError as err:
        return (state, *_panels(True), "", _error(err.message))
    return (state, *_panels(True), result_md, _error(None))


def on_logout(state: dict):
    """Déconnexion : jeton oublié, mot de passe et bâtiment effacés."""
    return (new_state(), *_panels(False), "", *_building_reset())


def build_app(client_factory: Callable[[], ApiClient] = default_client) -> gr.Blocks:
    client = client_factory()
    bind = functools.partial

    with gr.Blocks(title=TITLE) as demo:
        state = gr.State(new_state())

        with gr.Column(elem_id="login-box") as login_panel:
            gr.Markdown(f"# ⚡ {TITLE}")
            gr.Markdown(
                "Prédiction pour les bâtiments non résidentiels",
                elem_classes="subtitle",
            )
            username = gr.Textbox(label="Identifiant")
            password = gr.Textbox(label="Mot de passe", type="password")
            login_btn = gr.Button("Se connecter", variant="primary")
            login_msg = gr.Markdown()
            gr.Markdown(
                "Démo : `johndoe` / `secret` (si les comptes de démonstration "
                "sont activés)",
                elem_classes="subtitle",
            )

        with gr.Column(visible=False) as main_panel:
            with gr.Row():
                user_md = gr.Markdown()
                logout_btn = gr.Button("Se déconnecter", size="sm", scale=0)
            with gr.Row(equal_height=False):
                with gr.Column(scale=5):
                    gr.Markdown("### Trouver un bâtiment")
                    with gr.Row():
                        query = gr.Textbox(
                            show_label=False, placeholder="Nom ou adresse…", scale=4
                        )
                        search_btn = gr.Button("Rechercher", scale=1)
                    neighborhood = gr.Dropdown(
                        [ALL, *NEIGHBORHOODS], value=ALL, label="Quartier"
                    )
                    table = gr.Dataframe(
                        headers=COLUMNS,
                        interactive=False,
                        wrap=True,
                        max_height=520,
                        buttons=[],
                    )
                    with gr.Row():
                        prev_btn = gr.Button(
                            "◀ Précédent", size="sm", interactive=False
                        )
                        page_md = gr.Markdown()
                        next_btn = gr.Button("Suivant ▶", size="sm", interactive=False)
                with gr.Column(scale=4):
                    card_md = gr.Markdown(SELECT_PROMPT)
                    year_dd = gr.Dropdown(label="Année", choices=[])
                    with_kumo = gr.Checkbox(
                        label="Comparer avec Kumo-Tabular",
                        info="Calcul plus long (40 s à 1 min sur CPU) : Kumo relit tout le jeu d'entraînement.",
                    )
                    predict_btn = gr.Button(
                        "Prédire", variant="primary", interactive=False
                    )
                    error_md = gr.Markdown(visible=False, elem_id="error-banner")
                    result_md = gr.Markdown()

        head = [state, login_panel, main_panel, login_msg]
        page_outputs = [table, page_md, prev_btn, next_btn]
        building_outputs = [card_md, year_dd, predict_btn, result_md, error_md]

        login_btn.click(
            bind(on_login, client),
            [state, username, password],
            [*head, user_md, *page_outputs, *building_outputs],
            **PRIVATE,
        )
        password.submit(
            bind(on_login, client),
            [state, username, password],
            [*head, user_md, *page_outputs, *building_outputs],
            **PRIVATE,
        )
        for trigger in (search_btn.click, query.submit, neighborhood.change):
            trigger(
                lambda s, q, n: on_search(client, s, q, n, 0),
                [state, query, neighborhood],
                [*head, *page_outputs, error_md],
                **PRIVATE,
            )
        prev_btn.click(
            lambda s, q, n: on_page(client, s, q, n, -1),
            [state, query, neighborhood],
            [*head, *page_outputs, error_md],
            **PRIVATE,
        )
        next_btn.click(
            lambda s, q, n: on_page(client, s, q, n, 1),
            [state, query, neighborhood],
            [*head, *page_outputs, error_md],
            **PRIVATE,
        )

        # Fonction annotée explicitement : Gradio injecte gr.SelectData d'après la
        # signature, qu'un functools.partial masquerait.
        def select_row(s: dict, evt: gr.SelectData):
            return on_select(client, s, evt)

        table.select(
            select_row,
            [state],
            [*head, card_md, year_dd, predict_btn, result_md, error_md],
            **PRIVATE,
        )
        predict_btn.click(
            lambda: gr.update(value="Calcul…", interactive=False),
            None,
            predict_btn,
            **PRIVATE,
        ).then(
            bind(on_predict, client),
            [state, year_dd, with_kumo],
            [*head, result_md, error_md],
            **PRIVATE,
        ).then(
            # Réactivé seulement si un bâtiment est sélectionné (session valide).
            lambda s: gr.update(value="Prédire", interactive=bool(s.get("building"))),
            [state],
            predict_btn,
            **PRIVATE,
        )
        logout_btn.click(
            on_logout, [state], [*head, password, *building_outputs], **PRIVATE
        )

    return demo
