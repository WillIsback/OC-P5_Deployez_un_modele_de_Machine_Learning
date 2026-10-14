"""Préparation brut → building_features (deuxième temps, spec §4.1).

Usage : ``uv run python -m app.db.prepare --year 2016 2017 2018 2019``
"""

from __future__ import annotations

import argparse
import os

import pandas as pd
from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.db import session as db_session
from app.db.mapping import RAW_SQL, features_to_sql, to_python
from app.db.models import BuildingFeatures, BuildingRecordRaw
from app.lib.tools import get_logger
from app.schemas.api import FEATURE_COLUMNS
from app.training import data_processing as dp

log = get_logger(__name__)

TRAINING_YEAR = int(os.getenv("TRAINING_YEAR", "2016"))
PREP_VERSION = "1"
REQUIRED_FEATURES = (
    "Latitude",
    "Longitude",
    "YearBuilt",
    "NumberofFloors",
    "PropertyGFAParking",
    "PropertyGFABuilding(s)",
)
CHUNK_SIZE = 1000


def load_raw_frame(session: Session, year: int) -> pd.DataFrame:
    """Brut d'une année, colonnes CSV, index = record_id (ordre d'ingestion)."""
    rows = session.scalars(
        select(BuildingRecordRaw)
        .where(BuildingRecordRaw.data_year == year)
        .order_by(BuildingRecordRaw.id)
    ).all()
    data = [{csv: getattr(r, col) for csv, col in RAW_SQL.items()} for r in rows]
    index = pd.Index([r.id for r in rows], name="record_id")
    return pd.DataFrame(data, index=index, columns=list(RAW_SQL))


def build_feature_rows(
    df_raw: pd.DataFrame, *, training: bool, test_size: float = 0.2, seed: int = 42
) -> pd.DataFrame:
    """Features nettoyées + rôle, éligibilité et split figé (entraînement seulement)."""
    scoped = dp.apply_common_corrections(dp.filter_scope(df_raw))
    missing = scoped[list(REQUIRED_FEATURES)].isna().any(axis=1)
    if missing.any():
        log.warning(
            "%d bâtiment(s) ignoré(s) : feature obligatoire manquante",
            int(missing.sum()),
        )
        scoped = scoped.loc[~missing]
    base = [c for c in FEATURE_COLUMNS if c not in ("Has_NaturalGas", "Has_Steam")]
    out = dp.prepare_catboost(scoped[base], dp.build_flags(df_raw, scoped))
    if training:
        eligibility = dp.flag_training_eligibility(scoped)
        out["dataset_role"] = "training"
        out["is_training_eligible"] = eligibility["is_training_eligible"]
        out["exclusion_reason"] = eligibility["exclusion_reason"]
        eligible = out.index[out["is_training_eligible"].to_numpy(dtype=bool)]
        split = dp.assign_split(eligible, test_size=test_size, seed=seed)
        out["split"] = split.reindex(out.index)
    else:
        out["dataset_role"] = "production"
        out["is_training_eligible"] = False
        out["exclusion_reason"] = None
        out["split"] = None
    return out


def prepare_year(session: Session, year: int) -> int:
    """Calcule et upsert les features d'une année ; renvoie le nombre de lignes."""
    df_raw = load_raw_frame(session, year)
    if df_raw.empty:
        raise RuntimeError(
            f"Aucune donnée brute pour {year} : lancez d'abord app.db.ingest."
        )
    rows = build_feature_rows(df_raw, training=(year == TRAINING_YEAR))
    payload = []
    for record_id, row in rows.iterrows():
        values = features_to_sql(row)
        values.update(
            record_id=int(record_id),
            dataset_role=row["dataset_role"],
            is_training_eligible=bool(row["is_training_eligible"]),
            exclusion_reason=to_python(row["exclusion_reason"]),
            split=to_python(row["split"]),
            prep_version=PREP_VERSION,
        )
        payload.append(values)
    for start in range(0, len(payload), CHUNK_SIZE):
        chunk = payload[start : start + CHUNK_SIZE]
        stmt = pg_insert(BuildingFeatures).values(chunk)
        updates = {c: stmt.excluded[c] for c in chunk[0] if c != "record_id"}
        session.execute(
            stmt.on_conflict_do_update(
                index_elements=["record_id"],
                set_=updates | {"prepared_at": func.now()},
            )
        )
    # Lignes devenues hors périmètre depuis la dernière préparation.
    year_records = select(BuildingRecordRaw.id).where(
        BuildingRecordRaw.data_year == year
    )
    session.execute(
        delete(BuildingFeatures).where(
            BuildingFeatures.record_id.in_(year_records),
            BuildingFeatures.record_id.not_in([p["record_id"] for p in payload]),
        )
    )
    session.commit()
    return len(payload)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Préparation des features")
    parser.add_argument("--year", type=int, nargs="+", required=True)
    args = parser.parse_args(argv)
    with db_session.owner_session_factory()() as session:
        for year in args.year:
            try:
                count = prepare_year(session, year)
            except RuntimeError as exc:
                parser.error(str(exc))
            print(f"[prepare] {year} : {count} bâtiments dans le périmètre")


if __name__ == "__main__":
    main()
