# Held-Out Golden Eval Set

**Locked at:** 2026-05-19T00:54:58+00:00  (ISO-8601 UTC)
**Total tuples:** 22
**Held-out indices (0-based, matching golden_set.jsonl line order):** [0, 2, 4, 8, 11]
**Statement:** No retrieval tuning has been performed at the time of this commit.
Recall@K and MRR (Phase 5) will be measured against these held-out indices,
which are sourced from the following forum topics:
- bb_king_tone.txt
- eddie_van_halen_tone.txt
- funk_tone.txt
- lo_fi_tone.txt
- mark_knopfler_bowed_sound.txt

**Audit:** This file MUST be committed to git BEFORE any Phase 2 retrieval parameter
(K, expansion strategy, alias map content) is touched.
