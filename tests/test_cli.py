"""Tests du CLI d'entraînement (app.training.__main__)."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.training import __main__ as cli


def test_build_parser_defaults():
    args = cli.build_parser().parse_args([])
    assert args.output_dir == "models"
    assert args.cv_splits == 5
    assert args.download is False
    assert args.no_kumo is False


def test_build_parser_overrides():
    args = cli.build_parser().parse_args(
        [
            "--csv",
            "x.csv",
            "--output-dir",
            "out",
            "--download",
            "--no-kumo",
            "--cv-splits",
            "3",
        ]
    )
    assert args.csv == "x.csv"
    assert args.output_dir == "out"
    assert args.download is True
    assert args.no_kumo is True
    assert args.cv_splits == 3


def test_main_missing_dataset_exits(tmp_path, monkeypatch):
    monkeypatch.setattr(
        sys, "argv", ["app.training", "--csv", str(tmp_path / "nope.csv")]
    )
    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 2
