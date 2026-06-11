# Held-Out Golden Eval Set

**Locked at:** 2026-06-09T19:30:51+00:00  (ISO-8601 UTC)
**Total tuples:** 22
**Held-out indices (0-based, matching golden_set.jsonl line order):** [7, 9, 11, 12, 21]
**Statement:** No retrieval tuning has been performed at the time of this commit.
Recall@K and MRR (Phase 5) will be measured against these held-out indices,
which are sourced from the following forum topics:
- john_mayer_tone.txt
- lo_fi_tone.txt
- mark_knopfler_bowed_sound.txt
- modern_pop_punk_tone.txt
- unconventional_tones.txt

**Audit:** This file MUST be committed to git BEFORE any Phase 2 retrieval parameter
(K, expansion strategy, alias map content) is touched.
