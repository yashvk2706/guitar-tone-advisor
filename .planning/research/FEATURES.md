# Feature Research: Guitar Tone Advisor

**Domain:** Single-user RAG chat app for guitar tone recommendations
**Researched:** 2026-05-13
**Confidence:** MEDIUM-HIGH (grounded in project context + inspection of actual corpus shape in `raw_data/`; web verification was unavailable so cross-product comparisons are training-data only and flagged where relevant)
**Source priority used:** Project corpus inspection (HIGH) > Project PROJECT.md (HIGH) > Training-data domain knowledge of guitar tone conventions and RAG UX patterns (MEDIUM)

---

## Reading guide

Each feature is tagged `[TS]` Table Stakes, `[D]` Differentiator, or `[AF]` Anti-Feature, plus complexity `Low / Med / High`. Categories map 1:1 to the six dimensions in the brief so the user can scope v1 vs v2 per dimension.

---

## Table Stakes (must have or the tool is useless)

### 1. Chat / conversation

- **Single-turn tone query → cited answer [TS, Low]** — User types one description, gets a response. This is the atomic unit of value; everything else is sugar.
- **Per-session multi-turn context [TS, Low]** — Follow-ups like "what if I drop the gain?" or "what about the bridge pickup instead?" must work without restating gear. Already in PROJECT.md scope. Without this, the tool feels like a single-shot search engine, not an advisor.
- **Gear + tone target in one message [TS, Low]** — The system must accept compound prompts ("I have a Katana and a Les Paul, how do I get John Mayer's clean tone?") because that is how the actual corpus is phrased (see `forum_posts/john_mayer_tone.txt` — the user's question literally says "My current rig is a boss katana with an epiphone les paul... I want a blues rock tone"). The product must mirror the input format the training data already validates.
- **Visible "thinking → retrieving → answering" state [TS, Low]** — RAG latency is real (embedding + vector search + LLM). Users tolerate it only if the UI tells them what is happening. A spinner alone is not enough; show "searching corpus..." then "drafting recommendation..."

### 2. Citation / grounding

- **Inline citations attached to specific claims [TS, Med]** — "Set Treble around 6 [1]" not "Sources: [1][2][3]" dumped at the bottom. Guitar advice is claim-dense (one paragraph can have 5 separate settings recommendations) and the user must be able to verify each one. This is the single most important UX decision in the whole product.
- **Source-type label on every citation [TS, Low]** — `[Forum]`, `[Manual]`, `[Article]`, `[YouTube]`. A knob setting from an official manual is a different epistemic object than a Reddit user's preference. The corpus already has four very different source types; collapsing them into anonymous "[1]" wastes information that is free to surface.
- **Expandable source preview [TS, Med]** — Click/hover a citation, see ~3-5 sentences of the actual chunk plus the source name (e.g. "Marshall JCM800 manual, p.4" or "r/Guitar — john_mayer_tone thread"). Without this, "grounded" is a marketing claim, not a verifiable property.
- **Refusal-with-reason when corpus is sparse [TS, Med]** — If the user asks about a Friedman amp (not in the corpus), the system must say "I don't have material on Friedman amps; the closest documented amp in my corpus is the Marshall JCM800 — want recommendations based on that?" Anything else is hallucination and violates PROJECT.md's "no responses from model knowledge alone" constraint.

### 3. Gear context

- **Free-text gear description in chat [TS, Low]** — Per-message, no profile, matches PROJECT.md scope ("user describes gear per session"). Natural for a personal tool; explicit gear forms would feel like a database admin panel.
- **Re-use of gear context across turns [TS, Low]** — Once stated, the system carries it. Subsumed by multi-turn context above but worth listing because it is the #1 source of perceived intelligence in a tool like this.

### 4. Tone target input

- **Artist name as primary input mode [TS, Low]** — Corpus is organized by artist (BB King, EVH, Mayer, Knopfler) and genre (funk, lo-fi, neo-soul, pop-punk). The retrieval is going to work best when users name what the corpus is labeled with. Expose this implicitly through suggestions or examples rather than forcing a dropdown.
- **Genre name as fallback [TS, Low]** — Same logic. Half the corpus is genre-labeled.
- **Free-text descriptors accepted but not over-promised [TS, Low]** — "warm", "glassy", "scooped" — must be tokenized and embedded like any query, but the system should not pretend it has a semantic understanding of "feeling" if the corpus does not back it up. Cite or refuse.

### 5. Answer quality

- **Concrete knob positions on a 0-10 scale [TS, Med]** — The corpus (verified in `john_mayer_tone.txt`) gives exact numbers: "brite off, 5 bass, 6 mids, 7 treble, and 6 Gain/Volume." Reproducing this fidelity is the difference between "advisor" and "generic chatbot." If the model only gives ranges and principles, the user has gained nothing they could not get from Google.
- **Signal chain order recommendation [TS, Low]** — When the user lists multiple pedals, output the order (guitar → BD-2 → TS9 → MXR Phase 90 → DD-3 → amp). Standard guitar-domain expectation; pedal placement is a documented constraint, not preference.
- **Pedal-to-amp pairing logic [TS, Med]** — "Set TS9 with gain low, level high, hit a cranked Fender clean" — the relationship between pedal and amp setting is the actual content of tone advice. Must come through in answers.
- **"Closest you can get with your gear" framing [TS, Med]** — If user has a Mesa Mark V and asks for Marshall JCM800 crunch, do NOT say "buy a JCM800." Translate: "On the Mark V, use channel 2 'crunch' mode, gain ~5, master ~4, this approximates a cranked JCM800 because..." This is the single most useful behavior for a personal tool — the user has fixed gear.

### 6. UI / UX

- **Markdown rendering [TS, Low]** — Tone answers are inherently list-shaped (amp settings, pedal settings, signal chain). Plain text becomes unreadable. Use a standard React markdown renderer; do not write your own.
- **Chat history visible in session [TS, Low]** — Standard chat UX. Already in PROJECT.md scope.
- **Copy-to-clipboard on the recommendation block [TS, Low]** — Users want to physically adjust their amp while reading. Make the settings block one-tap copyable. Tiny feature, disproportionate value.
- **"New chat" button that clears state [TS, Low]** — Required because state is session-only (PROJECT.md). Must be obvious to avoid context pollution across unrelated tone questions.

---

## Differentiators (makes it great, competitive advantage)

### 1. Chat / conversation

- **Clarifying back-questions when the query is ambiguous [D, Med]** — "Are you asking about Mayer's clean Strat tone or his crunchy Black1 lead tone? My corpus distinguishes them." Powerful because the corpus naturally segments artists into multiple tones. Depends on retrieval returning labeled-enough chunks to detect ambiguity.
- **Suggested follow-ups [D, Low]** — Three buttons under each answer: "How do I get this cleaner?" / "What if I'm playing live?" / "Show me a budget version." Cheap to implement; massively increases tool's perceived intelligence.
- **"Why" toggle [D, Med]** — Each setting can be expanded to show the reasoning ("Treble at 6 because the JCM800's tone stack is bright and 7+ becomes harsh in a band mix [Marshall manual, p.4]"). Turns a recommendation list into a teaching tool.

### 2. Citation / grounding

- **Source diversity indicator [D, Med]** — Small badge: "3 forum posts, 1 manual" agree on this. Builds trust when corpus depth is good; honesty when it is shallow.
- **Quote-level grounding (not just chunk-level) [D, High]** — When the model cites, it shows the actual sentence it used, not just "from this 500-token chunk somewhere." Hard to implement well; requires either span attribution at generation time or post-hoc matching. Worth it because it makes hallucination obvious if it happens.
- **Conflicting-sources surfacing [D, Med]** — When forum users disagree (e.g. one says TS9 before the BD-2, another says after), surface the disagreement rather than collapsing it: "Sources disagree — most place TS9 before BD-2 [3 forum posts], but one notable post argues the reverse for John Mayer's tone [1 forum post]." Genuinely useful and uniquely possible because the corpus contains opinion content.

### 3. Gear context

- **Inferred gear normalization [D, Med]** — User says "Katana" → system internally tags it as "modeling amp, 50W class, has built-in TS9/BD-2/Fender simulations." Enables the "closest analog" responses. The `john_mayer_tone.txt` corpus literally does this inference ("Your amp already has everything else you need - a Blues Driver sim, a Tube Screamer sim..."). The corpus is teaching you the feature; you should ship it.
- **Gear-mismatch escape hatch [D, Med]** — When the corpus passage references gear the user does not have, the model should explicitly translate ("the passage describes a Two Rock; you have a Blackstar HT5 — here's the equivalent setting on yours"). High value because mismatches are the common case for a single-user personal tool.

### 4. Tone target input

- **Reference-track citation [D, Low]** — User says "the rhythm tone in 'Slow Dancing in a Burning Room'" — system passes it as part of the query and retrieves whatever chunks mention that song. Cheap (no audio processing — text only, per PROJECT.md), high value, very natural.
- **Tone descriptor → corpus vocabulary translation [D, Med]** — User says "I want a swampy tone." System retrieves chunks containing "swampy" or near-synonyms ("dark", "muddy", "blackface-ish"). Differentiator because most chatbots would just embed and hope; explicit query expansion within the guitar vocabulary makes retrieval visibly better.

### 5. Answer quality

- **"Budget version" variant [D, Low]** — Below the main recommendation, a 2-3 line "if you only have one OD pedal" or "if you can't crank your amp, here's how to fake it at bedroom volume." Maps directly to the recurring pattern in forum posts (the corpus is full of "for those who can't afford the real thing..." content).
- **Confidence indicator per recommendation [D, Med]** — A subtle "well-documented" vs "thinly sourced" marker. If 5 corpus chunks back a recommendation, say so. If only one forum comment supports it, say so. Maps to the source-diversity indicator above but applied per claim, not per answer.
- **Bedroom / band / studio mode toggle [D, Med]** — Same gear, three different recommendations depending on context (volume, mic'd vs DI, etc.). Forum posts already segment advice this way; surfacing the segmentation as a UI primitive is high-leverage.
- **Visual signal-chain diagram [D, High]** — Render the pedal order as a small left-to-right diagram (Guitar → BD-2 → TS9 → Amp). High implementation cost relative to a markdown list, but it is the single most "this is a real guitar tool" moment available in v2.

### 6. UI / UX

- **Side panel for cited passages [D, Med]** — Two-pane layout: chat on left, currently-cited sources on right, updating as you scroll the conversation. Pattern borrowed from research/legal RAG tools; uniquely well-suited to gear advice because users want to re-read source material while adjusting their rig.
- **"Compare two answers" mode [D, High]** — Run the same query through two different retrieval settings (e.g. forum-only vs manual-only) and show side-by-side. Diagnostically valuable for the project's "learn RAG internals" goal, and a unique UX no commercial product has.
- **Persistent "current rig" pill at top of chat [D, Low]** — Once the user describes their gear, show it as an editable chip at the top. Reduces re-statement and makes the active context legible. Stays within PROJECT.md scope (per-session only — does not persist across sessions).

---

## Anti-Features (deliberately avoid)

- **Persistent gear profile / user accounts [AF]** — Explicitly out of scope per PROJECT.md. Adds auth, DB schema, settings UI, and zero value for a personal tool. Easy to add accidentally because every tutorial includes it; resist.
- **Generic "ask me anything about guitar" framing [AF]** — Pulls the tool toward Wikipedia-style Q&A and away from the actionable settings-recommendation use case. The product is a *tone advisor*; if a question doesn't reduce to "given gear X, achieve sound Y," it does not belong.
- **Tone descriptors invented by the model [AF]** — If the corpus does not contain "buttery" or "creamy" or whatever marketing word the user types, do not bluff a translation. Either cite a passage that uses comparable language or surface the gap. Violating this single rule destroys the credibility of the tool.
- **Recommending gear the user does not have [AF]** — A single-user tool with fixed gear has zero use for "you should buy a Klon." Allowed only as a clearly-labeled aside ("if you ever upgrade..."), never as the primary recommendation.
- **Hallucinated knob settings [AF]** — The model must NOT fill in "Bass=5, Mid=5, Treble=5" when the corpus does not specify. If only one knob is documented, say only that one. This is the highest-stakes failure mode because settings *look* authoritative even when fabricated.
- **Audio file upload / waveform analysis [AF]** — Explicit PROJECT.md out-of-scope. Tempting because tone-from-audio is the obvious "AI" move; resist — it would be a different product.
- **YouTube embeds inline [AF, soft]** — Corpus already includes YouTube transcripts. Resist the urge to embed the actual video player in chat — it bloats the page and distracts from the cited text. A linked timestamp is enough.
- **Real-time MIDI / amp control [AF]** — Out of scope and would require hardware integration not relevant to a corpus-driven advisor.
- **Aggressive auto-complete or "suggested queries" before the user has typed anything [AF, soft]** — Personal tool. Empty state can be empty. Showing "popular searches" implies a multi-user product the system is not.
- **Confidence-as-percentage ("87% sure") [AF]** — Looks scientific, isn't. Use coarse labels (well-documented / partial / sparse) tied to actual chunk counts, not made-up numbers.
- **Star ratings / thumbs-up-thumbs-down feedback UI [AF, v1]** — Useful in multi-user products with model fine-tuning loops. For a single-user personal tool with no training loop, it is decoration. Defer until there is a real use for the data.
- **LangChain / LlamaIndex abstractions in the retrieval path [AF]** — Explicitly out of scope per PROJECT.md ("no framework abstractions"). Not a feature decision but worth restating because every off-the-shelf "RAG chat UI" template ships them.

---

## Feature Dependencies

```
Inline citations [TS]
  ├── requires: chunk-id passed through generation [TS]
  └── enables: Expandable source preview [TS]
        └── enables: Source diversity indicator [D]
              └── enables: Confidence indicator per recommendation [D]
                    └── enables: Conflicting-sources surfacing [D]

Multi-turn context [TS]
  ├── requires: session conversation store [TS]
  └── enables: Clarifying back-questions [D]
        └── enables: Suggested follow-ups [D]

Free-text gear description [TS]
  └── enables: Inferred gear normalization [D]
        └── enables: Gear-mismatch escape hatch [D]
              └── enables: "Closest you can get" framing [TS]   ← note: TS depends on D

Concrete knob positions [TS]
  ├── requires: retrieval surfacing setting-dense chunks [TS]
  └── enables: "Why" toggle [D]
        └── enables: Budget-version variant [D]

Source-type label [TS]
  └── enables: Compare-two-answers mode [D]
        (filter retrieval by source type)

Markdown rendering [TS]
  └── enables: Visual signal-chain diagram [D]
        (richer renderer can host the diagram component)

Persistent "current rig" pill [D]
  └── requires: gear-extraction from prior messages
        (lightweight named-entity-recognition or first-turn parse)
```

**Critical observation:** the "Closest you can get with your gear" feature is tagged Table Stakes because without it the tool is useless for the single-user case, but it depends on the **Inferred gear normalization** differentiator. The v1 implementation can be a degraded version that the LLM does inline (no explicit normalization step), with the proper normalization layer being a v2 upgrade. Flag this for the roadmap.

---

## Recommended v1 Scope

Phase 1 should ship every `[TS]` feature, and exactly two `[D]` features as quality multipliers. Concretely:

**v1 = Phase 1 deliverable**

Chat:
- Single-turn tone query → cited answer
- Per-session multi-turn context (gear + target reuse across turns)
- Visible retrieval / generation state in UI
- "New chat" clears session

Citation:
- Inline citations with claim-level attachment
- Source-type label (`[Forum]` / `[Manual]` / `[Article]` / `[YouTube]`)
- Expandable source preview (3-5 sentences + source name)
- Refusal-with-reason when corpus is sparse

Gear:
- Free-text gear description in chat
- "Closest you can get with your gear" framing (LLM-handled inline in v1, no explicit normalization layer yet)

Tone target:
- Artist name, genre, free-text descriptors all accepted as natural-language input

Answer quality:
- Concrete knob positions on a 0-10 scale when supported by corpus
- Signal chain order
- Pedal-to-amp pairing logic in the answer text

UI:
- Markdown rendering
- Session history visible
- Copy-to-clipboard on the recommendation block

**Two differentiators to include in v1** (low-cost, high-leverage):
- **Suggested follow-ups under each answer** — Low complexity, transforms the UX feel disproportionately. Three buttons, prompted from the answer content.
- **Source diversity indicator** ("3 forum posts, 1 manual agree") — Reuses citation infrastructure; cheap; directly addresses the project's "grounded, not hallucinated" thesis.

**Explicitly defer to v2:**
- Quote-level (span) grounding — too implementation-heavy for v1
- Inferred gear normalization as an explicit layer — let the LLM handle it in v1
- Visual signal-chain diagram — needs a custom component
- Side-panel cited-passages view — needs a different layout, can wait
- "Compare two answers" mode — diagnostic, not user-facing
- Conflicting-sources surfacing — depends on retrieval returning enough labeled chunks to detect conflict; assess after v1 corpus is indexed

**Explicit non-goals for v1:** All anti-features listed above, plus the deferred differentiators. Stay disciplined: every minute spent on a deferred differentiator is a minute not spent making the table-stakes citation UX excellent, and citation UX is where this product lives or dies.

---

## Quality Gate Checklist

- [x] Table stakes clearly separated from differentiators
- [x] Anti-features called out (12 explicit anti-features with rationale)
- [x] Complexity noted for every feature (`Low / Med / High`)
- [x] Guitar-domain-specific features captured (knob settings, signal chain, pedal-amp pairing, gear-mismatch translation, source-type taxonomy specific to guitar Q&A) — not just generic chatbot features

---
*Researched: 2026-05-13*
