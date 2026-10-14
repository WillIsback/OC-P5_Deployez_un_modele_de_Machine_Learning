"""Parsing et masquage des corps HTTP avant stockage dans `api_requests`."""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import parse_qsl

SECRET_KEYS = frozenset({"password", "access_token", "client_secret"})
MASK = "***"
MAX_TRACE_BYTES = 65536


def redact(value: Any) -> Any:
    """Remplace récursivement les valeurs des clés sensibles par ``MASK``."""
    if isinstance(value, dict):
        return {
            k: MASK if isinstance(k, str) and k.lower() in SECRET_KEYS else redact(v)
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [redact(v) for v in value]
    return value


def _sanitize(value: Any) -> Any:
    """Remplace récursivement le caractère nul (refusé par JSONB) par U+FFFD."""
    if isinstance(value, str):
        return value.replace("\x00", "�")
    if isinstance(value, dict):
        return {_sanitize(k): _sanitize(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_sanitize(v) for v in value]
    return value


def _raw_marker(body: bytes) -> dict[str, str]:
    return {"_raw": f"<non-JSON, {len(body)} octets>"}


def parse_body(body: bytes, content_type: str | None) -> Any | None:
    """Corps HTTP → valeur JSON-sérialisable (ou marqueur ``_raw``)."""
    if not body:
        return None
    if len(body) > MAX_TRACE_BYTES:
        return {"_raw": f"<tronqué, {len(body)} octets>"}
    # JSONB refuse le caractère nul : on ne tente pas de le stocker.
    if b"\\u0000" in body:
        return _raw_marker(body)
    ctype = (content_type or "").split(";")[0].strip().lower()
    try:
        if ctype == "application/x-www-form-urlencoded":
            text = body.decode("utf-8", errors="strict")
            return _sanitize(
                dict(parse_qsl(text, keep_blank_values=True, errors="strict"))
            )
        if ctype == "application/json" or ctype.endswith("+json"):
            return _sanitize(json.loads(body))
    except (UnicodeDecodeError, ValueError):
        pass
    return _raw_marker(body)


def to_trace(body: bytes, content_type: str | None) -> Any | None:
    """Corps HTTP → valeur masquée, prête à être stockée en JSONB."""
    return redact(parse_body(body, content_type))
