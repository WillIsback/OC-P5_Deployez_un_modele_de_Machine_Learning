"""Tests de l'ingestion CSV → buildings / building_years / building_actuals."""

import logging

import pytest
from sqlalchemy import func, select
from synth import make_synth

from app.db import ingest
from app.db import session as db_session
from app.db.models import Building, BuildingActual, BuildingYear


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


def _count(session, model, *where):
    return session.scalar(select(func.count()).select_from(model).where(*where))


@pytest.mark.db
def test_ingest_inserts_and_is_idempotent(db):
    df = make_synth(40)
    with db() as s:
        n = ingest.ingest_frame(s, df, year=2016)
        df.loc[0, "SiteEnergyUse(kBtu)"] = 123.0
        assert ingest.ingest_frame(s, df, year=2016) == n
        assert _count(s, Building) == 40
        assert _count(s, BuildingYear) == n
        year = s.scalar(select(BuildingYear).where(BuildingYear.building_id == 0))
        assert s.get(BuildingActual, year.id).site_energy_use_kbtu == 123.0
        building = s.get(Building, 0)
        assert building.address == "0 st"
        assert building.zip_code in {"98101", "98102", "98103"}


@pytest.mark.db
def test_ingest_deduplicates_building_ids(db, caplog):
    df = make_synth(10)
    df.loc[1, "OSEBuildingID"] = 0
    df.loc[1, "PropertyName"] = "dernier"
    with db() as s, caplog.at_level(logging.WARNING):
        # 9 identifiants distincts dont 1 résidentiel : 8 lignes d'année.
        assert ingest.ingest_frame(s, df, year=2016) == 8
        assert s.get(Building, 0).property_name == "dernier"
    assert "doublon" in caplog.text


@pytest.mark.db
def test_ingest_main(db, tmp_path, monkeypatch):
    csv = tmp_path / "x.csv"
    make_synth(12).to_csv(csv, index=False)
    monkeypatch.setattr(db_session, "owner_session_factory", lambda: db)
    ingest.main(["--year", "2016", "--csv", str(csv)])
    with db() as s:
        assert _count(s, BuildingYear) == 11


@pytest.mark.db
def test_out_of_scope_building_kept_without_year_row(db):
    with db() as s:
        ingest.ingest_frame(s, make_synth(40), year=2016)
        assert s.get(Building, 39) is not None  # résidentiel : identité seule
        assert _count(s, BuildingYear, BuildingYear.building_id == 39) == 0


@pytest.mark.db
def test_training_year_assigns_split_on_eligible_buildings(db):
    with db() as s:
        ingest.ingest_frame(s, make_synth(200), year=2016)
        splits = dict(s.execute(select(Building.id, Building.split)).all())
        reasons = dict(
            s.execute(
                select(BuildingYear.building_id, BuildingYear.exclusion_reason)
            ).all()
        )
    eligible = {b for b, reason in reasons.items() if reason is None}
    assert {b for b, v in splits.items() if v is not None} == eligible
    assert {v for v in splits.values() if v} == {"train", "test"}


@pytest.mark.db
def test_production_year_never_assigns_split(db):
    with db() as s:
        ingest.ingest_frame(s, make_synth(40).assign(DataYear=2018), year=2018)
        assert _count(s, Building, Building.split.is_not(None)) == 0


@pytest.mark.db
def test_production_ingest_keeps_training_split(db):
    with db() as s:
        ingest.ingest_frame(s, make_synth(80), year=2016)
        before = dict(s.execute(select(Building.id, Building.split)).all())
        ingest.ingest_frame(s, make_synth(80).assign(DataYear=2018), year=2018)
        after = dict(s.execute(select(Building.id, Building.split)).all())
    assert before == after


@pytest.mark.db
def test_reingest_removes_year_rows_leaving_scope(db):
    df = make_synth(40)
    with db() as s:
        n = ingest.ingest_frame(s, df, year=2016)
        df.loc[0, "BuildingType"] = "Multifamily LR (1-4)"
        assert ingest.ingest_frame(s, df, year=2016) == n - 1
        assert _count(s, BuildingYear, BuildingYear.building_id == 0) == 0
        assert s.get(Building, 0).split is None
