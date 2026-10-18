"""Gestionnaires d'événements de l'interface, sans réseau (client simulé).

Le client réel est testé de bout en bout dans tests/test_ui_client.py ; ici, on
vérifie ce que chaque action affiche. Chaque gestionnaire renvoie d'abord
(state, login_panel, main_panel, login_message).
"""

from types import SimpleNamespace

import gradio as gr
import pytest

from app.ui import app as ui
from app.ui.client import ApiError, SessionExpired
from app.ui.format import building_card, prediction_card

ITEMS = [
    {"building_id": i, "property_name": f"BÂTIMENT {i}", "neighborhood": "NORTH"}
    for i in range(1, 21)
]
DETAIL = {
    "building_id": 28,
    "property_name": "GRAHAM HILL ELEMENTARY SCHOOL",
    "address": "5101 S GRAHAM ST",
    "zip_code": "98118",
    "neighborhood": "SOUTHEAST",
    "years": [
        {"data_year": 2016, "primary_property_type": "K-12 School", "year_built": 1961},
        {"data_year": 2019, "primary_property_type": "K-12 School", "year_built": 1961},
    ],
}
CATBOOST = {
    "energy_use_kbtu": 3088219.8,
    "ghg_emissions_tco2e": 99.2,
    "prediction_id": 7,
}
KUMO = {"energy_use_kbtu": 525813.2, "ghg_emissions_tco2e": 18.4, "prediction_id": 8}


class FakeClient:
    """Réponses figées ; ``fail`` lève l'erreur donnée sur la méthode nommée."""

    def __init__(self, total=45, fail=None):
        self.total = total
        self.fail = fail or {}
        self.calls = []

    def _maybe_fail(self, name):
        if name in self.fail:
            raise self.fail[name]

    def login(self, username, password):
        self._maybe_fail("login")
        return "jeton"

    def search_buildings(self, token, *, q=None, neighborhood=None, limit=20, offset=0):
        self.calls.append(("search", q, neighborhood, offset))
        self._maybe_fail("search")
        items = ITEMS[: max(0, min(limit, self.total - offset))]
        return {"items": items, "total": self.total, "limit": limit, "offset": offset}

    def get_building(self, token, building_id):
        self._maybe_fail("select")
        return DETAIL

    def predict(self, token, building_id, data_year=None):
        self.calls.append(("predict", building_id, data_year))
        self._maybe_fail("predict")
        return CATBOOST

    def compare(self, token, building_id, data_year=None):
        self.calls.append(("compare", building_id, data_year))
        self._maybe_fail("predict")
        return {"catboost_prediction": CATBOOST, "kumo_prediction": KUMO}


def logged_state():
    return {**ui.new_state(), "token": "jeton", "username": "johndoe"}


def visible(update):
    return update["visible"]


def test_login_success_shows_main():
    out = ui.on_login(FakeClient(), ui.new_state(), "johndoe", "secret")
    state, login, main, message, user_md, table, page_md, prev_btn, next_btn = out[:9]
    assert message == ""
    assert state["token"] == "jeton" and state["username"] == "johndoe"
    assert not visible(login) and visible(main)
    assert "Connecté : johndoe" in user_md
    assert len(table["value"]) == 20
    assert page_md == "1–20 / 45"
    assert prev_btn["interactive"] is False and next_btn["interactive"] is True


def test_login_failure_message():
    client = FakeClient(
        fail={"login": ApiError(400, "Identifiants incorrects ou compte inactif")}
    )
    state, login, main, message, *_ = ui.on_login(
        client, ui.new_state(), "johndoe", "x"
    )
    assert state["token"] is None
    assert visible(login) and not visible(main)
    assert "Identifiants incorrects" in message


def test_login_api_unreachable():
    client = FakeClient(fail={"login": ApiError(None, "API indisponible")})
    *_, message = ui.on_login(client, ui.new_state(), "johndoe", "secret")[:4]
    assert "API indisponible" in message


def test_search_ignores_short_query():
    client = FakeClient()
    ui.on_search(client, logged_state(), "a", "Tous", 0)
    assert client.calls[-1] == ("search", None, None, 0)


def test_search_filters_neighborhood():
    client = FakeClient()
    ui.on_search(client, logged_state(), "école", "BALLARD", 0)
    assert client.calls[-1] == ("search", "école", "BALLARD", 0)


def test_search_no_result():
    out = ui.on_search(FakeClient(total=0), logged_state(), "", "Tous", 0)
    table, page_md, prev_btn, next_btn, error_md = out[4:]
    assert not visible(error_md)
    assert table["value"] == []
    assert page_md == "Aucun bâtiment trouvé"
    assert prev_btn["interactive"] is False and next_btn["interactive"] is False


