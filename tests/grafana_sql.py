"""Requêtes des tableaux de bord Grafana : extraction et rendu des macros.

Seules deux macros sont autorisées dans les panneaux (spec monitoring §4) ;
elles sont rendues ici par leur équivalent SQL pour exécuter les requêtes en
test, sous le rôle Grafana.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path

DASHBOARD_DIR = Path(__file__).resolve().parents[1] / "grafana/provisioning/dashboards"

_UNITS = {"m": 60, "h": 3600, "d": 86400}
_TIME_FILTER = re.compile(r"\$__timeFilter\(\s*([\w.]+)\s*\)")
_TIME_GROUP = re.compile(r"\$__timeGroupAlias\(\s*([\w.]+)\s*,\s*(\d+)([mhd])\s*\)")
_LEFTOVER = re.compile(r"\$\w+")


def load_dashboards() -> dict[str, dict]:
    """Tableaux de bord provisionnés, indexés par nom de fichier."""
    return {
        path.name: json.loads(path.read_text(encoding="utf-8"))
        for path in sorted(DASHBOARD_DIR.glob("*.json"))
    }


def iter_panels(dashboard: dict) -> Iterator[dict]:
    """Panneaux de données, y compris ceux repliés dans une ligne."""
    for panel in dashboard.get("panels", []):
        if panel.get("type") == "row":
            yield from panel.get("panels", [])
        else:
            yield panel


def iter_panel_queries(dashboard: dict) -> Iterator[tuple[str, str]]:
    """(titre du panneau, rawSql) de chaque cible."""
    for panel in iter_panels(dashboard):
        for target in panel.get("targets", []):
            yield panel["title"], target["rawSql"]


def render_macros(sql: str, start: datetime, end: datetime) -> str:
    """Remplace les macros Grafana ; toute autre macro ou variable est refusée."""

    def group(match: re.Match) -> str:
        column, n, unit = match.group(1), int(match.group(2)), match.group(3)
        seconds = n * _UNITS[unit]
        return (
            f"to_timestamp(floor(extract(epoch FROM {column}) / {seconds}) "
            f'* {seconds}) AS "time"'
        )

    out = _TIME_FILTER.sub(
        lambda m: f"{m.group(1)} BETWEEN '{start.isoformat()}' AND '{end.isoformat()}'",
        sql,
    )
    out = _TIME_GROUP.sub(group, out)
    leftover = _LEFTOVER.findall(out)
    if leftover:
        raise ValueError(f"Macro ou variable non prise en charge : {leftover}")
    return out
