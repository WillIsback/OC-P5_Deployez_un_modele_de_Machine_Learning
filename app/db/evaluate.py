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
from app.db.mapping import feature_values, features_from_sql
from app.db.models import (
    BuildingFeatures,
    BuildingRecordRaw,
    MlModel,
    Prediction,
    PredictionInput,
)
from app.db.registry import CATBOOST_NAME, active_model
from app.lib.tools import metrics_reelles
from app.schemas.api import FEATURE_COLUMNS

TARGET_PAIRS = {
    "energy": ("predicted_energy_kbtu", "actual_energy_kbtu"),
    "emissions": ("predicted_ghg_tco2e", "actual_ghg_tco2e"),
}

# Plages plausibles d'intensité (cible réelle / PropertyGFATotal), arrondies à
# partir des bâtiments éligibles de 2016 (EUI 1,4–906 kBtu/sf ; émissions
# ≤ 34 kg CO2e/sf). L'open data n'a plus la colonne Outlier de 2016 : sans ce
# garde-fou, une seule déclaration erronée (bâtiment 755 en 2019, 278 fois sa
# consommation 2018) suffit à écraser le R² d'une année.
SITE_EUI_RANGE = (1.0, 1000.0)  # kBtu/sf
GHG_INTENSITY_MAX = 0.05  # t CO2e/sf


def exclusion_reason(df: pd.DataFrame) -> pd.Series:
    """Raison d'exclure un bâtiment de l'évaluation (None = conservé).

    Reprend les filtres de l'entraînement (conformité) et remplace le flag
    Outlier, absent après 2016, par les plages d'intensité ci-dessus.
    """
    reason = pd.Series([None] * len(df), index=df.index, dtype=object)
    gfa = df["property_gfa_total"].where(df["property_gfa_total"] > 0)
    eui = df["actual_energy_kbtu"] / gfa
    ghg = df["actual_ghg_tco2e"] / gfa
    low, high = SITE_EUI_RANGE
    checks = [
        (df["compliance_status"].ne("Compliant"), "non_compliant"),
        ((eui < low) | (eui > high), "aberrant_energy"),
        (ghg > GHG_INTENSITY_MAX, "aberrant_emissions"),
    ]
    for mask, label in checks:
        reason[mask & reason.isna()] = label
    return reason


def _pending_features(
    session: Session, model: MlModel, years: list[int]
) -> list[BuildingFeatures]:
    """Bâtiments de production pas encore prédits en batch par ce modèle."""
    done = (
        select(PredictionInput.building_record_id)
        .join(Prediction, Prediction.prediction_input_id == PredictionInput.id)
        .where(Prediction.model_id == model.id, PredictionInput.input_source == "batch")
    )
    return list(
        session.scalars(
            select(BuildingFeatures)
            .join(BuildingRecordRaw, BuildingRecordRaw.id == BuildingFeatures.record_id)
            .where(
                BuildingFeatures.dataset_role == "production",
                BuildingRecordRaw.data_year.in_(years),
                BuildingFeatures.record_id.not_in(done),
            )
            .order_by(BuildingFeatures.record_id)
        ).all()
    )


def projected_metrics(
    session: Session, model: MlModel, years: list[int]
) -> pd.DataFrame:
    """Métriques par année et par cible, calculées depuis la vue SQL.

    Les bâtiments non conformes ou aux intensités aberrantes sont exclus
    (``exclusion_reason``) ; leur nombre est reporté dans ``n_excluded``.
    """
    rows = (
        session.execute(
            text(
                "SELECT e.*, r.compliance_status, r.property_gfa_total "
                "FROM v_projected_evaluation e "
                "JOIN building_records_raw r "
                "ON r.building_id = e.building_id AND r.data_year = e.data_year "
                "WHERE e.model_name = :name AND e.model_version = :version "
                "AND e.data_year = ANY(:years)"
            ),
            {"name": model.name, "version": model.version, "years": years},
        )
        .mappings()
        .all()
    )
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame([dict(r) for r in rows])
    df["exclusion_reason"] = exclusion_reason(df)
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
    pending = _pending_features(session, model, years)
    for start in range(0, len(pending), batch_size):
        chunk = pending[start : start + batch_size]
        inputs = [
            PredictionInput(
                input_source="batch",
                building_record_id=f.record_id,
                **feature_values(f),
            )
            for f in chunk
        ]
        session.add_all(inputs)
        session.commit()  # entrées commitées avant tout appel au modèle
        frame = pd.DataFrame([features_from_sql(i) for i in inputs])[FEATURE_COLUMNS]
        preds = model_service.predict_frame(frame)
        session.add_all(
            Prediction(
                prediction_input_id=inp.id,
                model_id=model.id,
                energy_use_kbtu=float(energy),
                ghg_emissions_tco2e=float(ghg),
            )
            for inp, energy, ghg in zip(inputs, preds["energy"], preds["emissions"])
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