def test_search_api_unreachable():
    client = FakeClient(fail={"search": ApiError(None, "API indisponible")})
    error_md = ui.on_search(client, logged_state(), "", "Tous", 0)[-1]
    assert visible(error_md) and "API indisponible" in error_md["value"]


@pytest.mark.parametrize(
    ("offset", "step", "expected"),
    [(0, -1, 0), (0, 1, 20), (20, 1, 40), (40, 1, 40), (40, -1, 20)],
)
def test_pagination_bounds(offset, step, expected):
    client = FakeClient(total=45)
    state = {**logged_state(), "offset": offset, "total": 45}
    new_state = ui.on_page(client, state, "", "Tous", step)[0]
    assert new_state["offset"] == expected
    assert client.calls[-1][-1] == expected


def test_select_building_fills_card():
    evt = SimpleNamespace(row_value=[28, "GRAHAM HILL", "SOUTHEAST"])
    out = ui.on_select(FakeClient(), logged_state(), evt)
    state, card_md, year_dd, predict_btn, result_md, error_md = out[0], *out[4:]
    assert state["building"] == DETAIL
    assert card_md == building_card(DETAIL)
    assert year_dd["choices"] == [2016, 2019] and year_dd["value"] == 2019
    assert predict_btn["interactive"] is True
    assert result_md == "" and not visible(error_md)


def test_predict_catboost():
    client = FakeClient()
    state = {**logged_state(), "building": DETAIL}
    result_md, error_md = ui.on_predict(client, state, 2019, False)[4:]
    assert client.calls[-1] == ("predict", 28, 2019)
    assert result_md == prediction_card(CATBOOST, "CatBoost")
    assert not visible(error_md)


def test_predict_with_kumo():
    client = FakeClient()
    state = {**logged_state(), "building": DETAIL}
    result_md = ui.on_predict(client, state, 2019, True)[4]
    assert client.calls[-1] == ("compare", 28, 2019)
    assert prediction_card(CATBOOST, "CatBoost") in result_md
    assert prediction_card(KUMO, "Kumo-Tabular") in result_md


def test_predict_error_banner():
    client = FakeClient(
        fail={"predict": ApiError(503, "Modèle Kumo-Tabular indisponible")}
    )
    state = {**logged_state(), "building": DETAIL}
    result_md, error_md = ui.on_predict(client, state, 2019, True)[4:]
    assert result_md == ""
    assert visible(error_md) and "Modèle Kumo-Tabular indisponible" in error_md["value"]


@pytest.mark.parametrize("action", ["search", "select", "predict"])
def test_expired_session_returns_to_login(action):
    client = FakeClient(fail={action: SessionExpired()})
    state = {**logged_state(), "building": DETAIL}
    calls = {
        "search": lambda: ui.on_search(client, state, "", "Tous", 0),
        "select": lambda: ui.on_select(client, state, SimpleNamespace(row_value=[28])),
        "predict": lambda: ui.on_predict(client, state, 2019, False),
    }
    new_state, login, main, message, *rest = calls[action]()
    assert new_state["token"] is None
    assert visible(login) and not visible(main)
    assert message == "Session expirée, reconnectez-vous"
    assert all(u == gr.update() for u in rest)


def test_logout_clears_password():
    state, login, main, message, password = ui.on_logout(logged_state())[:5]
    assert state == ui.new_state()
    assert visible(login) and not visible(main) and message == ""
    assert password == ""  # pas de mot de passe laissé à l'écran


def test_build_app_and_light_theme():
    demo = ui.build_app(lambda: FakeClient())
    assert isinstance(demo, gr.Blocks)
    assert "__theme" in ui.LAUNCH_OPTIONS["js"] and "light" in ui.LAUNCH_OPTIONS["js"]
    assert ui.LAUNCH_OPTIONS["footer_links"] == []
    assert len(ui.NEIGHBORHOODS) == 13


def test_no_gradio_telemetry():
    """Aucun appel sortant de Gradio (statistiques, vérification de version)."""
    import os

    assert os.environ["GRADIO_ANALYTICS_ENABLED"] == "False"


def test_build_app_wires_events_without_warning():
    """Gradio avertit quand il ne reconnaît pas la signature d'un gestionnaire
    (ex. ``gr.SelectData`` masqué par un ``functools.partial``) : l'événement
    ne serait alors pas injecté et le clic sur une ligne resterait sans effet."""
    import warnings

    with warnings.catch_warnings():
        warnings.filterwarnings("error", category=UserWarning, module=r"gradio\.")
        ui.build_app(lambda: FakeClient())


