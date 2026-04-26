"""Pacing analyzer — compute CONLIT-comparable stats on any text.

CONLIT (Piper et al., Figshare 21166171) ships per-book averages for
avg sentence length, avg word length, and the Tuldava lexical-
complexity index. This module computes the *same* metrics on a user-
supplied passage so the two are directly comparable.

Two consumer entry points:

  * ``analyze_text(text)`` — pure-Python, no NLP deps. Fast, runs on
    a chapter in a few ms. Good enough for pacing-level comparisons.
  * ``compare_to_genre(stats, genre_key)`` — diff against the CONLIT
    baseline, including a z-score against the genre's std-dev so the
    user sees whether they're inside or outside genre norms.

What we deliberately *don't* do here: full POS / supersense analysis.
The CONLIT_POS.csv and CONLIT_SUPERSENSE.csv files have those, but
computing matching stats from scratch needs spaCy and is heavier.
The three metrics this module covers are the most informative for
pacing — Piper's own R script leans on them — and they're all derivable
from cheap regex-level parsing.
"""

from __future__ import annotations

import math
import re
from typing import Any, Dict, Optional


# Sentence boundary heuristic. Real sentence segmentation needs spaCy
# or NLTK, but for pacing-level numbers (sentences-per-paragraph
# averaged over a chapter), a regex on punctuation + whitespace is
# accurate enough. We split on ".!?" followed by whitespace so
# abbreviations like "Mr. Smith" stay intact when followed by a
# capital with no whitespace.
_SENT_SPLIT = re.compile(r'(?<=[.!?])\s+(?=[A-Z"\'(\[])')


# Word tokenizer — letters + apostrophes, drops bare numbers and
# punctuation. CONLIT's token_count uses a similar word-level grain.
_WORD_RE = re.compile(r"\b[A-Za-z][A-Za-z'’]*\b")


def analyze_text(text: str) -> Dict[str, Any]:
    """Compute CONLIT-comparable summary statistics for a passage.

    Returns a dict with::

        {
          "token_count":          int,    # word count
          "sentence_count":       int,    # estimated sentences
          "avg_sentence_length":  float,  # words per sentence
          "avg_word_length":      float,  # chars per word
          "type_token_ratio":     float,  # vocabulary diversity
          "tuldava_score":        float,  # log(N) / log(V); CONLIT field
          "dialogue_ratio":       float,  # fraction of words inside quotes
        }

    Returns an empty dict for empty / non-textual input.
    """
    if not text or not text.strip():
        return {}

    sentences = [s.strip() for s in _SENT_SPLIT.split(text) if s.strip()]
    words = _WORD_RE.findall(text)
    if not sentences or not words:
        return {}

    token_count = len(words)
    sentence_count = len(sentences)
    avg_sentence_length = token_count / sentence_count
    avg_word_length = sum(len(w) for w in words) / token_count

    types = {w.lower() for w in words}
    type_token_ratio = len(types) / token_count

    # Tuldava index: log(tokens) / log(types). CONLIT publishes this
    # column. Higher = more lexically diverse / harder vocabulary.
    # Guard against pathological inputs (single-type passages).
    if len(types) > 1:
        tuldava_score = math.log(token_count) / math.log(len(types))
    else:
        tuldava_score = 0.0

    # Dialogue ratio — words inside double-quotes / total words.
    # Useful pacing signal: thrillers + romance lean dialogue-heavy,
    # literary fiction interior-monologue heavy.
    dialogue_words = 0
    for match in re.finditer(r'"([^"]+)"', text):
        dialogue_words += len(_WORD_RE.findall(match.group(1)))
    dialogue_ratio = dialogue_words / token_count

    return {
        "token_count": token_count,
        "sentence_count": sentence_count,
        "avg_sentence_length": round(avg_sentence_length, 3),
        "avg_word_length": round(avg_word_length, 3),
        "type_token_ratio": round(type_token_ratio, 4),
        "tuldava_score": round(tuldava_score, 3),
        "dialogue_ratio": round(dialogue_ratio, 4),
    }


