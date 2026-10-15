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