def test_select_building_error_banner():
    client = FakeClient(fail={"select": ApiError(404, "Bâtiment 28 introuvable")})
    error_md = ui.on_select(client, logged_state(), SimpleNamespace(row_value=[28]))[-1]
    assert visible(error_md) and "Bâtiment 28 introuvable" in error_md["value"]


def test_row_selection_is_wired_to_on_select():
    """Le clic sur une ligne du tableau appelle on_select avec l'événement."""
    demo = ui.build_app(lambda: FakeClient())
    (select_row,) = [f.fn for f in demo.fns.values() if f.name == "select_row"]
    out = select_row(logged_state(), SimpleNamespace(row_value=[28, "GRAHAM HILL"]))
    assert out[0]["building"] == DETAIL


def test_main_module_imports_without_launching():
    import importlib

    module = importlib.import_module("app.ui.__main__")
    assert module.build_app is ui.build_app


def test_neighborhood_filter_uses_dataset_values():
    """Le filtre compare la valeur exacte de l'identité du bâtiment : Delridge y
    est « DELRIDGE NEIGHBORHOODS » (49 bâtiments consultables sur 50)."""
    assert "DELRIDGE NEIGHBORHOODS" in ui.NEIGHBORHOODS
    assert "DELRIDGE" not in ui.NEIGHBORHOODS


def test_results_table_is_plain():
    """Tableau épuré : sans barre d'outils, police du texte courant (pas de
    chasse fixe, qui tronquait la colonne « Quartier »). Pas de column_widths
    en pourcentages : le tableau se redimensionnait en boucle."""
    demo = ui.build_app(lambda: FakeClient())
    (table,) = [b for b in demo.blocks.values() if isinstance(b, gr.Dataframe)]
    assert table.buttons == []
    assert not table.column_widths
    theme = ui.LAUNCH_OPTIONS["theme"]
    assert theme._font_mono == theme._font


@pytest.mark.parametrize(
    ("username", "password"), [("", ""), ("johndoe", ""), ("  ", "x")]
)
def test_login_requires_both_fields(username, password):
    client = FakeClient()
    state, login, main, message, *_ = ui.on_login(
        client, ui.new_state(), username, password
    )
    assert state["token"] is None
    assert visible(login) and not visible(main)
    assert message == "Saisissez votre identifiant et votre mot de passe."
    assert client.calls == []  # aucun appel à l'API


def test_no_run_history_nor_public_api():
    """Gradio enregistre par défaut les entrées de chaque événement (dont le mot
    de passe) dans le localStorage (/gradio_api/runs) et expose chaque événement
    en API publique : les deux sont désactivés."""
    assert ui.LAUNCH_OPTIONS["run_history"] is False
    demo = ui.build_app(lambda: FakeClient())
    assert {f.api_visibility for f in demo.fns.values()} == {"private"}


RIGHT_RESET = "Sélectionnez un bâtiment dans la liste."


def test_logout_resets_building_panel():
    out = ui.on_logout({**logged_state(), "building": DETAIL})
    card_md, year_dd, predict_btn, result_md, error_md = out[5:]
    assert card_md == RIGHT_RESET
    assert year_dd["choices"] == [] and year_dd["value"] is None
    assert predict_btn["interactive"] is False
    assert result_md == "" and not visible(error_md)


def test_login_resets_building_panel():
    out = ui.on_login(FakeClient(), ui.new_state(), "johndoe", "secret")
    assert tuple(out[9:]) == ui._building_reset()


def test_expired_session_resets_building_panel():
    client = FakeClient(fail={"predict": SessionExpired()})
    out = ui.on_predict(client, {**logged_state(), "building": DETAIL}, 2019, False)
    assert out[0]["building"] is None
    assert visible(out[1]) and not visible(out[2])


def test_predict_without_building():
    """Bouton resté actif (ex. après reconnexion) : message, pas de TypeError."""
    client = FakeClient()
    result_md, error_md = ui.on_predict(client, logged_state(), 2019, False)[4:]
    assert result_md == ""
    assert "Sélectionnez un bâtiment" in error_md["value"]
    assert client.calls == []


def test_launch_listens_on_localhost_by_default(monkeypatch):
    monkeypatch.delenv("GRADIO_SERVER_NAME", raising=False)
    assert ui.launch_options()["server_name"] == "127.0.0.1"
    monkeypatch.setenv("GRADIO_SERVER_NAME", "0.0.0.0")
    assert ui.launch_options()["server_name"] == "0.0.0.0"
    assert ui.launch_options()["server_port"] == 7860
