"""Tests unitaires de app.lib.tools."""

import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.lib import tools


def test_get_logger_is_stable_and_setup_logging_is_idempotent(monkeypatch):
    log1 = tools.get_logger("demo")
    log2 = tools.get_logger("demo")
    assert log1 is log2

    root = logging.getLogger()
    saved_handlers = root.handlers[:]
    root.handlers = []
    monkeypatch.setattr(tools, "_configured", False)
    try:
        tools.setup_logging()
        tools.setup_logging()
        tools.get_logger("demo")
        assert len(root.handlers) == 1
    finally:
        root.handlers = saved_handlers


def test_sanitize_metric_key_replaces_percent():
    assert tools.sanitize_metric_key("MedAPE_%") == "MedAPE_pct"


def test_ensure_dir_and_json_roundtrip(tmp_path):
    d = tools.ensure_dir(tmp_path / "a" / "b")
    assert d.is_dir()
    p = d / "x.json"
    tools.save_json(p, {"a": 1, "b": "é"})
    assert tools.load_json(p) == {"a": 1, "b": "é"}
    assert json.loads(p.read_text(encoding="utf-8"))["a"] == 1


def test_metrics_reelles_values():
    y_true = [100.0, 200.0, 300.0]
    y_pred = [110.0, 180.0, 330.0]
    m = tools.metrics_reelles(y_true, y_pred)
    assert set(m) == {"R2", "MAE", "MedAE", "MedAPE_%"}
    assert m["MAE"] == 20.0
    assert m["MedAE"] == 20.0
    assert m["MedAPE_%"] > 0


def test_timed_and_log_calls_decorators_return_value():
    @tools.timed("add")
    @tools.log_calls
    def add(a, b):
        return a + b

    assert add(2, 3) == 5