def compare_to_genre(
    stats: Dict[str, Any],
    genre_key: str,
    conlit_genre_stats: Dict[str, Any],
) -> Dict[str, Any]:
    """Diff a passage's stats against a CONLIT genre baseline.

    Args:
        stats: output of ``analyze_text``.
        genre_key: canonical genre (mystery / scifi / romance / literary).
        conlit_genre_stats: ``by_genre`` dict from
            ``conlit_loader.get_genre_stats_cached()``.

    Returns a structured comparison::

        {
          "genre": "Mystery",
          "baseline_n_books": 234,
          "summary": "Sentences run longer than mystery norm by +5.4 words …",
          "deltas": {
              "avg_sentence_length": {
                  "value": 19.2, "baseline": 13.8, "delta": +5.4,
                  "stdev": 2.04, "z_score": +2.65,
                  "direction": "longer",
                  "outside_norm": True,   # |z| ≥ 1.5
              },
              ...
          },
        }

    Empty deltas mean the genre isn't covered by CONLIT (horror /
    western / fantasy fall through silently).
    """
    baseline = conlit_genre_stats.get(genre_key)
    if not baseline or not stats:
        return {}

    deltas: Dict[str, Any] = {}
    for field, direction_pair in (
        ("avg_sentence_length", ("longer", "shorter")),
        ("avg_word_length",     ("longer", "shorter")),
        ("tuldava_score",       ("more lexically dense",
                                 "lexically simpler")),
    ):
        if field not in stats:
            continue
        mean_key = f"{field}__mean"
        if mean_key not in baseline:
            continue
        baseline_mean = float(baseline[mean_key])
        baseline_stdev = float(baseline.get(f"{field}__stdev", 0.0) or 0.0)
        observed = float(stats[field])
        delta = observed - baseline_mean
        z = (delta / baseline_stdev) if baseline_stdev > 0 else 0.0
        direction = direction_pair[0] if delta > 0 else direction_pair[1]
        deltas[field] = {
            "value": round(observed, 3),
            "baseline": round(baseline_mean, 3),
            "stdev": round(baseline_stdev, 3),
            "delta": round(delta, 3),
            "z_score": round(z, 2),
            "direction": direction,
            "outside_norm": abs(z) >= 1.5,
        }

    # Build a one-line plain-English summary. Highlights the most
    # outside-norm dimension — that's usually the actionable one.
    summary_bits = []
    for field, d in sorted(deltas.items(),
                           key=lambda x: -abs(x[1]["z_score"])):
        if not d["outside_norm"]:
            continue
        nice = field.replace("_", " ").replace("avg ", "")
        summary_bits.append(
            f"{nice} runs {d['direction']} than {genre_key} norm "
            f"by {abs(d['delta']):.1f} (z={d['z_score']:+.1f})")
    summary = ("; ".join(summary_bits[:2])
               if summary_bits
               else f"Pacing within {genre_key} genre norms (no z≥1.5).")

    return {
        "genre": baseline.get("label", genre_key),
        "baseline_n_books": baseline.get("n_books", 0),
        "summary": summary,
        "deltas": deltas,
    }


def comparison_report(
    text: str,
    genre_key: str,
    conlit_genre_stats: Dict[str, Any],
) -> Dict[str, Any]:
    """One-shot convenience: analyze + compare in one call.

    Returns ``{"stats": {...}, "comparison": {...}, "n_words": N}``
    or ``{}`` when the text is empty / the genre isn't in CONLIT.
    """
    stats = analyze_text(text)
    if not stats:
        return {}
    cmp = compare_to_genre(stats, genre_key, conlit_genre_stats)
    return {
        "stats": stats,
        "comparison": cmp,
        "n_words": stats.get("token_count", 0),
    }
