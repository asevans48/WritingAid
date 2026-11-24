# How much does the check miss?

Written by `scripts/measure_misses.py` on 2026-11-23. Rerun it after any change to a check, the proofreading pass or the story read.

**What was measured:** 60 copies of the benchmark's clean passages with 409 known mistakes inserted, read by the readiness check “Spelling and grammar left”. Without LanguageTool.

## Spelling and grammar: caught and missed

| Mistake | Inserted | Rules alone: caught |
|---|---|---|
| Misspelling | 60 | 60 (100%) |
| Confused word (their/there, could of) | 60 | 7 (12%) |
| Subject–verb agreement | 49 | 49 (100%) |
| Punctuation and capitals | 60 | 54 (90%) |
| Doubled word | 60 | 60 (100%) |
| Harder confusion (quite/quiet) | 60 | 0 (0%) |
| Missing word | 60 | 0 (0%) |
| **All** | 409 | **230 (56%)** |

- Flags that hit no inserted mistake: 4.75 per 1,000 words with the rules alone.
- Flags on the untouched passages: 4.75 per 1,000 words with the rules alone.

**Still missed, for example:**

- Punctuation and capitals: missing apostrophe; missing apostrophe; missing apostrophe; missing apostrophe; missing apostrophe
- Harder confusion (quite/quiet): his → he's; his → he's; of → off; his → he's; of → off
- Missing word: “the” dropped; “the” dropped; “the” dropped; “the” dropped; “the” dropped
- Confused word (their/there, could of): where → were; where → were; where → were; where → were; to → too

## Story: contradictions caught

Not measured: the story read needs a model. Run with `--model`.

## What this does and doesn't show

- The inserted mistakes are common kinds, one of each per copy; real drafts make others. A caught rate here is an upper bound on trust, not a promise.
- The story cases are short and hand-written, with the contradiction two chapters after the fact. A novel's contradictions are further apart and subtler.
- Model results vary by model and from run to run; the model is named above.
