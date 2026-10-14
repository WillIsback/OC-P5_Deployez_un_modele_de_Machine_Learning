"""Tests du masquage des secrets dans les traces."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db.redaction import MAX_TRACE_BYTES, parse_body, redact, to_trace

FORM = "application/x-www-form-urlencoded"
JSON = "application/json"


def test_token_form_password_masked():
    body = b"grant_type=password&username=johndoe&password=secret"
    assert to_trace(body, FORM) == {
        "grant_type": "password",
        "username": "johndoe",
        "password": "***",
    }


def test_nested_and_case_insensitive_keys_masked():
    value = {"a": [{"Access_Token": "x"}], "client_secret": "y", "keep": 1}
    assert redact(value) == {
        "a": [{"Access_Token": "***"}],
        "client_secret": "***",
        "keep": 1,
    }


def test_json_with_charset_parsed():
    assert to_trace(b'{"building_id": 1}', "application/json; charset=utf-8") == {
        "building_id": 1
    }


def test_empty_body_is_none():
    assert parse_body(b"", JSON) is None


def test_invalid_json_stored_as_raw_marker():
    assert parse_body(b"{not json", JSON) == {"_raw": "<non-JSON, 9 octets>"}


def test_binary_body_stored_as_raw_marker():
    assert parse_body(b"\xff\xfe\x00", "application/octet-stream") == {
        "_raw": "<non-JSON, 3 octets>"
    }


def test_non_utf8_form_stored_as_raw_marker():
    assert parse_body(b"password=\xff", FORM) == {"_raw": "<non-JSON, 10 octets>"}


def test_null_char_rejected_by_jsonb_stored_as_raw_marker():
    body = json.dumps({"x": "a\u0000b"}).encode()
    assert parse_body(body, JSON) == {"_raw": f"<non-JSON, {len(body)} octets>"}


def test_oversized_body_truncated_marker():
    body = b"{" + b" " * MAX_TRACE_BYTES + b"}"
    assert parse_body(body, JSON) == {"_raw": f"<tronqué, {len(body)} octets>"}


def test_form_null_char_replaced_and_password_masked():
    trace = to_trace(b"a=%00&password=x&k%00=v", FORM)
    assert trace == {"a": "�", "password": "***", "k�": "v"}
    assert "\x00" not in json.dumps(trace, ensure_ascii=False)


def test_no_null_char_survives_any_path():
    # Octet nul brut dans un JSON : refusé par le parseur → marqueur sans \x00.
    for body, ctype in [
        (b'{"x": "a\x00b"}', JSON),
        (b'{"x": "a\\u0000b"}', JSON),
        (b"\x00", "text/plain"),
        (b"a=%00", FORM),
    ]:
        assert "\x00" not in json.dumps(to_trace(body, ctype), ensure_ascii=False)
