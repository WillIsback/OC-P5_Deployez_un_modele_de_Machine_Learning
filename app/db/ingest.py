"""Ingestion d'un CSV Seattle (une année) : nettoyage, features, cibles réelles.

Usage : ``uv run python -m app.db.ingest --year 2016 --csv data/2016_….csv``

Deux formats sont acceptés : le CSV 2016 d'entraînement, et l'export open data
Seattle 2015→aujourd'hui (2017–2019), ramené au schéma 2016 par
``app.db.harmonize`` avant écriture. Pour l'année d'entraînement
(``TRAINING_YEAR``), l'ingestion fige aussi le split train/test par bâtiment.
"""

from __future__ import annotations

import argparse
from collections.abc import Iterator
from pathlib import Path

import pandas as pd
from sqlalchemy import delete, func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.db import harmonize
from app.db import session as db_session
from app.db.mapping import (
    FEATURE_SQL,
    FLAG_COLUMNS,
    SOURCE_COLUMNS,
    TARGET_SQL,
    coerce_row,
    features_to_sql,
    to_python,
)
from app.db.models import Building, BuildingActual, BuildingYear, Prediction
from app.db.prepare import PREP_VERSION, TRAINING_YEAR, build_feature_rows
from app.lib.tools import get_logger
from app.training import data_processing as dp

log = get_logger(__name__)

SUPPORTED_YEARS: tuple[int, ...] = (2016, 2017, 2018, 2019)

REQUIRED_SOURCE_COLUMNS: tuple[str, ...] = (
    "OSEBuildingID",
    "DataYear",
    *(c for c in FEATURE_SQL if c not in FLAG_COLUMNS),
    "NaturalGas(kBtu)",
    "SteamUse(kBtu)",
    *TARGET_SQL,
)

# Colonne de `buildings` → colonne du fichier normalisé.
IDENTITY_SOURCE = {
    "property_name": "PropertyName",
    "address": "Address",
    "zip_code": "ZipCode",
    "neighborhood": "Neighborhood",
    "building_type": "BuildingType",
    "primary_property_type": "PrimaryPropertyType",
}

CHUNK_SIZE = 500  # 500 × 22 colonnes < limite de 65 535 paramètres


def normalize_columns(
    df: pd.DataFrame,
    year: int,
    reference_building_types: dict[int, str] | None = None,
) -> pd.DataFrame:
    """Ramène un fichier annuel aux colonnes de SOURCE_COLUMNS (manquantes → NaN)."""
    if year not in SUPPORTED_YEARS:
        raise ValueError(f"Année non supportée : {year} (ajoutez-la à SUPPORTED_YEARS)")
    out = df
    if harmonize.is_open_data(df):
        out = harmonize.from_open_data(df, reference_building_types)
    missing = [c for c in REQUIRED_SOURCE_COLUMNS if c not in out.columns]
    if missing:
        raise ValueError(f"Colonnes obligatoires absentes pour {year} : {missing}")
    unknown = sorted(set(out.columns) - set(SOURCE_COLUMNS))
    if unknown:
        log.warning("Colonnes ignorées pour %s : %s", year, unknown)
    years = {int(y) for y in out["DataYear"].dropna().unique()}
    if years != {year}:
        raise ValueError(f"DataYear incohérent : {sorted(years)} (attendu {year})")
    return out.reindex(columns=list(SOURCE_COLUMNS))


def reference_building_types(session: Session) -> dict[int, str]:
    """BuildingType déjà connu par bâtiment (référence de l'harmonisation)."""
    rows = session.execute(
        select(Building.id, Building.building_type).where(
            Building.building_type.is_not(None)
        )
    ).all()
    return dict(rows)


def _chunks(items: list, size: int = CHUNK_SIZE) -> Iterator[list]:
    for start in range(0, len(items), size):
        yield items[start : start + size]


def _upsert_buildings(session: Session, df: pd.DataFrame) -> None:
    """Identité de tous les bâtiments du fichier, hors périmètre compris."""
    corrected = dp.apply_common_corrections(df)
    records = [
        {"id": int(building_id)}
        | coerce_row(Building, {col: row[src] for col, src in IDENTITY_SOURCE.items()})
        for building_id, row in corrected.iterrows()
    ]
    table = Building.__table__
    for chunk in _chunks(records):
        stmt = pg_insert(Building).values(chunk)
        # Une valeur absente du fichier n'efface pas l'identité déjà connue.
        updates = {
            col: func.coalesce(stmt.excluded[col], table.c[col])
            for col in IDENTITY_SOURCE
        }
        session.execute(stmt.on_conflict_do_update(index_elements=["id"], set_=updates))


