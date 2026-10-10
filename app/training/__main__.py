"""Entrée CLI : ``uv run python -m app.training [--download]``."""

from __future__ import annotations

import argparse

from app.training import data_processing as dp
from app.training.pipeline import TrainPipeline


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Entraînement CatBoost multi-cible (P5)"
    )
    parser.add_argument(
        "--csv",
        default=str(dp.DEFAULT_DATASET_PATH),
        help="Chemin du CSV brut (défaut : data/2016_Building_Energy_Benchmarking.csv)",
    )
    parser.add_argument("--output-dir", default="models")
    parser.add_argument(
        "--download", action="store_true", help="Télécharge le dataset s'il est absent"
    )
    parser.add_argument(
        "--no-kumo", action="store_true", help="N'évalue pas le modèle Kumo"
    )
    parser.add_argument(
        "--cv-splits", type=int, default=5, help="Nombre de plis de validation croisée"
    )
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    try:
        csv_path = dp.ensure_dataset(args.csv, download=args.download)
    except (FileNotFoundError, RuntimeError) as exc:
        parser.error(str(exc))
        return
    pipe = TrainPipeline(
        csv_path=csv_path, output_dir=args.output_dir, cv_splits=args.cv_splits
    )
    metrics = pipe.run(include_kumo=not args.no_kumo)
    print(f"[done] scores: {metrics}")


if __name__ == "__main__":
    main()
