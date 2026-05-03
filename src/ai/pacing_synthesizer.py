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
    tones: Optional[List[str]] = None,
    on_log: Optional[Callable[[str], None]] = None,
) -> Dict[str, Any]:
    """Walk corpus rows, rewrite via LLM toward the target baseline,
    keep only rewrites whose stats genuinely move closer.

    Tone variants
    -------------
    When ``tones`` is supplied (a list of canonical tone keys from
    :mod:`src.data.tones`), the synthesiser produces one rewrite
    *per tone* per source row. The LLM is asked to hit BOTH the
    CONLIT pacing baseline AND the tone register — the resulting
    pair carries ``style=<tone_key>`` so the trainer's plot/pacing
    instruction template includes the tone at training time.

    Composition: source repeated across tones isn't redundant. With
    tone-conditioning in the prompt, the model learns "given source
    X + target genre Y + tone Z, produce a rewrite". ``max_pairs``
    is a hard cap on emissions — 200 cap with 4 tones ticked → ~50
    source rows × 4 tones each.

    When ``tones`` is None or empty the function behaves as before
    (one tone-agnostic rewrite per source).

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
        tones: optional list of canonical tone keys. When set, each
            source row produces one rewrite per tone with the tone's
            register injected into the LLM prompt.
        on_log: optional log sink for progress lines.

    Returns ``{n_logged, n_skipped_already_matching, n_skipped_no_improvement,
    n_failed, target_genre, baseline_summary, tones_used}``.
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
    DEFAULT_SYS = (
        "You are a literary editor. You rewrite passages to match a "
        "target genre's pacing while keeping the meaning intact. "
        "Match the requested sentence-length and word-length targets "
        "as closely as you can. Output only the rewritten passage, "
        "no commentary, no quotes around it.")

    # Tone iteration. ``[None]`` is the legacy single-rewrite path;
    # a non-empty tone list produces one variant per tone per source.
    if tones:
        from src.data.tones import (
            TONES as _TONES,
            display_name as _tone_name,
        )
        tone_iter = list(tones)
        log(f"Tone variants per source row: "
            f"{', '.join(_tone_name(t) for t in tone_iter)}")
    else:
        tone_iter = [None]
        _TONES = {}                       # noqa: F841
        _tone_name = lambda k: k or ""    # noqa: E731

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
        # Skip passages already on-target (within ±1 word per sentence)
        # — but only when not generating tone variants. With tones, the
        # rewrite still needs to shift the *tone* even if pacing is
        # already on-target, so we let those through.
        if not tones and abs(current_sl - target_sl) < 1.0:
            n_already_matching += 1
            continue

        for tone_key in tone_iter:
            if n_logged >= max_pairs:
                break

            # Build the tone-conditional system + user prompts. The
            # tone description from the canonical taxonomy is
            # injected so the LLM knows the exact register required
            # — pacing target + tone register together.
            if tone_key:
                tinfo = _TONES.get(tone_key, {})
                tlabel = tinfo.get("name", tone_key)
                tdesc = tinfo.get("description", "")
                sys_for_call = (
                    "You are a literary editor. You rewrite passages "
                    f"to match a target genre's pacing in a "
                    f"{tlabel.lower()} register — {tdesc} Match the "
                    "requested sentence-length and word-length "
                    "targets as closely as you can. Output only the "
                    "rewritten passage, no commentary, no quotes "
                    "around it.")
                prompt = (
                    f"Rewrite the passage below to match "
                    f"{target_genre} genre pacing in a "
                    f"{tlabel.lower()} register.\n"
                    f"Target avg sentence length: {target_sl:.1f} "
                    f"words (currently {current_sl:.1f}).\n"
                    f"Target avg word length: {target_wl:.1f} chars "
                    f"(currently {current_wl:.1f}).\n"
                    f"Keep the meaning intact; rewrite the prose in "
                    f"the {tlabel.lower()} register, don't summarize."
                    f"\n\nPassage:\n{passage}\n\n"
                    f"Rewritten passage:")
            else:
                sys_for_call = DEFAULT_SYS
                prompt = (
                    f"Rewrite the passage below to match "
                    f"{target_genre} genre pacing.\n"
                    f"Target avg sentence length: {target_sl:.1f} "
                    f"words (currently {current_sl:.1f}).\n"
                    f"Target avg word length: {target_wl:.1f} chars "
                    f"(currently {current_wl:.1f}).\n"
                    f"Keep the meaning of the passage intact; "
                    f"rewrite the prose, don't summarize.\n\n"
                    f"Passage:\n{passage}\n\n"
                    f"Rewritten passage:")

            try:
                rewrite = llm_generate(prompt, sys_for_call)
            except Exception as e:
                n_failed += 1
                log(f"  LLM call failed: {e}")
                continue

            rewrite = (rewrite or "").strip()
            if (not rewrite
                    or len(rewrite.split()) < min_passage_words // 2):
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
                # Rewrite didn't help — drop it. Important for
                # training quality; bad supervision is worse than
                # less supervision.
                n_no_improvement += 1
                continue

            # Save as a SOURCE_PLOT row tagged for pacing. The
            # ``source_text`` is the bare passage — NOT framed
            # with "Rewrite this to match X pacing", because the
            # trainer's plot/pacing template adds that framing at
            # render time (see ``_format_row``'s SOURCE_PLOT
            # branch with kind="pacing"). Earlier versions baked
            # the framing into source_text as a workaround for a
            # missing pacing template; that produced doubled
            # instructions ("Rewrite this passage to match..."
            # both inside and outside the input). The
            # ``_init_schema`` backfill strips the legacy
            # framing from existing rows; new rows skip it.
            #
            # Notes carry pacing_target so the trainer detects
            # kind="pacing" via the existing notes-based hint;
            # tone (when set) lands in ``style`` so the template
            # adds "in a <tone> tone" at training time.
            tone_note = (f" tone={tone_key}" if tone_key else "")
            notes = (
                f"pacing_target={target_genre}{tone_note} "
                f"old_sl={current_sl:.2f} new_sl={new_sl:.2f} "
                f"target_sl={target_sl:.2f}")
            db.log_plot(
                prompt=passage, completion=rewrite,
                voice="", genre=target_genre,
                style=(tone_key or ""),
                notes=notes)
            n_logged += 1
            tone_label = (
                f" [{_tone_name(tone_key)}]" if tone_key else "")
            log(f"  [{n_logged}/{max_pairs}]{tone_label} kept — "
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
        "tones_used": list(tone_iter) if tones else [],
    }
