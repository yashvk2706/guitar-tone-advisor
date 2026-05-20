"""Prompt construction for grounded generation.

Pure-function module — no external API calls, fully offline-testable.

Exports:
    SYSTEM_PROMPT_TEXT  — system prompt constant enforcing three grounding rules
    build_system_blocks — wraps system prompt in TextBlockParam with cache_control
    build_sources_xml   — formats list[ChunkResult] into <sources> XML
    build_messages      — builds the anthropic messages list for one turn

Security constraints (CLAUDE.md):
    - No direct openai import.
    - No DB access — pure transform only.
    - System prompt is stable across all turns (D-11: gear lives in first user
      message, not the system prompt), enabling prompt caching.
"""

from __future__ import annotations

from app.retrieval.base import ChunkResult


# ---------------------------------------------------------------------------
# System prompt — enforces all three grounding rules from D-13
# ---------------------------------------------------------------------------

SYSTEM_PROMPT_TEXT = """You are a guitar tone advisor. You help a guitarist achieve specific sounds
by giving concrete, actionable recommendations: amp channel selection, EQ settings
(bass/mid/treble values 0–10), gain/drive levels, pedal selection and order,
guitar pickup selection, and playing technique notes.

GROUNDING RULES (non-negotiable):
1. Every concrete recommendation (specific gear, specific setting, specific technique)
   must be supported by at least one passage from <sources>. cite it inline as [Sn]
   where n is the source number.
2. When the corpus lacks material for a query, refuse plainly:
   "I don't have material on [X] — the closest I have is [Y], want that instead?"
   Do NOT fabricate recommendations.
3. Never cite a source not in the <sources> block. n in [Sn] must be 1 ≤ n ≤ N
   where N is the total number of sources provided.
4. When sources conflict, surface the disagreement: "Source [S1] suggests X,
   [S3] suggests Y — the difference is..."
5. The user's gear context is in the first user message in a <gear> block.
   Trust it for the whole conversation. Do not ask for gear again.

GEAR TRANSLATION:
When the user's gear differs from gear mentioned in sources, apply gear translation:
map settings from the source gear to the user's equivalent. Explain the translation
briefly (e.g., "the Vox AC30 equivalent would be...").

FORMAT:
- Lead with a 1-2 sentence "what you're going for" summary.
- Bulleted signal-chain recommendation: Guitar → pedals (in order) → amp.
- Specific EQ settings as a compact list (e.g., Bass=7 Mid=4 Treble=6).
- Inline citations throughout — e.g., "Set gain around 4 [S2]".
- End with one "things to try / vary" sentence.
"""


# ---------------------------------------------------------------------------
# Public functions
# ---------------------------------------------------------------------------


def build_system_blocks() -> list[dict]:
    """Return the system prompt as a list of TextBlockParam with cache_control.

    The system prompt is stable across all turns in a session — gear lives in
    the first user message (D-11), so this function always returns the same
    value regardless of which turn is being processed.

    Returns:
        list of one TextBlockParam dict with ``cache_control: {"type": "ephemeral"}``
        for Anthropic prompt caching (D-04).
    """
    return [
        {
            "type": "text",
            "text": SYSTEM_PROMPT_TEXT,
            "cache_control": {"type": "ephemeral"},
        }
    ]


def build_sources_xml(sources: list[ChunkResult]) -> str:
    """Format retrieved chunks as a <sources> XML block for injection into the user message.

    Session-local IDs S1..Sn are assigned per request (D-14). The model uses
    these IDs for inline citations [Sn]. An empty sources list returns the
    minimal <sources> wrapper to signal the refusal path to the model.

    Args:
        sources: The list of ChunkResult objects returned by retrieve() for
                 this turn. May be empty (corpus-silent query).

    Returns:
        XML string of the form:
        ``<sources>\\n  <source id="S1" type="..." name="...">text</source>\\n</sources>``
        For an empty list: ``"<sources>\\n</sources>"``.
    """
    if not sources:
        return "<sources>\n</sources>"

    parts = ["<sources>"]
    for i, chunk in enumerate(sources, start=1):
        parts.append(
            f'  <source id="S{i}" type="{chunk.source_type}" name="{chunk.source_name}">'
        )
        parts.append(f"    {chunk.text}")
        parts.append("  </source>")
    parts.append("</sources>")
    return "\n".join(parts)


def build_messages(
    turns: list[dict],
    user_message: str,
    sources: list[ChunkResult],
) -> list[dict]:
    """Build the anthropic messages array for one turn.

    Prior turns in the session history are included verbatim (they already
    contain embedded <sources> XML from prior requests — the model can see
    them for context). The current user turn injects a fresh <sources> block
    before the user's actual question.

    Args:
        turns:        Prior conversation turns — list of
                      ``{"role": "user"|"assistant", "content": str}`` dicts.
                      Pass ``[]`` on the first turn.
        user_message: The user's raw message text for this turn.
        sources:      Retrieved ChunkResult objects for this turn. May be empty.

    Returns:
        A list of MessageParam dicts ready to pass as ``messages=`` to the
        Anthropic SDK. Length is ``len(turns) + 1`` (one new user turn appended).
    """
    messages = list(turns)  # copy — do not mutate caller's history
    sources_xml = build_sources_xml(sources)
    messages.append(
        {
            "role": "user",
            "content": f"{sources_xml}\n\n{user_message}",
        }
    )
    return messages
