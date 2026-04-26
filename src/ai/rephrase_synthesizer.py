"""Synthesize rephrase training pairs from existing corpus rows.

The path: take any corpus the user has ingested (their own writing,
project chapters, public-domain literature), ask the configured LLM
to paraphrase each passage, then **verify the paraphrase is actually
useful supervision** before saving it. Quality gates are critical
here — bad rephrase pairs teach the model to either (a) echo the
input verbatim, or (b) drift wildly off-meaning.

Two filter conditions a paraphrase must pass to be kept:

  1. **Different enough** — bigram Jaccard overlap with the original
     must be < 0.7 (a verbatim echo would score 1.0; a true rephrase
     scores 0.2-0.5). Below 0.7 means the model is doing real work.
  2. **Length-similar** — within 30% of the original's word count.
     A 60-word original paraphrased to 12 words is summarization, not
     rephrasing; we drop those.

Verified pairs are logged as ``SOURCE_REPHRASE`` rows so they feed
the rephrase task pipeline directly. Voice + genre tags propagate
from the source corpus row, so the user's voice (when training their
own writing) carries through to the rephrased target.
"""

from __future__ import annotations

import re
from typing import Any, Callable, Iterable, List, Optional


def _ngrams(text: str, n: int = 2) -> set:
    """Set of n-grams over lowercase tokens."""
    tokens = re.findall(r"[a-z][a-z']*", text.lower())
    if len(tokens) < n:
        return set()
    return {tuple(tokens[i:i + n]) for i in range(len(tokens) - n + 1)}


def _bigram_jaccard(a: str, b: str) -> float:
    """Bigram Jaccard similarity in [0, 1]. 1.0 = identical bigram set,
    0.0 = no shared bigrams. Used as the "different enough" gate."""
    set_a, set_b = _ngrams(a, 2), _ngrams(b, 2)
    if not set_a or not set_b:
        return 0.0
    intersection = len(set_a & set_b)
    union = len(set_a | set_b)
    return intersection / union if union else 0.0


def _word_count(text: str) -> int:
    return len(re.findall(r"\b\w+\b", text))


