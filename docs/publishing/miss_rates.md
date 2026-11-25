# How much does the check miss?

Written by `scripts/measure_misses.py` on 2026-11-24. Rerun it after any change to a check, the proofreading pass or the story read.

**What was measured:** 3 copies of the benchmark's clean passages with 21 known mistakes inserted, read by the readiness check “Spelling and grammar left”; and 4 short three-chapter books, in most of which the last chapter contradicts the first. Without LanguageTool.

## Spelling and grammar: caught and missed

| Mistake | Inserted | Rules alone: caught | With the model (mlx-community/Cydonia-24B-v3.1-4bit): caught |
|---|---|---|---|
| Misspelling | 3 | 3 (100%) | 3 (100%) |
| Confused word (their/there, could of) | 3 | 0 (0%) | 1 (33%) |
| Subject–verb agreement | 3 | 3 (100%) | 2 (67%) |
| Punctuation and capitals | 3 | 2 (67%) | 2 (67%) |
| Doubled word | 3 | 3 (100%) | 3 (100%) |
| Harder confusion (quite/quiet) | 3 | 0 (0%) | 1 (33%) |
| Missing word | 3 | 0 (0%) | 1 (33%) |
| **All** | 21 | **11 (52%)** | **13 (62%)** |

- Flags that hit no inserted mistake: 8.91 per 1,000 words with the rules alone, 1.98 with the model.
- Flags on the untouched passages: 8.93 per 1,000 words with the rules alone, 11.9 with the model.

**Flags on the untouched passages with the model, for example:**

- “Agathon” (a rule the model kept: Possible misspelling.)
- “marvellous” (a rule the model kept: Possible misspelling.)
- “splendour” (a rule the model kept: Possible misspelling.)
- “girl” (the model: missing comma after introductory phrase (found by the model))
- “Cannes” (the model: missing comma after introductory phrase (found by the model))
- “Deauville” (the model: missing comma after introductory phrase (found by the model))
- “know” (the model: missing period at end of sentence (found by the model))
- “doesn’t” (the model: tense slip (past tense context) (found by the model))
- “this” (the model: missing comma after introductory phrase (found by the model))
- “driving” (the model: missing comma after introductory phrase (found by the model))
- “twilight:” (the model: colon should be period (not a complete sentence) (found by t)
- “Oldring” (a rule the model kept: Possible misspelling.)

**Still missed with the model, for example:**

- Punctuation and capitals: missing apostrophe
- Subject–verb agreement: you were → you was
- Harder confusion (quite/quiet): of → off; from → form
- Missing word: “the” dropped; “the” dropped
- Confused word (their/there, could of): where → were; to → too

## Story: contradictions caught

- Contradictions caught: **1 of 3** (33%).
- Findings on the 1 books with nothing wrong: **3**.
- Other findings on the books with a contradiction: 2.
- Facts the model recorded for the style sheet: 39.
- Missed: eyes (appearance changed); letter (ability contradicted).
- Wrongly raised: ok-learned: “All that summer Tobias taught Mara to swim in the shallows b”.

## Structure: planted flaws caught

- Planted flaws caught by the editor's checks: **2 of 4**.
- Of those 4 books, the editorial letter named the flawed chapter in an issue for **4**.
- Findings on the book with nothing planted: 6.
- Missed: flat-scene (a chapter of chores after which nothing is different); head-hop (the bailiff's private thoughts inside Ilse's scene).

## What this does and doesn't show

- The inserted mistakes are common kinds, one of each per copy; real drafts make others. A caught rate here is an upper bound on trust, not a promise.
- The story cases are short and hand-written, with the contradiction two chapters after the fact. A novel's contradictions are further apart and subtler.
- The structure cases are four short chapters with one obvious flaw each: a floor, not a measure of how the letter does on a real novel.
- Model results vary by model and from run to run; the model is named above.
