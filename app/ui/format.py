"""Mise en forme française des réponses de l'API pour l'interface."""

from __future__ import annotations

from typing import Any

MISSING = "—"
_NBSP = " "  # séparateur de milliers (espace insécable)


def fr_number(value: float | None, decimals: int = 0) -> str:
    """``3088219.81`` → ``3 088 220`` ; ``99.238`` (1 décimale) → ``99,2``."""
    if value is None:
        return MISSING
    text = f"{value:,.{decimals}f}"
    return text.replace(",", _NBSP).replace(".", ",")


def _text(value: Any) -> str:
    return MISSING if value in (None, "") else str(value)


def building_card(detail: dict) -> str:
    """Fiche Markdown d'un bâtiment (identité + dernière année disponible)."""
    year = detail["years"][-1] if detail.get("years") else {}
    surface = year.get("property_gfa_buildings")
    surface_text = MISSING if surface is None else f"{fr_number(surface)} pi²"
    location = " · ".join(
        _text(detail.get(key)) for key in ("address", "zip_code", "neighborhood")
    )
    usage = " · ".join(
        [
            f"**{_text(year.get('primary_property_type'))}**",
            f"construit en {_text(year.get('year_built'))}",
            surface_text,
        ]
    )
    return "\n".join([f"### {_text(detail.get('property_name'))}", location, "", usage])


def prediction_card(result: dict, label: str) -> str:
    """Bloc Markdown d'une prédiction (énergie, émissions, identifiant)."""
    return "\n".join(
        [
            f"**Énergie** : {fr_number(result.get('energy_use_kbtu'))} kBtu/an  ",
            f"**Émissions** : {fr_number(result.get('ghg_emissions_tco2e'), 1)} t CO2e/an  ",
            f"<small>{label} · prédiction n° {_text(result.get('prediction_id'))}</small>",
        ]
    )
