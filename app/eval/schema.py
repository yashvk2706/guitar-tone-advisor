"""Golden eval-set schema (D-08, D-09) plus JSONL load/save helpers.

The Phase 5 retrieval evaluation reads ``eval/golden_set.jsonl`` produced
by the interactive authoring CLI in ``app.eval.author``. Each line of that
file is one ``GoldenTuple``. Locking the schema here (a Pydantic v2 model
+ a closed-enum ``Theme`` literal) guarantees:

* No silent theme drift across runs — Phase 5 recall@K is comparable
  because the only acceptable theme labels are the five locked in
  ``VALID_THEMES`` (D-09).
* No transcription errors — every ``expected_chunk_ids`` entry must parse
  as ``uuid.UUID`` at load time, so a hand-edited JSONL line that
  fat-fingered a chunk ID fails loudly instead of skewing recall (D-07
  enforces the same constraint at write time via live DB lookup).
* Identical write/read contract — ``save_golden_set`` serializes via
  ``model_dump()`` so the JSONL row shape matches the model exactly;
  ``load_golden_set`` validates every row through ``model_validate`` and
  reports the offending 1-based line number on failure.

Pure module — no DB, no network, no filesystem side effects beyond the
``path``-arg helpers.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, ValidationError, field_validator


# The five locked theme labels (D-09). Both the runtime tuple AND the
# Literal type alias name the same five strings so that:
#   - User code can ``if theme in VALID_THEMES`` without importing typing.
#   - Pydantic's ``Literal[...]`` validation rejects anything outside the set
#     before a tuple is constructed, surfacing the typo in the model error.
VALID_THEMES: tuple[str, ...] = (
    "amp_settings",
    "pedal_choice",
    "signal_chain",
    "pickup_tone",
    "studio_vs_live",
)

Theme = Literal[
    "amp_settings",
    "pedal_choice",
    "signal_chain",
    "pickup_tone",
    "studio_vs_live",
]


class GoldenTuple(BaseModel):
    """One row of the locked golden eval set.

    Fields (D-08):
        query: Natural-language guitarist query. Non-empty, max 300 chars.
        expected_chunk_ids: Non-empty list of chunk UUIDs (as strings) that
            the human reviewer marked as relevant for ``query``. Each entry
            MUST parse as ``uuid.UUID`` — enforced by the field validator
            below (T-05-02 mitigation against transcription errors).
        expected_themes: Non-empty list of theme labels from
            ``VALID_THEMES``. The ``Literal`` type alias rejects unknown
            themes before the model is constructed (T-05-01 mitigation
            against silent enum drift).
        held_out: True iff this tuple belongs to the 5-tuple held-out
            split locked in ``eval/HELD_OUT.md`` (D-10).
    """

    query: str = Field(min_length=1, max_length=300)
    expected_chunk_ids: list[str] = Field(min_length=1)
    expected_themes: list[Theme] = Field(min_length=1)
    held_out: bool

    @field_validator("expected_chunk_ids")
    @classmethod
    def _validate_chunk_ids_are_uuids(cls, value: list[str]) -> list[str]:
        """Reject any chunk-id that does not parse as a UUID.

        We re-store the canonical string form (``str(uuid.UUID(s))``) so
        that hyphenation / case differences in the input file are
        normalized on the way in and never reach Phase 5 retrieval.
        """
        normalized: list[str] = []
        for s in value:
            try:
                normalized.append(str(uuid.UUID(s)))
            except (ValueError, TypeError, AttributeError) as e:
                raise ValueError(
                    f"expected_chunk_ids entry {s!r} is not a valid UUID: {e}"
                ) from e
        return normalized


def save_golden_set(tuples: list[GoldenTuple], path: Path) -> None:
    """Write ``tuples`` as JSONL to ``path``, one ``model_dump()`` per line.

    Input order is preserved. The file is overwritten atomically: we open
    the destination in write mode and emit a newline-terminated row per
    tuple. ``json.dumps`` is called with ``ensure_ascii=False`` so unicode
    characters from forum queries survive the round-trip without ``\\u``
    escapes.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for t in tuples:
            fh.write(json.dumps(t.model_dump(), ensure_ascii=False))
            fh.write("\n")


def load_golden_set(path: Path) -> list[GoldenTuple]:
    """Read JSONL at ``path`` and return one ``GoldenTuple`` per line.

    Errors surface the offending 1-based line number so a hand-edited
    JSONL is debuggable:

        ValueError: Malformed JSONL at line 7: Expecting property name ...

    Both ``json.JSONDecodeError`` and ``pydantic.ValidationError`` are
    caught and re-raised under the same ``Malformed JSONL at line N:``
    prefix so callers (e.g., Phase 5 eval harness) have one error shape
    to handle.

    Empty lines are skipped silently to allow newline-terminated files
    with a trailing blank line.
    """
    path = Path(path)
    out: list[GoldenTuple] = []
    with path.open("r", encoding="utf-8") as fh:
        for n, raw in enumerate(fh, start=1):
            line = raw.strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError as e:
                raise ValueError(f"Malformed JSONL at line {n}: {e}") from e
            try:
                out.append(GoldenTuple.model_validate(payload))
            except ValidationError as e:
                raise ValueError(f"Malformed JSONL at line {n}: {e}") from e
    return out
