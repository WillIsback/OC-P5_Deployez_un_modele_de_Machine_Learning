"""Ingestion d'un CSV Seattle (une année) vers le schéma brut.

Usage : ``uv run python -m app.db.ingest --year 2016 --csv data/2016_….csv``

Deux formats sont acceptés : le CSV 2016 d'entraînement, et l'export open data
Seattle 2015→aujourd'hui (2017–2019), ramené au schéma 2016 par
``app.db.harmonize`` avant écriture.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.db import harmonize
from app.db import session as db_session
from app.db.mapping import FEATURE_SQL, FLAG_COLUMNS, RAW_SQL, TARGET_SQL, coerce_row
from app.db.models import Building, BuildingActual, BuildingRecordRaw
from app.db.prepare import TRAINING_YEAR
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

CHUNK_SIZE = 500  # 500 × 47 colonnes < limite de 65 535 paramètres


def normalize_columns(
    df: pd.DataFrame,
    year: int,
    reference_building_types: dict[int, str] | None = None,
) -> pd.DataFrame:
    """Ramène un fichier annuel aux colonnes de RAW_SQL (manquantes → NaN)."""
    if year not in SUPPORTED_YEARS:
        raise ValueError(f"Année non supportée : {year} (ajoutez-la à SUPPORTED_YEARS)")
    out = df
    if harmonize.is_open_data(df):
        out = harmonize.from_open_data(df, reference_building_types)
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


def reference_building_types(session: Session) -> dict[int, str]:
    """BuildingType de l'année d'entraînement, par bâtiment."""
    rows = session.execute(
        select(BuildingRecordRaw.building_id, BuildingRecordRaw.building_type).where(
            BuildingRecordRaw.data_year == TRAINING_YEAR,
            BuildingRecordRaw.building_type.is_not(None),
        )
    ).all()
    return dict(rows)


def _chunks(items: list, size: int = CHUNK_SIZE):
    for start in range(0, len(items), size):
        yield items[start : start + size]


def ingest_frame(
    session: Session, df: pd.DataFrame, *, year: int, source_file: str
) -> int:
    """Upsert buildings / records / actuals ; retourne le nombre de lignes."""
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
            c: stmt.excluded[c]
            for c in chunk[0]
            if c not in ("building_id", "data_year")
        }
        stmt = stmt.on_conflict_do_update(
            index_elements=["building_id", "data_year"],
            set_=updates | {"ingested_at": func.now()},
        ).returning(BuildingRecordRaw.id, BuildingRecordRaw.building_id)
        ids = {building_id: rid for rid, building_id in session.execute(stmt).all()}
        actuals = [
            {"record_id": ids[r["building_id"]]}
            | {TARGET_SQL[c]: r[RAW_SQL[c]] for c in TARGET_SQL}
            for r in chunk
        ]
        a = pg_insert(BuildingActual).values(actuals)
        session.execute(
            a.on_conflict_do_update(
                index_elements=["record_id"],
                set_={col: a.excluded[col] for col in TARGET_SQL.values()},
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
        count = ingest_frame(session, df, year=args.year, source_file=path.name)
    print(f"[ingest] {count} lignes {args.year} depuis {path.name}")


if __name__ == "__main__":
    main()
