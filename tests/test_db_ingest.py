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
