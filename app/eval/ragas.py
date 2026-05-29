"""Custom RAGAS-style faithfulness CLI (EVAL-04).

Measures the hallucination rate of generated answers by:
1. Generating a live answer for each held-out golden tuple.
2. Decomposing the answer into atomic factual claims (Step 1: Claim Extraction).
3. Checking each claim against the retrieved source chunks (Step 2: Grounding Verification).
4. Computing faithfulness = supported_claims / total_claims per query.

Run it with::

    python -m app.eval.ragas
        [--held-out]          Score only the 5 held-out tuples (default)
        [--all]               Score all 22 tuples
        [--golden-set PATH]   Path to golden_set.jsonl (default: eval/golden_set.jsonl)
        [--runs-log PATH]     Path to faithfulness_runs.jsonl (default: eval/faithfulness_runs.jsonl)

Security constraints (CLAUDE.md / threat model):
    - No direct openai import — all embeddings go through get_embedder() (T-05-03).
    - Answer + claim text interpolated ONLY into user-role messages; system prompts
      are fixed and trusted (T-05-02 prompt-injection mitigation).
    - parse_claims returns [] and parse_support returns False on JSONDecodeError;
      total==0 → faithfulness 0.0, never 1.0 (T-05-08 spoofing mitigation).
    - eval/faithfulness_runs.jsonl is separate from eval/runs.jsonl (A2) so Plan 1's
      diff reader (which expects retrieval-shaped records) is never fed a faithfulness
      record.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

from anthropic import Anthropic, AsyncAnthropic

from app.db import get_conn
from app.embeddings.factory import get_embedder
from app.eval.schema import GoldenTuple, load_golden_set
from app.generation.generator import stream_response
from app.generation.prompt import build_messages, build_system_blocks
from app.retrieval.base import ChunkResult, retrieve


# ---------------------------------------------------------------------------
# Prompt constants
# Answer/claim text is ONLY placed in user-role messages — NEVER in the system
# prompt (T-05-02: prompt-injection boundary).
# ---------------------------------------------------------------------------

CLAIM_EXTRACT_SYSTEM = (
    "You are an information extraction assistant. "
    "Extract every factual claim from the text below as a JSON list of strings. "
    "Each claim must be a standalone declarative sentence. "
    "Return ONLY valid JSON: [\"claim1\", \"claim2\", ...]"
)

CLAIM_EXTRACT_USER = (
    "Extract all factual claims from this guitar tone recommendation:\n\n{answer}"
)

CLAIM_SUPPORT_SYSTEM = (
    "You are a grounding verifier. "
    "Given a claim and a set of source passages, determine if the claim is "
    "directly supported by the passages. "
    "Return JSON: {\"supported\": true} or {\"supported\": false}. "
    "A claim is supported only if the passage explicitly states or clearly implies it."
)

CLAIM_SUPPORT_USER = (
    "Claim: {claim}\n\n"
    "Source passages:\n{chunk_texts}\n\n"
    "Is this claim supported by the passages above?"
)


# ---------------------------------------------------------------------------
# Parse helpers
# ---------------------------------------------------------------------------


def parse_claims(response_text: str) -> list[str]:
    """Extract a JSON array of claims from LLM response text.

    Handles both bare JSON and markdown-fenced JSON. Returns [] on parse
    failure so a failed extraction cannot masquerade as perfect faithfulness
    (T-05-08 mitigation).

    Args:
        response_text: Raw LLM response string, possibly markdown-fenced.

    Returns:
        List of non-empty claim strings. Empty list on failure.
    """
    # Strip optional markdown code fence (```json ... ``` or ``` ... ```)
    cleaned = re.sub(
        r"^```(?:json)?\s*|\s*```$",
        "",
        response_text.strip(),
        flags=re.DOTALL,
    )
    try:
        result = json.loads(cleaned)
    except json.JSONDecodeError:
        # Fallback: extract first JSON array from anywhere in the text
        m = re.search(r"\[.*?\]", cleaned, re.DOTALL)
        if m:
            try:
                result = json.loads(m.group(0))
            except json.JSONDecodeError:
                return []
        else:
            return []
    if not isinstance(result, list):
        return []
    return [c for c in result if isinstance(c, str) and c.strip()]


def parse_support(response_text: str) -> bool:
    """Extract the boolean grounding verdict from an LLM response.

    Handles both bare JSON and markdown-fenced JSON. Returns False on parse
    failure so a failed extraction cannot masquerade as 'supported' (T-05-08).

    Args:
        response_text: Raw LLM response string, possibly markdown-fenced.

    Returns:
        True if the claim is supported; False otherwise or on parse failure.
    """
    cleaned = re.sub(
        r"^```(?:json)?\s*|\s*```$",
        "",
        response_text.strip(),
        flags=re.DOTALL,
    )
    try:
        result = json.loads(cleaned)
        return bool(result.get("supported", False))
    except (json.JSONDecodeError, AttributeError):
        # Text-scan fallback for slightly-malformed responses
        lower = response_text.lower()
        return '"supported": true' in lower or '"supported":true' in lower


# ---------------------------------------------------------------------------
# Faithfulness arithmetic
# ---------------------------------------------------------------------------


def faithfulness(supported: int, total: int) -> float:
    """Compute faithfulness score: supported_claims / total_claims.

    Returns 0.0 when total == 0 so an extraction failure cannot masquerade
    as perfect faithfulness (T-05-08 mitigation).

    Args:
        supported: Number of claims verified as grounded in source chunks.
        total:     Total number of extracted claims.

    Returns:
        Float in [0.0, 1.0].
    """
    if total == 0:
        return 0.0
    return supported / total


# ---------------------------------------------------------------------------
# Answer generation (async → sync bridge)
# ---------------------------------------------------------------------------


def generate_answer_sync(
    query: str,
    sources_with_ids: list,
) -> str:
    """Synchronously collect the full answer text from stream_response().

    Wraps the async generator in asyncio.run() so the sync RAGAS CLI can
    invoke it without a running event loop. A fresh AsyncAnthropic client is
    constructed inside the coroutine so its lifetime is bound to the event
    loop created by asyncio.run() — reusing a client across multiple
    asyncio.run() calls would orphan the httpx connection pool each time the
    loop closes (CR-01 fix).

    Args:
        query:            The user query for this golden tuple.
        sources_with_ids: List of (ChunkResult, sn) pairs from retrieve().

    Returns:
        Full response text concatenated from token events.
    """
    async def _run() -> str:
        async with AsyncAnthropic() as client:
            parts: list[str] = []
            async for sse in stream_response(
                client=client,
                system_blocks=build_system_blocks(),
                messages=build_messages([], query, sources_with_ids),
                sources_with_ids=sources_with_ids,
                session_id="eval-faithfulness",
            ):
                if sse.event is None:
                    payload = json.loads(sse.data)
                    if "text" in payload:
                        parts.append(payload["text"])
        return "".join(parts)

    return asyncio.run(_run())


# ---------------------------------------------------------------------------
# Tuple-level faithfulness scorer
# ---------------------------------------------------------------------------


def score_tuple_faithfulness(
    t: GoldenTuple,
    k: int = 8,
    conn=None,
    embedder=None,
    sync_client: Anthropic | None = None,
) -> dict:
    """Score faithfulness for one golden tuple.

    Steps:
    1. Retrieve top-k chunks for the tuple's query.
    2. Generate a live answer (AsyncAnthropic client is created internally
       per-call so its lifetime is scoped to each asyncio.run() event loop).
    3. Extract atomic claims from the answer via the sync client.
    4. Per claim, check grounding against the retrieved chunks.
    5. Return per-query dict with faithfulness score.

    Args:
        t:           GoldenTuple to evaluate.
        k:           Number of chunks to retrieve (default 8).
        conn:        Injected psycopg3 connection (None → get_conn()).
        embedder:    Injected Embedder (None → get_embedder()).
        sync_client: Anthropic sync instance for claim decomposition.

    Returns:
        Dict with keys: query, faithfulness, total_claims, supported_claims.
    """
    from app.config import get_settings

    chunks: list[ChunkResult] = retrieve(t.query, k=k, conn=conn, embedder=embedder)
    sources_with_ids = [(c, i + 1) for i, c in enumerate(chunks)]

    # Step 1: Generate live answer — AsyncAnthropic client created inside
    answer_text = generate_answer_sync(t.query, sources_with_ids)

    # Step 2: Extract claims — answer text goes ONLY into user-role message
    claim_resp = sync_client.messages.create(
        model=get_settings().anthropic_model,
        max_tokens=512,
        system=CLAIM_EXTRACT_SYSTEM,
        messages=[
            {
                "role": "user",
                "content": CLAIM_EXTRACT_USER.format(answer=answer_text),
            }
        ],
    )
    # Guard: content may be empty on API refusal or safety block (CR-02 fix)
    claim_text = claim_resp.content[0].text if claim_resp.content else ""
    claims = parse_claims(claim_text)

    # Step 3: Check each claim — claim text goes ONLY into user-role message
    chunk_texts = "\n---\n".join(c.text for c in chunks)
    supported_count = 0
    total_count = len(claims)

    for claim in claims:
        support_resp = sync_client.messages.create(
            model=get_settings().anthropic_model,
            max_tokens=64,
            system=CLAIM_SUPPORT_SYSTEM,
            messages=[
                {
                    "role": "user",
                    "content": CLAIM_SUPPORT_USER.format(
                        claim=claim,
                        chunk_texts=chunk_texts,
                    ),
                }
            ],
        )
        # Guard: content may be empty on API refusal or safety block (CR-02 fix)
        support_text = support_resp.content[0].text if support_resp.content else ""
        if parse_support(support_text):
            supported_count += 1

    return {
        "query": t.query,
        "faithfulness": faithfulness(supported_count, total_count),
        "total_claims": total_count,
        "supported_claims": supported_count,
    }


# ---------------------------------------------------------------------------
# faithfulness_runs.jsonl append helper
# ---------------------------------------------------------------------------


def append_faithfulness_run(path: Path, record: dict) -> None:
    """Append one faithfulness run record to path as a JSON line.

    Creates the file (and parent directories) if absent. Separate from
    eval/runs.jsonl so Plan 1's retrieval diff reader is not fed a
    faithfulness record (A2).

    Args:
        path:   Target file path (default: eval/faithfulness_runs.jsonl).
        record: Dict to serialize as one JSON line.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    """Build the argument parser for the faithfulness CLI."""
    p = argparse.ArgumentParser(
        prog="python -m app.eval.ragas",
        description=(
            "RAGAS-style faithfulness scorer: generates live answers for held-out "
            "golden tuples, decomposes answers into claims, checks each claim against "
            "retrieved chunks, and reports supported/total faithfulness per query."
        ),
    )
    p.add_argument(
        "--held-out",
        action="store_true",
        default=True,
        help="Score only the 5 held-out tuples (default)",
    )
    p.add_argument(
        "--all",
        dest="held_out",
        action="store_false",
        help="Score all 22 tuples (overrides --held-out)",
    )
    p.add_argument(
        "--golden-set",
        type=Path,
        default=Path("eval/golden_set.jsonl"),
        help="Path to golden_set.jsonl (default: eval/golden_set.jsonl)",
    )
    p.add_argument(
        "--runs-log",
        type=Path,
        default=Path("eval/faithfulness_runs.jsonl"),
        help=(
            "Path to faithfulness_runs.jsonl log (default: eval/faithfulness_runs.jsonl). "
            "Separate from eval/runs.jsonl (retrieval metrics)."
        ),
    )
    return p