def _upsert_years(session: Session, rows: pd.DataFrame, year: int) -> dict[int, int]:
    """Features de l'année ; retourne building_id → building_years.id."""
    payload = [
        features_to_sql(row)
        | {
            "building_id": int(building_id),
            "data_year": year,
            "exclusion_reason": to_python(row["exclusion_reason"]),
            "prep_version": PREP_VERSION,
        }
        for building_id, row in rows.iterrows()
    ]
    for chunk in _chunks(payload):
        stmt = pg_insert(BuildingYear).values(chunk)
        updates = {
            c: stmt.excluded[c]
            for c in chunk[0]
            if c not in ("building_id", "data_year")
        }
        session.execute(
            stmt.on_conflict_do_update(
                index_elements=["building_id", "data_year"],
                set_=updates | {"prepared_at": func.now()},
            )
        )
    return dict(
        session.execute(
            select(BuildingYear.building_id, BuildingYear.id).where(
                BuildingYear.data_year == year
            )
        ).all()
    )


def _upsert_actuals(
    session: Session, df: pd.DataFrame, rows: pd.DataFrame, year_ids: dict[int, int]
) -> None:
    targets = df.loc[rows.index, list(TARGET_SQL)]
    records = [
        coerce_row(BuildingActual, {TARGET_SQL[c]: row[c] for c in TARGET_SQL})
        | {"building_year_id": year_ids[int(building_id)]}
        for building_id, row in targets.iterrows()
    ]
    for chunk in _chunks(records):
        stmt = pg_insert(BuildingActual).values(chunk)
        session.execute(
            stmt.on_conflict_do_update(
                index_elements=["building_year_id"],
                set_={col: stmt.excluded[col] for col in TARGET_SQL.values()},
            )
        )


def _assign_splits(session: Session, rows: pd.DataFrame) -> None:
    """Remplace le split de tous les bâtiments par celui de l'année d'entraînement."""
    session.execute(update(Building).values(split=None))
    for label in ("train", "test"):
        ids = [int(i) for i in rows.index[rows["split"] == label]]
        for chunk in _chunks(ids):
            session.execute(
                update(Building).where(Building.id.in_(chunk)).values(split=label)
            )


def _drop_stale_years(session: Session, kept: pd.Index, year: int) -> None:
    """Supprime les lignes d'année sorties du périmètre (sauf si déjà prédites)."""
    predicted = select(Prediction.building_year_id).where(
        Prediction.building_year_id.is_not(None)
    )
    session.execute(
        delete(BuildingYear).where(
            BuildingYear.data_year == year,
            BuildingYear.building_id.not_in([int(i) for i in kept]),
            BuildingYear.id.not_in(predicted),
        )
    )


def ingest_frame(session: Session, df: pd.DataFrame, *, year: int) -> int:
    """Upsert buildings / building_years / building_actuals ; retourne le nombre
    de lignes d'année (bâtiments dans le périmètre du modèle)."""
    reference = (
        reference_building_types(session) if harmonize.is_open_data(df) else None
    )
    df = normalize_columns(df, year, reference).dropna(subset=["OSEBuildingID"])
    dup = df["OSEBuildingID"].duplicated(keep="last")
    if dup.any():
        log.warning(
            "%d doublon(s) d'OSEBuildingID pour %s : dernière ligne conservée",
            int(dup.sum()),
            year,
        )
        df = df.loc[~dup]
    df = df.set_index(df["OSEBuildingID"].astype(int).rename("building_id"))
    training = year == TRAINING_YEAR
    rows = build_feature_rows(df, training=training)
    _upsert_buildings(session, df)
    year_ids = _upsert_years(session, rows, year)
    _upsert_actuals(session, df, rows, year_ids)
    if training:
        _assign_splits(session, rows)
    _drop_stale_years(session, rows.index, year)
    session.commit()
    return len(rows)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Ingestion d'un CSV Seattle")
    parser.add_argument("--year", type=int, required=True)
    parser.add_argument("--csv", required=True, help="Chemin du CSV de l'année")
    parser.add_argument(
        "--download",
        action="store_true",
        help="Télécharge le CSV s'il est absent (2016 : CSV du projet ; "
        "autres années : export open data Seattle filtré sur l'année)",
    )
    return parser


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    path = Path(args.csv)
    if args.download and args.year == 2016:
        dp.ensure_dataset(path, download=True)
    elif args.download:
        harmonize.download_open_data_year(args.year, path)
    if not path.exists():
        parser.error(f"CSV introuvable : {path}")
    df = pd.read_csv(path, low_memory=False)
    with db_session.owner_session_factory()() as session:
        count = ingest_frame(session, df, year=args.year)
    print(f"[ingest] {count} bâtiments {args.year} dans le périmètre ({path.name})")


if __name__ == "__main__":
    main()
