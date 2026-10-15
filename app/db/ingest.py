"""Ingestion d'un CSV Seattle (une année) vers le schéma brut.

Usage : ``uv run python -m app.db.ingest --year 2016 --csv data/2016_….csv``
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd
from sqlalchemy import func
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.db import session as db_session
from app.db.mapping import FEATURE_SQL, FLAG_COLUMNS, RAW_SQL, TARGET_SQL, coerce_row
from app.db.models import Building, BuildingActual, BuildingRecordRaw
from app.lib.tools import get_logger
from app.training import data_processing as dp

log = get_logger(__name__)

# Renommages source → noms 2016, par année. Compléter à partir des en-têtes
# réels des fichiers 2017–2019 (voir Step 5).
YEAR_COLUMN_RENAMES: dict[int, dict[str, str]] = {
    2016: {},
    2017: {},
    2018: {},
    2019: {},
}

REQUIRED_SOURCE_COLUMNS: tuple[str, ...] = (
    "OSEBuildingID",
    "DataYear",
    *(c for c in FEATURE_SQL if c not in FLAG_COLUMNS),
    "NaturalGas(kBtu)",
    "SteamUse(kBtu)",
    *TARGET_SQL,
)

CHUNK_SIZE = 500  # 500 × 47 colonnes < limite de 65 535 paramètres


def normalize_columns(df: pd.DataFrame, year: int) -> pd.DataFrame:
    """Ramène un fichier annuel aux colonnes de RAW_SQL (manquantes → NaN)."""
    if year not in YEAR_COLUMN_RENAMES:
        raise ValueError(
            f"Année non supportée : {year} (ajoutez-la à YEAR_COLUMN_RENAMES)"
        )
    out = df.rename(columns=YEAR_COLUMN_RENAMES[year])
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


def _chunks(items: list, size: int = CHUNK_SIZE):
    for start in range(0, len(items), size):
        yield items[start : start + size]


def ingest_frame(
    session: Session, df: pd.DataFrame, *, year: int, source_file: str
) -> int:
    """Upsert buildings / records / actuals ; retourne le nombre de lignes."""
    df = normalize_columns(df, year).dropna(subset=["OSEBuildingID"])
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
        help="Télécharge le CSV 2016 s'il est absent (2016 uniquement)",
    )
    return parser


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    path = Path(args.csv)
    if args.download and args.year != 2016:
        parser.error("--download n'est valable que pour --year 2016")
    if args.download:
        dp.ensure_dataset(path, download=True)
    if not path.exists():
        parser.error(f"CSV introuvable : {path}")
    df = pd.read_csv(path)
    with db_session.owner_session_factory()() as session:
        count = ingest_frame(session, df, year=args.year, source_file=path.name)
    print(f"[ingest] {count} lignes {args.year} depuis {path.name}")


if __name__ == "__main__":
    main()
