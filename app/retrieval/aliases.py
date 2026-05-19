"""Gear alias query expansion for the retrieval layer.

Loads a static corpus-grounded alias map (``data/gear_aliases.json``) once at
first call (``lru_cache``) and applies bidirectional word-boundary expansion to
user queries before they are embedded.

Example:
    >>> expand_query("Strat clean tone", [("Strat", "Stratocaster")])
    'Strat Stratocaster clean tone'
    >>> expand_query("Stratocaster clean tone", [("Strat", "Stratocaster")])
    'Strat Stratocaster clean tone'

No external imports — stdlib only. This module must NEVER import ``openai``,
``psycopg``, or any non-stdlib package (CLAUDE.md constraint).
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

# app/retrieval/aliases.py is at <root>/app/retrieval/aliases.py.
# Three .parent hops: aliases.py → retrieval/ → app/ → <root>
_ALIASES_PATH = (
    Path(__file__).resolve().parent.parent.parent / "data" / "gear_aliases.json"
)


@lru_cache(maxsize=1)
def _load_alias_pairs() -> list[tuple[str, str]]:
    """Load alias pairs once at first call; cached for process lifetime.

    Tests that need to override aliases must call ``_load_alias_pairs.cache_clear()``
    — same convention as ``get_settings.cache_clear()`` in test_embedder_protocol.py.

    Returns:
        List of ``(shortform, canonical)`` string tuples — 14 pairs for the
        Phase 2 corpus.
    """
    data = json.loads(_ALIASES_PATH.read_text(encoding="utf-8"))
    return [(entry["shortform"], entry["canonical"]) for entry in data["aliases"]]


def expand_query(
    query: str,
    alias_pairs: list[tuple[str, str]] | None = None,
) -> str:
    """Apply bidirectional alias expansion to a query string.

    Each ``(shortform, canonical)`` pair generates two expansion rules:

    * ``shortform`` → ``"shortform canonical"``
      (e.g. ``"Strat"`` → ``"Strat Stratocaster"``)
    * ``canonical`` → ``"shortform canonical"``
      (e.g. ``"Stratocaster"`` → ``"Strat Stratocaster"``)

    Word-boundary matching (``\\b``) prevents ``"Strat"`` from expanding inside
    ``"Stratocaster"``.  ``count=1`` prevents duplicate expansion when the same
    token appears multiple times in the query.

    Per RESEARCH.md Pitfall 6: the query is whitespace-normalised before
    expansion so multi-word canonicals (e.g. ``"Dumble Steel String Slinger"``)
    are matched reliably regardless of extra spaces.

    Args:
        query:       Raw user query string.
        alias_pairs: Override for testing; defaults to ``_load_alias_pairs()``.
                     Pass ``[]`` (empty list) to skip all expansion.

    Returns:
        Expanded query string with both shortform and canonical tokens present
        for any alias that matched.
    """
    pairs = alias_pairs if alias_pairs is not None else _load_alias_pairs()

    # Normalise whitespace so multi-word canonicals match reliably (Pitfall 6).
    result = " ".join(query.split())

    for shortform, canonical in pairs:
        replacement = f"{shortform} {canonical}"

        # Check canonical presence BEFORE trying the shortform rule.
        # For 6 of 14 pairs the shortform is a standalone word inside the
        # canonical (e.g. "5150" inside "Peavey 5150", "SLO" inside
        # "Soldano SLO-100"). If we tried the shortform rule first, \b5150\b
        # would match the "5150" in "Peavey 5150" and produce a doubled token
        # ("Peavey 5150 Peavey 5150") before the canonical rule could fire.
        if re.search(rf"\b{re.escape(canonical)}\b", result, re.IGNORECASE):
            # Canonical already present — normalise to "shortform canonical".
            result = re.sub(
                rf"\b{re.escape(canonical)}\b",
                replacement,
                result,
                count=1,
                flags=re.IGNORECASE,
            )
        else:
            # Canonical absent — try shortform → "shortform canonical".
            result = re.sub(
                rf"\b{re.escape(shortform)}\b",
                replacement,
                result,
                count=1,
                flags=re.IGNORECASE,
            )

    return result
