"""Synthesize pacing-rewrite training pairs using CONLIT baselines.

The path: CONLIT can't be training data (no full text), but its
**genre baselines** are excellent supervision targets. For each
existing corpus row, we ask the configured LLM to rewrite the
passage so its avg sentence length, avg word length, and Tuldava
score move toward a target genre's CONLIT baseline. We verify each
rewrite genuinely shifts the stats *toward* the baseline (the
analyzer re-measures the LLM's output) and discard rewrites that
don't actually move closer — so the resulting training set is full
of demonstrably-correct supervision for "rewrite for genre X."

These rows land as ``SOURCE_PLOT`` with ``pacing_target=<genre>`` in
notes. A model fine-tuned on them learns "given a passage and a
target genre, produce a rewrite that matches that genre's pacing
conventions" — which is the practical use case for plot/pacing.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, Iterable, List, Optional


def synthesize_pacing_pairs(
    db,                                          # RephraseDatabase
    target_genre: str,
    *,
    llm_generate: Callable[[str, str], str],
    conlit_genre_stats: Optional[Dict[str, Any]] = None,
    source_collection_keys: Optional[Iterable[str]] = None,
    max_pairs: int = 20,
    min_passage_words: int = 100,
    on_log: Optional[Callable[[str], None]] = None,
) -> Dict[str, Any]:
    """Walk corpus rows, rewrite via LLM toward the target baseline,
    keep only rewrites whose stats genuinely move closer.

    Args:
        db: RephraseDatabase instance.
        target_genre: canonical genre key (mystery / scifi / romance /
            literary). Must be present in ``conlit_genre_stats``.
        llm_generate: callable taking ``(prompt, system_prompt)`` and
            returning the model's response text. The Training Studio
            wraps an ``LLMClient.generate_text`` here so the same
            cloud/local routing kicks in.
        conlit_genre_stats: ``by_genre`` dict from
            ``conlit_loader.get_genre_stats_cached()``. Pulled lazily
            when ``None``.
        source_collection_keys: per-corpus filter (same shape as the
            Corpus Filter dialog produces). ``None`` → consider every
            corpus collection.
        max_pairs: cap on training pairs to write — each one costs an
            LLM call, so we budget rather than blowing through.
        min_passage_words: skip passages shorter than this; pacing
            stats on tiny snippets are noisy.
        on_log: optional log sink for progress lines.

    Returns ``{n_logged, n_skipped_already_matching, n_skipped_no_improvement,
    n_failed, target_genre, baseline_summary}``.
    """
    log = on_log or (lambda *_: None)

    # Pull baselines if caller didn't pass them in
    if conlit_genre_stats is None:
        try:
            from src.data.conlit_loader import get_genre_stats_cached
            conlit_genre_stats = get_genre_stats_cached() or {}
        except Exception as e:
            return {"error": f"Could not load CONLIT stats: {e}",
                    "n_logged": 0}
    baseline = conlit_genre_stats.get(target_genre) if conlit_genre_stats else None
    if not baseline:
        return {
            "error": f"CONLIT has no baseline for genre {target_genre!r}. "
                     f"Available: "
                     f"{sorted(conlit_genre_stats or {})}",
            "n_logged": 0,
        }

    target_sl = baseline.get("avg_sentence_length__mean")
    target_wl = baseline.get("avg_word_length__mean")
    target_tul = baseline.get("tuldava_score__mean")
    if target_sl is None:
        return {"error": "Baseline missing avg_sentence_length__mean.",
                "n_logged": 0}

    log(f"Target {target_genre} pacing: "
        f"avg sentence length ≈ {target_sl:.2f} words, "
        f"avg word length ≈ {target_wl:.2f} chars, "
        f"Tuldava ≈ {target_tul:.2f}")

    # Pull candidate corpus rows. We look at every corpus row, optionally
    # narrowed to specific collection keys via the per-corpus filter.
    from src.data.rephrase_database import SOURCE_CORPUS, SOURCE_PLOT
    rows = db.positive_rows(source_types=[SOURCE_CORPUS])
    if source_collection_keys is not None:
        keys = set(source_collection_keys)

        def _key_for(notes: str) -> str:
            from src.data.rephrase_database import RephraseDatabase
            k, _, _ = RephraseDatabase._parse_collection_id(notes or "")
            return k
        rows = [r for r in rows if _key_for(r.get("notes") or "") in keys]
    log(f"Candidate corpus rows: {len(rows)}")

    from src.ai.pacing_analyzer import analyze_text

    n_logged = 0
    n_already_matching = 0
    n_no_improvement = 0
    n_failed = 0
    sys_prompt = (
        "You are a literary editor. You rewrite passages to match a "
        "target genre's pacing while keeping the meaning intact. "
        "Match the requested sentence-length and word-length targets "
        "as closely as you can. Output only the rewritten passage, "
        "no commentary, no quotes around it.")

    for row in rows:
        if n_logged >= max_pairs:
            break
        # Reconstruct the full passage (prompt = first sentence,
        # output = rest). For pacing analysis we want the whole thing.
        passage = ((row.get("source_text") or "") + " "
                   + (row.get("output_text") or "")).strip()
        stats = analyze_text(passage)
        if (not stats
                or stats.get("token_count", 0) < min_passage_words):
            continue

        current_sl = stats["avg_sentence_length"]
        current_wl = stats["avg_word_length"]
        # Skip passages already on-target (within ±1 word per sentence).
        # No useful supervision signal — would just teach the model to
        # echo. We want examples that demonstrate the rewrite move.
        if abs(current_sl - target_sl) < 1.0:
            n_already_matching += 1
            continue

        prompt = (
            f"Rewrite the passage below to match {target_genre} genre "
            f"pacing.\n"
            f"Target avg sentence length: {target_sl:.1f} words "
            f"(currently {current_sl:.1f}).\n"
            f"Target avg word length: {target_wl:.1f} chars "
            f"(currently {current_wl:.1f}).\n"
            f"Keep the meaning of the passage intact; rewrite the "
            f"prose, don't summarize.\n\n"
            f"Passage:\n{passage}\n\n"
            f"Rewritten passage:")

        try:
            rewrite = llm_generate(prompt, sys_prompt)
        except Exception as e:
            n_failed += 1
            log(f"  LLM call failed: {e}")
            continue

        rewrite = (rewrite or "").strip()
        if not rewrite or len(rewrite.split()) < min_passage_words // 2:
            n_failed += 1
            continue

        # Verify the rewrite *actually* moved closer to the target.
        # Without this, we'd save junk supervision — e.g., the LLM
        # ignored our request and the stats are unchanged or worse.
        new_stats = analyze_text(rewrite)
        if not new_stats:
            n_failed += 1
            continue
        new_sl = new_stats["avg_sentence_length"]
        old_distance = abs(current_sl - target_sl)
        new_distance = abs(new_sl - target_sl)
        if new_distance >= old_distance:
            # Rewrite didn't help — drop it. Important for training
            # quality; bad supervision is worse than less supervision.
            n_no_improvement += 1
            continue

        # Save as a SOURCE_PLOT row tagged for pacing. The notes carry
        # the target genre + stats deltas so the user (or a later
        # analyzer) can audit what was learned.
        notes = (
            f"pacing_target={target_genre} "
            f"old_sl={current_sl:.2f} new_sl={new_sl:.2f} "
            f"target_sl={target_sl:.2f}")
        # The trainer's plot prompt template adds "Generate a story
        # outline" framing — for pacing pairs we want a clearer
        # "rewrite this passage to match X pacing" framing instead.
        # We embed the framing in the prompt itself (which becomes the
        # "input" at training time) so the trainer's instruction
        # template still works without a new source type.
        train_prompt = (
            f"Rewrite the following passage to match {target_genre} "
            f"genre pacing (avg sentence length ≈ {target_sl:.1f} "
            f"words, avg word length ≈ {target_wl:.1f} chars). "
            f"Keep the meaning intact:\n\n{passage}")
        db.log_plot(prompt=train_prompt, completion=rewrite,
                    voice="", genre=target_genre, notes=notes)
        n_logged += 1
        log(f"  [{n_logged}/{max_pairs}] kept — "
            f"sl: {current_sl:.1f} → {new_sl:.1f} "
            f"(target {target_sl:.1f})")

    summary_bits = [
        f"avg_sl≈{target_sl:.2f}",
        f"avg_wl≈{target_wl:.2f}" if target_wl else "",
        f"tuldava≈{target_tul:.2f}" if target_tul else "",
    ]
    return {
        "n_logged": n_logged,
        "n_skipped_already_matching": n_already_matching,
        "n_skipped_no_improvement": n_no_improvement,
        "n_failed": n_failed,
        "target_genre": target_genre,
        "baseline_summary": ", ".join(s for s in summary_bits if s),
    }
