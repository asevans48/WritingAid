# How good are the checks?

Written by `scripts/score_checks.py` (piece Q.2) on 2026-11-23. Rerun it after any
change to a check and compare with this table. The numbers are also in
`check_scores.json`.

**What the benchmark is** (`benchmark/`, piece Q.1):

- **seeded**: 12 passages of published prose with 58 known mistakes inserted;
- **clean**: the same 4,210 words untouched, where nearly every flag is a false alarm;
- **marked**: 24 short passages with every style problem marked by hand, including deliberate choices where a flag would be wrong.

Checks run as the editor shows them, with its quick rules for dialogue and names, with LanguageTool.

**Targets** (open decision 3, provisional): at least **4 in 5 flags right** (80%), and no more than **3 flags per 1,000 words** on clean prose.

| Check | Scored on | Found | Missed | Flags right | Flags wrong | Right (precision) | Found (recall) | Clean prose, per 1,000 words | Verdict |
|---|---|---|---|---|---|---|---|---|---|
| Spelling | seeded | 12 | 0 | 15 | 23 | 39% | 100% | 5.7 | below 4 in 5; too many on clean prose |
| Grammar | seeded | 43 | 3 | 41 | 7 | 85% | 93% | 1.7 | meets both targets |
| Overused words | clean only | — | — | — | — | — | — | 22.3 | too many on clean prose |
| Repeated phrases | clean only | — | — | — | — | — | — | 10.0 | too many on clean prose |
| Passive voice | marked | 3 | 0 | 3 | 3 | 50% | 100% | 2.4 | below 4 in 5 |
| Adverbs | marked | 4 | 0 | 4 | 4 | 50% | 100% | 10.7 | below 4 in 5; too many on clean prose |
| Weak intensifiers | marked | 4 | 0 | 4 | 0 | 100% | 100% | 2.6 | meets both targets |
| Wordy phrases | marked | 4 | 0 | 4 | 1 | 80% | 100% | 1.2 | meets both targets |
| Clichés | marked | 3 | 0 | 3 | 1 | 75% | 100% | 0.0 | below 4 in 5 |
| Repeated sentence starts | marked | 2 | 0 | 2 | 2 | 50% | 100% | 0.0 | below 4 in 5 |
| Echoes | marked | 1 | 1 | 1 | 4 | 20% | 50% | 5.5 | below 4 in 5; too many on clean prose |
| Long sentences | marked | 1 | 0 | 1 | 1 | 50% | 100% | 5.0 | below 4 in 5; too many on clean prose |
| Hard-to-read sentences | marked | 1 | 1 | 1 | 0 | 100% | 50% | 2.9 | meets both targets |
| Sticky sentences | marked | 1 | 0 | 1 | 16 | 6% | 100% | 34.4 | below 4 in 5; too many on clean prose |
| Overly descriptive | marked | 4 | 0 | 4 | 3 | 57% | 100% | 8.1 | below 4 in 5; too many on clean prose |

## The worst checks

- **Sticky sentences**: 6% of flags right, 34.4 flags per 1,000 words of clean prose (below 4 in 5; too many on clean prose).
- **Overused words**: — of flags right, 22.3 flags per 1,000 words of clean prose (too many on clean prose).
- **Adverbs**: 50% of flags right, 10.7 flags per 1,000 words of clean prose (below 4 in 5; too many on clean prose).
- **Echoes**: 20% of flags right, 5.5 flags per 1,000 words of clean prose (below 4 in 5; too many on clean prose).

## Seeded mistakes, by kind

| Kind of mistake | Found | Missed | Examples missed |
|---|---|---|---|
| agreement | 10 | 0 | — |
| confused word | 9 | 3 | “to → too”, “it is → its”, “to → too” |
| punctuation | 12 | 0 | — |
| repeated word | 12 | 0 | — |
| spelling | 12 | 0 | — |

## On clean published prose

4,210 words from twelve books (Gatsby, Styles, Call of the Wild …).

| Flag | Count | Per 1,000 words | Examples |
|---|---|---|---|
| sticky_sentence | 145 | 34.4 | “"What they must have cost at this season”, “the lady was saying in a sighing staccat”, “Archer bowed, and she continued: "My Ell” |
| overuse | 94 | 22.3 | “know”, “know”, “spirit” |
| adverb | 45 | 10.7 | “reprovingly”, “hastily”, “happily” |
| overused_phrase | 42 | 10.0 | “scratched his head”, “scratched his head”, “man had gone” |
| overdescribed | 34 | 8.1 | “The boys, who had to wriggle hastily dow”, “At last he said with an almost touching ”, “When those four quite honest men said th” |
| spelling | 24 | 5.7 | “Agathon”, “bloweth”, “listeth” |
| echo | 23 | 5.5 | “poetry”, “witty”, “once” |
| long_sentence | 21 | 5.0 | “I came from Cuba, where I have been spen”, “The boys, who had to wriggle hastily dow”, “Anne could run like a deer, however; run” |
| hard_sentence | 12 | 2.9 | “I came from Cuba, where I have been spen”, “The boys, who had to wriggle hastily dow”, “Ruby Gillis, who got a glimpse of it as ” |
| intensifier | 11 | 2.6 | “just”, “fairly”, “rather” |
| passive | 10 | 2.4 | “was swept”, “were beaten”, “was required” |
| grammar | 7 | 1.7 | “last”, “ hopefully”, “it” |
| wordy | 5 | 1.2 | “shrugged his shoulders”, “made an attempt”, “began to” |

## The two style analysers side by side (for R.4)

On the measures both have. Precision and recall on the marked passages; rate on clean prose.

**Since R.4** `ProWritingAnalyzer` (the Critique's numbers) calls `style_checks` for all five, so each check exists once. The columns still differ only because the Critique keeps whole sentences (passive, sticky) and distinct words (adverbs) where the editor marks each word, and this report counts what each one lists.

| Measure | style_checks: right | recall | clean per 1,000 | ProWritingAnalyzer: right | recall | clean per 1,000 | Better |
|---|---|---|---|---|---|---|---|
| passive | 43% | 100% | 4.3 | 33% | 100% | 2.4 | about the same |
| adverb | 50% | 100% | 11.9 | 36% | 100% | 13.5 | style_checks |
| cliche | 75% | 100% | 0.0 | 75% | 100% | 0.0 | about the same |
| sticky_sentence | 6% | 100% | 34.4 | 6% | 100% | 18.8 | ProWritingAnalyzer |
| echo | 20% | 50% | 5.5 | 10% | 50% | 10.9 | style_checks |

## Limits

- The marked set is small (a few dozen marks) and its marks are one editor's judgment, a draft for the writer to review. A single flag moves a style check's score a lot.
- The seeded mistakes are typical ones, inserted one of each kind per passage; real drafts make other mistakes too.
- The clean prose is 1898–1925 English. Period spellings and punctuation can draw flags that modern prose would not.
