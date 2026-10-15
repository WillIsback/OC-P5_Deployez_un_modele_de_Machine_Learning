"""Entrée CLI : ``uv run python -m app.training`` (lit le jeu préparé en base)."""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

from app.db import session as db_session
from app.db.registry import CATBOOST_NAME, register_model
from app.db.training_data import load_training_data
from app.training.pipeline import TrainPipeline


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Entraînement CatBoost multi-cible (P5)"
    )
    parser.add_argument("--output-dir", default="models")
    parser.add_argument(
        "--no-kumo", action="store_true", help="N'évalue pas le modèle Kumo"
    )
    parser.add_argument(
        "--cv-splits", type=int, default=5, help="Nombre de plis de validation croisée"
    )
    return parser


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    # Écritures confinées au projet : refuse un --output-dir hors du répertoire courant.
    output_dir = Path(args.output_dir).resolve()
    if not output_dir.is_relative_to(Path.cwd().resolve()):
        parser.error(
            f"--output-dir doit se trouver sous le répertoire du projet "
            f"({Path.cwd()}) : {args.output_dir}"
        )
    factory = db_session.owner_session_factory()
    with factory() as session:
        try:
            data = load_training_data(session)
        except RuntimeError as exc:
            parser.error(str(exc))
            return
    pipe = TrainPipeline(
        training_data=data, output_dir=output_dir, cv_splits=args.cv_splits
    )
    metrics = pipe.run(include_kumo=not args.no_kumo)
    with factory() as session:
        model = register_model(
            session,
            name=CATBOOST_NAME,
            version=datetime.now(UTC).strftime("%Y%m%d%H%M%S"),
            mlflow_run_id=pipe.mlflow_run_id,
            artifact_path=str(output_dir),
        )
        name, version = model.name, model.version
    # Lu par l'API au chargement des .cbm pour tracer la version réellement servie.
    version_info = {
        "name": name,
        "version": version,
        "mlflow_run_id": pipe.mlflow_run_id,
    }
    (output_dir / "version.json").write_text(
        json.dumps(version_info, indent=2), encoding="utf-8"
    )
    print(f"[done] {name} v{version} activé — scores: {metrics}")


if __name__ == "__main__":
    main()
