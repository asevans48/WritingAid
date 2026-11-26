# Which rated rewrites a rewrite learns from: today and by voice (V.4)

_Measured 25 November 2026 with `scripts/voice_examples_compare.py`, no model._

**What was compared.** The brief's gate is the voice fit of rewrites made
with same-group examples against today's choice. Making rewrites needs a
model, and this session runs none, so this is the part that needs no model:
for every distinct rated passage of a grouped source (87 passages,
leave-one-out: an example of the same passage never counts), the two
examples each choice would give the model, measured by

- how many come from the passage's own voice group,
- how many are in the passage's person (first or third),
- the **voice fit** of the rewrite the writer chose in each example, scored
  by `WriterVoice.fit_score` (the score every rewrite is shown with) against
  the voice measured around the passage,
- the voice distance (V.1 fingerprint, in spreads) between example and passage.

The writer's database was read read-only (`mode=ro`); the rated rewrites were
copied to a scratch folder and fingerprinted and grouped there. Two groups, as
in V.2: Born in Blood (third person; 35 chosen examples, 31 passages, 1
rejected) and Teller County (first person; 65 chosen, 50 passages, none
rejected). Tempest (2 ratings) is Unsorted and learns as today.

"As a new book" is the same passage in a book with no ratings of its own,
placed in that voice's group: the case the groups are for.

| choice | examples | from the passage's group | in the passage's person | voice fit (mean) | voice distance (median) |
|---|---|---|---|---|---|
| today | 174 | 100% | 84% | 0.885 | 4.14 |
| today, new book | 174 | 49% | 44% | 0.849 | 4.58 |
| **by group, "tiers" (built)** | 174 | 100% | **86%** | **0.894** | 2.95 |
| by group, "tiers", new book | 174 | 100% | 86% | 0.894 | 2.95 |
| by group, closest first | 174 | 100% | 82% | 0.871 | 2.17 |
| by group, closest first, new book | 174 | 100% | 82% | 0.871 | 2.17 |
| by group, today's order | 174 | 100% | 85% | 0.884 | 4.11 |

**Reading it.**

- In the writer's two books today's choice already stays in the book's own
  voice, because each group is one book and that book's ratings come first.
  The gain is in a **new book** (or a book with few ratings) in a known
  voice: today half its examples come from the other voice (44% in its
  person, fit 0.849); by group all of them are its own voice (86%, 0.894).
- **Closest first** (the review note's wording, taken literally) picks
  examples nearest in voice (distance 2.17) but scores a little *lower* on
  voice fit (0.871 against today's 0.885), so by the gate it is not kept as
  the first key.
- **"Tiers"** keeps today's two tiers in front (excellent first, this
  project next) and puts the closest voice first inside each tier. It is the
  same or better than today on every line, so it is what was built
  (`voice_examples.WITHIN_GROUP = "tiers"`).

**Still to do with a model** (the writer): rewrite the same passages with
both choices and compare the voice fit of the rewrites themselves.
The differences above are small (0.885 → 0.894 on 174 examples); in a new
book they are large (0.849 → 0.894).

Re-run: `DB="$HOME/.creativeos/rephrase_history.db"; HOME=$(mktemp -d) venv/bin/python scripts/voice_examples_compare.py --db "$DB"`
(reads the database read-only; the copy goes to a scratch folder).
