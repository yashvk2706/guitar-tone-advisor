# Guitar Tone Advisor

## What This Is

A personal conversational web app that helps a guitarist identify how to achieve specific sounds. The user describes their current gear and a target tone (an artist's sound, a genre, a feeling), and the AI responds with grounded, citation-backed recommendations — specific amp settings, pedal choices, signal chain order, and knob positions — drawn entirely from a hand-curated corpus of forum discussions, equipment manuals, Premier Guitar articles, and YouTube video transcripts.

## Core Value

Given a user's gear and a target tone, produce concrete, cited settings recommendations they can immediately act on — no vague advice, no hallucinated gear.

## Requirements

### Validated

- [x] Embeddings are generated and stored in pgvector via the configurable embedding model — *Validated in Phase 1: Schema, Forum Ingestion & Golden Eval Set*
- [x] Corpus ingestion pipeline processes forum posts (Phase 1 source type) — *Validated in Phase 1*
- [x] RAG retrieval fetches relevant passages given a tone query — *Validated in Phase 2: Retrieval Layer & Gear Aliases*
- [x] Embedding model is configurable via environment variable without code changes — *Validated in Phase 1/2 (EMBEDDING_MODEL env var + Embedder Protocol)*

### Active

- [ ] Corpus ingestion pipeline processes all four source types (forum posts, PDF manuals, scraped articles, YouTube transcripts)
- [ ] Embeddings are generated and stored in pgvector via the configurable embedding model
- [ ] RAG retrieval fetches relevant passages given a tone query
- [ ] Conversational chat UI lets user describe gear + target tone
- [ ] AI response cites which source passages informed each recommendation
- [ ] Per-session conversation history maintained (cleared on new chat)
- [ ] Embedding model is configurable via environment variable without code changes
- [ ] FastAPI backend serves chat and retrieval endpoints
- [ ] Next.js frontend renders chat interface with citation display

### Out of Scope

- Persistent user accounts or saved chats — personal tool, single session only
- Gear inventory database / persistent gear profile — user describes gear per session
- Multi-user / authentication — not needed for personal tool
- LangChain or LlamaIndex — building pipeline from scratch for full control
- Mobile app — web-first
- External hosting / deployment — runs fully local
- Audio analysis or MIDI integration — text-only for v1
- Real-time collaboration — single-user

## Context

**Existing corpus in `raw_data/`:**

- `forum_posts/` — 10 curated forum Q&A discussions on specific artist tones (BB King, EVH, John Mayer, Mark Knopfler, etc.) and genre tones (funk, lo-fi, neo-soul, pop-punk, Indian-sounding, unconventional)
- `manuals/` — 15 amp and pedal PDF manuals: Marshall JCM800, JTM45; Fender Deluxe Reverb, Twin Reverb; Vox AC30; Mesa Boogie Mark V; Orange Rockerverb 50; Blackstar HT5; Boss BD-2, DD-3, DS-1; Electro-Harmonix Big Muff; Ibanez TS9; MXR Phase 90; Strymon BlueSky
- `article_urls.txt` — 10 Premier Guitar article URLs covering tone, gear, mods
- `youtube_ids.txt` — 13 YouTube video IDs on artist/genre tones

**Architecture intent:** Ingestion pipeline (offline, run once) → PostgreSQL/pgvector chunk store → Python retrieval layer → FastAPI chat API → Next.js chat UI. No framework abstractions in the retrieval layer — chunking, embedding generation, and similarity search are all raw Python + psycopg2.

**Learning goal:** This project is also a vehicle for understanding how RAG pipelines actually work internally, without framework magic hiding the mechanics.

## Constraints

- **Tech stack**: Python backend (direct `anthropic` SDK, `psycopg2`, `pgvector`), Next.js frontend — no LangChain, no LlamaIndex
- **Embeddings**: OpenAI `text-embedding-3-*` as v1 default, but swappable via `EMBEDDING_MODEL` env var (target: Voyage AI and `text-embedding-3-large`)
- **Database**: Local PostgreSQL with `pgvector` extension — no hosted DB
- **Deployment**: Fully local — no cloud hosting, no CI/CD pipeline needed
- **Single user**: No authentication, no multi-tenancy, no user management
- **Citation grounding**: Responses must cite source passages — no responses from model knowledge alone

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| No LangChain/LlamaIndex | Full control over chunking, retrieval, and embedding logic; learning the internals | — Pending |
| Configurable embedding model via env var | Can compare Voyage AI vs OpenAI vs local without code changes | — Pending |
| pgvector over a vector-DB service | Keeps everything local; familiar SQL tooling; no extra service to run | — Pending |
| Per-session memory only | Simplest correct behavior for personal tool; no state management overhead | — Pending |
| All four corpus source types in v1 | All data is already collected; ingestion complexity is the interesting engineering challenge | — Pending |
| Vertical MVP project mode | Ship an end-to-end working slice in Phase 1 (forum posts → chat → cited answer) before expanding corpus | — Pending |

## Evolution

This document evolves at phase transitions and milestone boundaries.

**After each phase transition** (via `/gsd-transition`):
1. Requirements invalidated? → Move to Out of Scope with reason
2. Requirements validated? → Move to Validated with phase reference
3. New requirements emerged? → Add to Active
4. Decisions to log? → Add to Key Decisions
5. "What This Is" still accurate? → Update if drifted

**After each milestone** (via `/gsd-complete-milestone`):
1. Full review of all sections
2. Core Value check — still the right priority?
3. Audit Out of Scope — reasons still valid?
4. Update Context with current state

---
*Last updated: 2026-05-19 — Phase 2 complete (retrieval layer + gear alias expansion)*
