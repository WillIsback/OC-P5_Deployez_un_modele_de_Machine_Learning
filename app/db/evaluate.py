"""Évaluation projetée du modèle actif sur les années de production.

Usage : ``uv run python -m app.db.evaluate --years 2017 2018 2019``
"""

from __future__ import annotations

import argparse

import pandas as pd
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.core import model_service
from app.db import session as db_session
from app.db.mapping import features_from_sql
from app.db.models import BuildingYear, MlModel, Prediction
from app.db.prepare import TRAINING_YEAR
from app.db.registry import CATBOOST_NAME, active_model
from app.lib.tools import metrics_reelles
from app.schemas.api import FEATURE_COLUMNS

TARGET_PAIRS = {
    "energy": ("predicted_energy_kbtu", "actual_energy_kbtu"),
    "emissions": ("predicted_ghg_tco2e", "actual_ghg_tco2e"),
}


def _pending_years(
    session: Session, model: MlModel, years: list[int]
) -> list[BuildingYear]:
    """Lignes de production pas encore prédites en batch par ce modèle."""
    done = select(Prediction.building_year_id).where(
        Prediction.model_id == model.id, Prediction.api_request_id.is_(None)
    )
    return list(
        session.scalars(
            select(BuildingYear)
            .where(
                BuildingYear.data_year.in_(years),
                BuildingYear.data_year != TRAINING_YEAR,
                BuildingYear.id.not_in(done),
            )
            .order_by(BuildingYear.id)
        ).all()
    )


def projected_metrics(
    session: Session, model: MlModel, years: list[int]
) -> pd.DataFrame:
    """Métriques par année et par cible, calculées depuis la vue SQL.

    Les bâtiments portant une ``exclusion_reason`` (non conformes, intensités
    aberrantes) sont exclus ; leur nombre est reporté dans ``n_excluded``.
    """
    rows = (
        session.execute(
            text(
                "SELECT * FROM v_projected_evaluation "
                "WHERE model_name = :name AND model_version = :version "
                "AND data_year = ANY(:years)"
            ),
            {"name": model.name, "version": model.version, "years": years},
        )
        .mappings()
        .all()
    )
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame([dict(r) for r in rows])
    out = []
    for year, group in df.groupby("data_year"):
        excluded = int(group["exclusion_reason"].notna().sum())
        kept = group.loc[group["exclusion_reason"].isna()]
        for target, (pred_col, actual_col) in TARGET_PAIRS.items():
            ok = kept[actual_col] > 0
            if not ok.any():
                continue
            scores = metrics_reelles(kept.loc[ok, actual_col], kept.loc[ok, pred_col])
            out.append(
                {
                    "data_year": int(year),
                    "target": target,
                    "n": int(ok.sum()),
                    "n_excluded": excluded,
                    **scores,
                }
            )
    return pd.DataFrame(out)


def evaluate_years(
    session: Session, years: list[int], *, batch_size: int = 500
) -> pd.DataFrame:
    """Prédit (une seule fois) les bâtiments de production puis calcule les métriques."""
    model = active_model(session, CATBOOST_NAME)
    pending = _pending_years(session, model, years)
    for start in range(0, len(pending), batch_size):
        chunk = pending[start : start + batch_size]
        features = [features_from_sql(row) for row in chunk]
        preds = model_service.predict_frame(pd.DataFrame(features)[FEATURE_COLUMNS])
        session.add_all(
            Prediction(
                building_year_id=row.id,
                model_id=model.id,
                input_features=feats,
                energy_use_kbtu=float(energy),
                ghg_emissions_tco2e=float(ghg),
            )
            for row, feats, energy, ghg in zip(
                chunk, features, preds["energy"], preds["emissions"]
            )
        )
        session.commit()
    return projected_metrics(session, model, years)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Évaluation projetée")
    parser.add_argument("--years", type=int, nargs="+", required=True)
    args = parser.parse_args(argv)
    with db_session.owner_session_factory()() as session:
        metrics = evaluate_years(session, args.years)
    if metrics.empty:
        print("[evaluate] aucune donnée de production pour ces années")
        return
    print(metrics.to_string(index=False))


if __name__ == "__main__":
    main()