def synthesize_rephrase_pairs(
    db,                                          # RephraseDatabase
    *,
    llm_generate: Callable[[str, str], str],
    source_collection_keys: Optional[Iterable[str]] = None,
    max_pairs: int = 30,
    min_passage_words: int = 40,
    max_passage_words: int = 400,
    max_overlap: float = 0.7,
    min_overlap: float = 0.15,
    length_tolerance: float = 0.30,
    on_log: Optional[Callable[[str], None]] = None,
) -> dict:
    """Generate rephrase training pairs by paraphrasing corpus rows.

    Args:
        db: RephraseDatabase instance.
        llm_generate: ``(prompt, system_prompt) -> str`` — the configured
            LLM. Wrapped from ``LLMClient.generate_text`` by the caller.
        source_collection_keys: per-corpus filter (same shape as the
            Corpus Filter dialog produces). ``None`` → consider every
            corpus collection.
        max_pairs: cap on training pairs to write — each costs an
            LLM call.
        min_passage_words / max_passage_words: passages outside this
            range are skipped. Tiny passages produce noisy stats;
            huge ones blow the LLM context.
        max_overlap: bigram Jaccard threshold above which a "rephrase"
            is judged too close to the original (verbatim echo).
            Default 0.7 — the LLM has to genuinely transform the prose.
        min_overlap: floor below which a "rephrase" is judged
            unrelated to the original (LLM hallucinated different
            meaning). Default 0.15.
        length_tolerance: rewrite must be within ±this fraction of
            the original's word count. Default 0.30 (i.e. 70%-130%).
        on_log: optional log sink for progress.

    Returns ``{n_logged, n_skipped_too_short, n_skipped_too_long,
    n_skipped_too_similar, n_skipped_too_different, n_skipped_length,
    n_failed}`` so the caller can show a useful summary.
    """
    log = on_log or (lambda *_: None)

    from src.data.rephrase_database import (
        SOURCE_CORPUS, SOURCE_REPHRASE, RephraseDatabase,
    )

    # Pull candidate corpus rows. The user's own writing produces the
    # highest-value supervision (voice-specific rephrases) — passages
    # tagged with a voice are prioritized within the cap.
    rows = db.positive_rows(source_types=[SOURCE_CORPUS])
    if source_collection_keys is not None:
        keys = set(source_collection_keys)

        def _key_for(notes: str) -> str:
            k, _, _ = RephraseDatabase._parse_collection_id(notes or "")
            return k
        rows = [r for r in rows if _key_for(r.get("notes") or "") in keys]

    # Sort: voice-tagged corpus rows first (highest training value
    # for the user's own model), then everything else.
    rows.sort(key=lambda r: 0 if (r.get("voice") or "").strip() else 1)
    log(f"Candidate corpus rows: {len(rows)}")

    sys_prompt = (
        "You are a literary editor. You paraphrase passages — "
        "rewriting them so the prose is materially different but the "
        "meaning is preserved. Keep the same length (within 30% of "
        "the original). Don't summarize; rewrite. Output ONLY the "
        "paraphrased passage, no commentary, no quotes around it.")

    n_logged = 0
    n_skipped_too_short = 0
    n_skipped_too_long = 0
    n_skipped_too_similar = 0
    n_skipped_too_different = 0
    n_skipped_length = 0
    n_failed = 0

    for row in rows:
        if n_logged >= max_pairs:
            break
        passage = ((row.get("source_text") or "") + " "
                   + (row.get("output_text") or "")).strip()
        passage_wc = _word_count(passage)
        if passage_wc < min_passage_words:
            n_skipped_too_short += 1
            continue
        if passage_wc > max_passage_words:
            n_skipped_too_long += 1
            continue

        prompt = (
            f"Paraphrase this passage. Keep the meaning intact; "
            f"rewrite the prose. Match the original length "
            f"(~{passage_wc} words).\n\n"
            f"Passage:\n{passage}\n\n"
            f"Paraphrased passage:")

        try:
            rewrite = llm_generate(prompt, sys_prompt)
        except Exception as e:
            n_failed += 1
            log(f"  LLM call failed: {e}")
            continue
        rewrite = (rewrite or "").strip()
        if not rewrite:
            n_failed += 1
            continue

        # Length gate
        rewrite_wc = _word_count(rewrite)
        if rewrite_wc == 0:
            n_failed += 1
            continue
        length_ratio = rewrite_wc / passage_wc
        if (length_ratio < (1 - length_tolerance)
                or length_ratio > (1 + length_tolerance)):
            n_skipped_length += 1
            continue

        # Surface-difference gate (bigram Jaccard)
        overlap = _bigram_jaccard(passage, rewrite)
        if overlap > max_overlap:
            n_skipped_too_similar += 1
            log(f"  too similar ({overlap:.2f}): rejected")
            continue
        if overlap < min_overlap:
            n_skipped_too_different += 1
            log(f"  too different ({overlap:.2f}): probably "
                f"hallucinated, rejected")
            continue

        # Save as a rephrase training row. Voice + genre come from the
        # source row so user-voice corpora produce voice-specific
        # rephrase supervision (the user's own writing → their style
        # of rephrase).
        voice = (row.get("voice") or "").strip()
        genre = (row.get("genre") or "").strip()
        notes = (
            f"synthesized=rephrase "
            f"source_corpus_id={row.get('id', '?')} "
            f"overlap={overlap:.2f} "
            f"len_ratio={length_ratio:.2f}")
        db.log(
            source_text=passage, output_text=rewrite,
            source_type=SOURCE_REPHRASE,
            rating="good",         # synthetic but quality-gated → good
            accepted=True,
            voice=voice, genre=genre,
            character_name=row.get("character_name", ""),
            notes=notes)
        n_logged += 1
        log(f"  [{n_logged}/{max_pairs}] kept "
            f"(overlap={overlap:.2f}, len_ratio={length_ratio:.2f})")

    return {
        "n_logged": n_logged,
        "n_skipped_too_short": n_skipped_too_short,
        "n_skipped_too_long": n_skipped_too_long,
        "n_skipped_too_similar": n_skipped_too_similar,
        "n_skipped_too_different": n_skipped_too_different,
        "n_skipped_length": n_skipped_length,
        "n_failed": n_failed,
    }
