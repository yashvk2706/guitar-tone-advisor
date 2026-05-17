"""Unit tests for ``app.eval.schema``.

Locks D-08 (JSONL schema), D-09 (fixed theme enum), and the
``load_golden_set`` / ``save_golden_set`` round-trip contract.

These tests are pure Python — no DB, no network. They run in every
environment.
"""

from __future__ import annotations

import json
import uuid

import pytest
from pydantic import ValidationError

from app.eval.schema import (
    VALID_THEMES,
    GoldenTuple,
    load_golden_set,
    save_golden_set,
)


# A handful of valid UUIDs, frozen here so the fixtures are deterministic.
_UUID_A = str(uuid.UUID("11111111-1111-1111-1111-111111111111"))
_UUID_B = str(uuid.UUID("22222222-2222-2222-2222-222222222222"))
_UUID_C = str(uuid.UUID("33333333-3333-3333-3333-333333333333"))


def _good_tuple(**overrides) -> dict:
    """Return a baseline dict that constructs a valid ``GoldenTuple``."""
    base = {
        "query": "What amp settings does BB King prefer?",
        "expected_chunk_ids": [_UUID_A],
        "expected_themes": ["amp_settings"],
        "held_out": False,
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# Test 1: round-trip a valid tuple through dict.
# ---------------------------------------------------------------------------


def test_valid_tuple_round_trips():
    t = GoldenTuple(**_good_tuple())
    again = GoldenTuple(**t.model_dump())
    assert again == t


# ---------------------------------------------------------------------------
# Test 2: an empty expected_chunk_ids list is rejected.
# ---------------------------------------------------------------------------


def test_empty_chunk_ids_rejected():
    with pytest.raises(ValidationError):
        GoldenTuple(**_good_tuple(expected_chunk_ids=[]))


# ---------------------------------------------------------------------------
# Test 3: a malformed UUID in expected_chunk_ids is rejected.
# ---------------------------------------------------------------------------


def test_invalid_uuid_rejected():
    with pytest.raises(ValidationError):
        GoldenTuple(**_good_tuple(expected_chunk_ids=["not-a-uuid"]))


# ---------------------------------------------------------------------------
# Test 4: a theme outside VALID_THEMES is rejected (Literal enforces enum).
# ---------------------------------------------------------------------------


def test_invalid_theme_rejected():
    with pytest.raises(ValidationError):
        GoldenTuple(**_good_tuple(expected_themes=["whammy_bar"]))


# ---------------------------------------------------------------------------
# Test 5: an empty query string is rejected.
# ---------------------------------------------------------------------------


def test_empty_query_rejected():
    with pytest.raises(ValidationError):
        GoldenTuple(**_good_tuple(query=""))


# ---------------------------------------------------------------------------
# Test 6: a query over 300 characters is rejected.
# ---------------------------------------------------------------------------


def test_query_over_300_chars_rejected():
    with pytest.raises(ValidationError):
        GoldenTuple(**_good_tuple(query="x" * 301))


# ---------------------------------------------------------------------------
# Test 7: save → load round-trip preserves order and content.
# ---------------------------------------------------------------------------


def test_jsonl_round_trip(tmp_path):
    t1 = GoldenTuple(**_good_tuple())
    t2 = GoldenTuple(
        **_good_tuple(
            query="Best overdrive for John Mayer blues?",
            expected_chunk_ids=[_UUID_B, _UUID_C],
            expected_themes=["pedal_choice", "signal_chain"],
            held_out=True,
        )
    )
    t3 = GoldenTuple(
        **_good_tuple(
            query="Funk pickup choice — neck or bridge?",
            expected_chunk_ids=[_UUID_C],
            expected_themes=["pickup_tone"],
        )
    )

    out_path = tmp_path / "g.jsonl"
    save_golden_set([t1, t2, t3], out_path)

    # File is exactly 3 lines, each line valid JSON.
    raw = out_path.read_text(encoding="utf-8")
    lines = [line for line in raw.splitlines() if line.strip()]
    assert len(lines) == 3
    for line in lines:
        json.loads(line)  # must not raise

    # And the round-trip is equality-preserving in order.
    loaded = load_golden_set(out_path)
    assert loaded == [t1, t2, t3]


# ---------------------------------------------------------------------------
# Test 8: a malformed JSONL line is reported with its 1-based line number.
# ---------------------------------------------------------------------------


def test_jsonl_malformed_line_reports_line_number(tmp_path):
    good_line = json.dumps(
        {
            "query": "What amp for blues?",
            "expected_chunk_ids": [_UUID_A],
            "expected_themes": ["amp_settings"],
            "held_out": False,
        }
    )
    bad_line = "{this is not valid json"

    path = tmp_path / "bad.jsonl"
    path.write_text(f"{good_line}\n{bad_line}\n", encoding="utf-8")

    with pytest.raises(ValueError) as exc:
        load_golden_set(path)

    # The error message MUST identify the offending 1-based line number.
    msg = str(exc.value)
    assert "line 2" in msg
    assert "Malformed JSONL" in msg


# ---------------------------------------------------------------------------
# Bonus: VALID_THEMES is the locked enum content (D-09).
# ---------------------------------------------------------------------------


def test_valid_themes_is_the_locked_enum():
    assert VALID_THEMES == (
        "amp_settings",
        "pedal_choice",
        "signal_chain",
        "pickup_tone",
        "studio_vs_live",
    )