def main(argv: list[str] | None = None) -> int:
    """CLI entry point for the faithfulness scorer.

    Args:
        argv: Command-line arguments (None → sys.argv).

    Returns:
        Exit code (0 = success, 1 = error).
    """
    from app.config import get_settings

    args = build_parser().parse_args(argv)

    # Fail-fast: construct embedder before opening DB connection
    try:
        embedder = get_embedder()
    except Exception as e:
        print(f"ERROR: Could not construct embedder: {e!r}", file=sys.stderr)
        return 1

    conn = get_conn()
    try:
        sync_client = Anthropic()

        tuples = load_golden_set(args.golden_set)
        if args.held_out:
            sample = [t for t in tuples if t.held_out]
            scope = "held_out"
        else:
            sample = tuples
            scope = "all"

        print(f"Scoring faithfulness for {len(sample)} tuples ({scope}) ...")
        print()

        per_query: list[dict] = []
        for t in sample:
            try:
                result = score_tuple_faithfulness(
                    t,
                    k=8,
                    conn=conn,
                    embedder=embedder,
                    sync_client=sync_client,
                )
            except Exception as e:
                print(
                    f"  ERROR scoring {t.query[:60]!r}: {e!r}",
                    file=sys.stderr,
                )
                result = {
                    "query": t.query,
                    "faithfulness": None,
                    "total_claims": None,
                    "supported_claims": None,
                    "error": repr(e),
                }
            per_query.append(result)

            # Print per-query line to stdout
            query_preview = t.query[:60] + "..." if len(t.query) > 60 else t.query
            if result.get("error"):
                print(f"  {query_preview!r}: ERROR — {result['error']}")
            else:
                print(
                    f"  {query_preview!r}: faithfulness={result['faithfulness']:.2f} "
                    f"({result['supported_claims']}/{result['total_claims']} claims supported)"
                )

        print()
        successful = [r for r in per_query if r.get("faithfulness") is not None]
        mean_faith = (
            sum(r["faithfulness"] for r in successful) / len(successful)
            if successful
            else 0.0
        )
        print(f"Mean faithfulness: {mean_faith:.2f} across {len(successful)} queries")

        settings = get_settings()
        record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "run_type": "faithfulness",
            "scope": scope,
            "sample_count": len(per_query),
            "mean_faithfulness": mean_faith,
            "per_query": per_query,
            "embedding_model": settings.embedding_model,
            "anthropic_model": settings.anthropic_model,
        }

        append_faithfulness_run(args.runs_log, record)
        print(f"Run appended to {args.runs_log}")
        return 0

    finally:
        try:
            conn.close()
        except Exception:
            pass


if __name__ == "__main__":  # pragma: no cover — invoked via python -m
    sys.exit(main())
