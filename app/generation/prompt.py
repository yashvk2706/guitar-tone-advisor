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

import re
from xml.sax.saxutils import escape, quoteattr

# Strips <sources>...</sources> blocks (including trailing newline) from prior
# user turns so stale S{n} IDs don't bleed into the current turn's context.
_SOURCES_BLOCK_RE = re.compile(r"<sources>.*?</sources>\n*", re.DOTALL)

from app.retrieval.base import ChunkResult


# ---------------------------------------------------------------------------
# System prompt — enforces all three grounding rules from D-13
# ---------------------------------------------------------------------------

SYSTEM_PROMPT_TEXT = """You are a guitar tone advisor. You help a guitarist achieve specific sounds
by giving concrete, actionable recommendations: amp channel selection, EQ settings
(bass/mid/treble values 0–10), gain/drive levels, pedal selection and order,
guitar pickup selection, and playing technique notes.

GROUNDING RULES (non-negotiable):
1. Every concrete recommendation (specific gear name, specific numeric setting,
   specific technique) must appear verbatim or near-verbatim in a cited <sources>
   passage. Cite it inline as [Sn]. Do NOT state a specific value (e.g. "Bass=7",
   "gain around 4", "use a TS-style pedal") unless that value is explicitly present
   in the cited chunk — not merely implied by the topic of the chunk.
2. When the corpus lacks material for a query, refuse plainly:
   "I don't have material on [X] — the closest I have is [Y], want that instead?"
   Do NOT fabricate recommendations or fill gaps with general knowledge.
3. Never cite a source not in the <sources> block. n in [Sn] must be 1 ≤ n ≤ N
   where N is the total number of sources provided.
   Source IDs are LOCAL to each response — [S3] in a prior assistant turn
   refers to a completely different chunk than [S3] in the current turn.
   Never interpret, reference, or comment on source IDs from your own prior responses.
4. When sources conflict, surface the disagreement: "Source [S1] suggests X,
   [S3] suggests Y — the difference is..."
5. The user's gear context is in the first user message in a <gear> block.
   Trust it for the whole conversation. Do not ask for gear again.

GEAR TRANSLATION:
When the user's gear differs from gear mentioned in sources, you may suggest an
approximate equivalent — but you MUST label it explicitly as an estimate:
e.g., "the source specifies a Vox AC30 [S2]; on your Fender, an approximate
starting point would be Bass=6, but treat this as an estimate, not a sourced value."
Never present a translated setting as a sourced fact.

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


def build_sources_xml(sources_with_ids: list[tuple[ChunkResult, int]]) -> str:
    """Format retrieved chunks as a <sources> XML block using session-stable IDs.

    Args:
        sources_with_ids: List of (ChunkResult, assigned_sn) pairs from
                          ``session.register_sources()``. The integer is the
                          session-global S-number for that chunk — stable across
                          all turns in the session.

    Returns:
        XML string of the form:
        ``<sources>\\n  <source id="S3" type="..." name="...">text</source>\\n</sources>``
        For an empty list: ``"<sources>\\n</sources>"``.
    """
    if not sources_with_ids:
        return "<sources>\n</sources>"

    parts = ["<sources>"]
    for chunk, sn in sources_with_ids:
        parts.append(
            f"  <source id=\"S{sn}\" type={quoteattr(chunk.source_type)} name={quoteattr(chunk.source_name)}>"
        )
        parts.append(f"    {escape(chunk.text)}")
        parts.append("  </source>")
    parts.append("</sources>")
    return "\n".join(parts)


def build_messages(
    turns: list[dict],
    user_message: str,
    sources_with_ids: list[tuple[ChunkResult, int]],
) -> list[dict]:
    """Build the anthropic messages array for one turn.

    Prior user turns have their <sources> XML stripped — those blocks used
    session-global S-numbers that are stable, but carrying full chunk text
    forward bloats the prompt without adding value (the assistant already cited
    what mattered). The current turn injects a fresh <sources> block with the
    same stable S-numbers so the model can look up any chunk it references.

    Args:
        turns:            Prior conversation turns (user + assistant dicts).
                          Pass ``[]`` on the first turn.
        user_message:     The user's raw message for this turn.
        sources_with_ids: (ChunkResult, assigned_sn) pairs from
                          ``session.register_sources()`` for this turn.

    Returns:
        Anthropic MessageParam list, length ``len(turns) + 1``.
    """
    messages = []
    for turn in turns:
        if turn["role"] == "user":
            clean = _SOURCES_BLOCK_RE.sub("", turn["content"]).lstrip()
            messages.append({"role": "user", "content": clean})
        else:
            messages.append(dict(turn))

    sources_xml = build_sources_xml(sources_with_ids)
    messages.append(
        {
            "role": "user",
            "content": f"{sources_xml}\n\n{user_message}",
        }
    )
    return messages
