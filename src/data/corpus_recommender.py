"""Smart-pick corpus downloader.

Picks a small, well-justified set of catalog entries to download
based on the user's current state — intent, genres, tones, what's
already in the DB. The user has had to walk the full Library
dialog manually until now; this module recommends the 3-7 entries
that would best round out the dataset and skips everything else.

**Two-tier recommendation**:

  1. **Deterministic ranker** — always runs. Builds a candidate
     pool from the genre/tone taxonomies + writing-craft pointers
     for the recipe's intent, drops anything already ingested,
     scores by relevance + complementarity, returns the top N.

  2. **Optional LLM refinement** — when an LLM is configured, we
     pass it the deterministic shortlist + the user's current
     stats and ask it to pick the subset most worth downloading
     and explain each choice. The LLM can drop entries it thinks
     are redundant; it can't add entries outside the shortlist.
     Falls back to deterministic when no LLM is available, the
     LLM call fails, or the LLM's output is unparseable.

**What the recommender never does**:

  * Downloads anything itself — the caller (UI dialog) drives
    the download via :mod:`corpus_downloader` after user
    confirmation.
  * Suggests entries that aren't license-safe.
  * Suggests entries with broken / unreachable URLs (we don't
    probe; we trust the catalog. If a catalog entry is broken,
    it should be fixed in the catalog.)

**Public API**:

  * :class:`DownloadSuggestion` — one entry + reason + priority.
  * :func:`recommend_downloads` — main entry point.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set


@dataclass
class DownloadSuggestion:
    """One catalog entry the recommender thinks is worth using
    for the next training run.

    The name is historical — Smart Pick *also* recommends entries
    that are already ingested (no download needed) so the user
    can curate which of their ~100 ingested corpora to actually
    train on. ``requires_download`` distinguishes the two:
    ``True`` means "download then include for training",
    ``False`` means "already in the DB, just include in the
    training filter".
    """
    corpus_id: str
    name: str
    description: str
    license: str
    size_kb: int
    reason: str               # why we recommend it (user-facing)
    priority: int             # 1 = highest, 5 = lowest
    catalog_entry: Any = None  # the underlying CorpusEntry
    requires_download: bool = True  # True = not yet ingested


@dataclass
class RecommendationResult:
    """Diagnostic-rich result of one recommendation pass.

    The UI uses this to render *useful* empty states. When the
    suggestions list is empty, the diagnostic fields explain why —
    "you've already ingested all 24 horror entries" beats a
    generic "nothing to pick" message every time.
    """
    suggestions: List[DownloadSuggestion]
    candidate_pool_size: int = 0
    n_already_ingested: int = 0
    n_license_filtered: int = 0
    expanded_to_related: List[str] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)
    # The user-friendly summary the UI should show. Computed in
    # ``_compose_summary`` so the dialog doesn't have to format
    # diagnostic text inline.
    summary: str = ""


def _ingested_corpus_ids(db_path: Path) -> Set[str]:
    """Set of catalog ids that already have rows in the DB.

    Every downloaded row gets ``corpus_id=<id>`` written somewhere
    into its ``notes`` column at ingest time — the field can have
    a leading ``corpus_title=…`` prefix when the ingestion path
    that wrote it knew the row's title, so we substring-match
    rather than expecting the marker at position 0.
    """
    out: Set[str] = set()
    if not Path(db_path).exists():
        return out
    try:
        from src.data.rephrase_database import RephraseDatabase
        db = RephraseDatabase(db_path)
        with db._conn() as c:
            cur = c.execute(
                "SELECT DISTINCT notes FROM rephrases "
                "WHERE source_type = 'corpus' "
                "AND notes LIKE '%corpus_id=%'")
            for row in cur:
                notes = row["notes"] or ""
                m = re.search(r'corpus_id=(\S+)', notes)
                if m:
                    out.add(m.group(1))
    except Exception:
        return out
    return out


def _candidate_pool(*,
                    intent: str,
                    genres: List[str],
                    tones: List[str]) -> List[str]:
    """Build the universe of catalog ids worth considering.

    Pulls from:
      * Each ticked genre's exemplar corpora (from
        :mod:`src.data.genres`)
      * Each ticked genre's writing-craft pointers (so a horror
        recipe gets Lovecraft's *Supernatural Horror*, not just
        horror fiction)
      * Each ticked tone's exemplar corpora (from
        :mod:`src.data.tones`)

    De-duplicates while preserving genre-first ordering — the
    most-relevant candidates appear earlier in the returned list.
    Caller still has to filter against already-ingested.
    """
    seen: Set[str] = set()
    pool: List[str] = []

    try:
        from src.data import genres as genres_mod
    except Exception:
        genres_mod = None
    try:
        from src.data import tones as tones_mod
    except Exception:
        tones_mod = None

    if genres_mod is not None:
        for cid in genres_mod.corpora_for(genres or []):
            if cid not in seen:
                seen.add(cid); pool.append(cid)
        for cid in genres_mod.craft_corpora_for(genres or []):
            if cid not in seen:
                seen.add(cid); pool.append(cid)

    if tones_mod is not None and tones:
        for cid in tones_mod.corpora_for_tones(tones):
            if cid not in seen:
                seen.add(cid); pool.append(cid)

    return pool


# Adjacent-genre map for the fallback pool. When all entries for
# the user's selected genre are already ingested, we widen the net
# to closely-related genres so Smart Pick still has *something* to
# offer rather than going silent. Each value is sorted from most
# to least adjacent.
_ADJACENT_GENRES = {
    "horror":      ["gothic", "thriller", "weird"],
    "gothic":      ["horror", "romance"],
    "scifi":       ["fantasy", "adventure"],
    "fantasy":     ["scifi", "adventure"],
    "western":     ["frontier", "adventure"],
    "frontier":    ["western", "adventure", "literary"],
    "romance":     ["literary", "gothic"],
    "literary":    ["romance", "frontier"],
    "mystery":     ["thriller"],
    "thriller":    ["mystery", "horror"],
    "adventure":   ["scifi", "western", "fantasy"],
}


# Per-intent weight on craft documents. Voice intents care less
# about craft theory than literary or rephrase intents do — voice
# fine-tunes mostly need lots of in-voice prose.
_CRAFT_WEIGHT_BY_INTENT = {
    "voice": 0.3,
    "rephrase": 0.6,
    "plot": 0.9,
    "character": 0.7,
    "worldbuilding": 0.7,
    "chat": 0.5,
    "general": 0.6,
}


def _score_entry(entry,
                 *,
                 intent: str,
                 genres: List[str],
                 tones: List[str],
                 ingested: Set[str],
                 ingested_size_kb: int) -> float:
    """Heuristic score (0-1) for one catalog entry's relevance.

    Higher = more likely to round out the user's dataset usefully.
    Considers tag overlap with the user's selections, the entry's
    size relative to what's already ingested, and intent-aware
    weighting on craft documents.
    """
    if entry is None:
        return 0.0
    score = 0.5  # baseline

    tags = set(entry.tags or [])
    sel_genres_lower = {g.lower() for g in genres}
    sel_tones_lower = {t.lower() for t in tones}

    # Genre tag overlap.
    matched_genres = tags & sel_genres_lower
    if matched_genres:
        score += 0.15 * min(2, len(matched_genres))

    # Tone tag overlap (if any).
    if tones and (tags & sel_tones_lower):
        score += 0.1

    # Craft-document weighting per intent.
    if "craft" in tags or "writing-guide" in tags:
        score *= _CRAFT_WEIGHT_BY_INTENT.get(
            (intent or "general").lower(), 0.6)

    # Diminishing returns — when the user already has plenty of
    # ingested data, deprioritize bringing in more bulk.
    if ingested_size_kb > 5000:  # > 5 MB ingested
        if (entry.size_hint_kb or 0) > 1500:  # large entry
            score *= 0.7

    # Penalize gigantic HF datasets unless explicitly intended for
    # this user — the Training Studio caps at sensible row counts
    # but a 5 GB dataset feels like overkill for a smart-pick.
    if (entry.size_hint_kb or 0) > 200_000:
        score *= 0.4

    # If the same author / family is already ingested, prefer
    # different authors for breadth.
    if entry.author:
        author_low = entry.author.lower()
        for cid in ingested:
            from src.data.corpus_catalog import find_entry
            already = find_entry(cid)
            if already and (already.author or "").lower() == author_low:
                score *= 0.85
                break

    return max(0.0, min(1.0, score))


def _rationale(entry,
               *,
               intent: str,
               genres: List[str],
               tones: List[str]) -> str:
    """One-sentence "why we picked this" string for the UI."""
    tags = set(entry.tags or [])
    sel_genres_lower = {g.lower() for g in genres}
    sel_tones_lower = {t.lower() for t in tones}
    matched_g = tags & sel_genres_lower
    matched_t = tags & sel_tones_lower

    bits: List[str] = []
    if matched_g:
        bits.append(f"matches genre {sorted(matched_g)[0]}")
    if matched_t:
        bits.append(f"matches tone {sorted(matched_t)[0]}")
    if "craft" in tags or "writing-guide" in tags:
        bits.append(f"craft text — informs {intent} task")
    if entry.author:
        bits.append(f"by {entry.author}")
    if not bits:
        bits.append("relevant to your selection")

    size_b = entry.size_hint_kb or 0
    if size_b > 1024:
        bits.append(f"{size_b // 1024} MB")
    elif size_b > 0:
        bits.append(f"{size_b} KB")

    return "; ".join(bits)


def recommend_downloads_with_diagnosis(
        *,
        intent: str,
        genres: List[str],
        tones: List[str],
        db_path: Path,
        max_suggestions: int = 5,
        llm_generate: Optional[Callable[[str, str], str]] = None,
        allow_adjacent: bool = True,
        include_ingested: bool = True,
) -> RecommendationResult:
    """Curate the training-relevant subset of catalog entries.

    Despite the name, this isn't only about downloads. With
    ``include_ingested=True`` (default), already-downloaded
    catalog entries are scored alongside un-downloaded ones —
    Smart Pick uses this to drive the *training filter* on a DB
    that's already comprehensive. Each suggestion's
    ``requires_download`` flag tells the UI whether picking it
    triggers a download or just a filter toggle.

    Adjacent-genre fallback still applies when the primary pool
    has no candidates after filtering.
    """
    from src.data.corpus_catalog import find_entry, is_license_safe

    ingested = _ingested_corpus_ids(db_path)
    ingested_size_kb = sum(
        (find_entry(cid).size_hint_kb or 0)
        for cid in ingested if find_entry(cid) is not None)

    primary_pool = _candidate_pool(
        intent=intent, genres=genres, tones=tones)
    n_pool = len(primary_pool)
    n_already_ingested = sum(1 for c in primary_pool if c in ingested)
    n_license_filtered = 0

    # Score every candidate; mark whether it's already ingested so
    # the UI can render "include for training" vs "download then
    # include" actions. ``include_ingested=False`` reverts to the
    # download-only legacy behaviour for callers that need it.
    candidates: List[Tuple[float, Any, bool]] = []
    for cid in primary_pool:
        is_ingested = cid in ingested
        if is_ingested and not include_ingested:
            continue
        e = find_entry(cid)
        if e is None:
            continue
        if not is_license_safe(e.license or ""):
            n_license_filtered += 1
            continue
        score = _score_entry(
            e, intent=intent, genres=genres, tones=tones,
            ingested=ingested, ingested_size_kb=ingested_size_kb)
        candidates.append((score, e, is_ingested))

    expanded_to: List[str] = []
    notes: List[str] = []

    # Adjacent-genre fallback when the primary pool is empty.
    if not candidates and allow_adjacent and genres:
        for g in genres:
            for adj in _ADJACENT_GENRES.get(g.lower(), []):
                adj_pool = _candidate_pool(
                    intent=intent, genres=[adj], tones=[])
                for cid in adj_pool:
                    is_ingested = cid in ingested
                    if is_ingested and not include_ingested:
                        continue
                    e = find_entry(cid)
                    if e is None:
                        continue
                    if not is_license_safe(e.license or ""):
                        continue
                    score = _score_entry(
                        e, intent=intent, genres=[adj], tones=tones,
                        ingested=ingested,
                        ingested_size_kb=ingested_size_kb)
                    # Slight discount — adjacent genre is less
                    # relevant than the user's actual pick.
                    score *= 0.85
                    candidates.append((score, e, is_ingested))
                    expanded_to.append(adj)
        expanded_to = sorted(set(expanded_to))

    # Compose the diagnostic summary so the UI can render it.
    if not candidates:
        if n_pool == 0:
            summary = (
                "No catalog entries map to your selection. The "
                "genre/tone taxonomies cover the major fiction "
                "categories — pick at least one of those on Step 1.")
        else:
            summary = (
                f"Couldn't find any candidates "
                f"(pool size {n_pool}, "
                f"{n_license_filtered} filtered for license).")
        return RecommendationResult(
            suggestions=[],
            candidate_pool_size=n_pool,
            n_already_ingested=n_already_ingested,
            n_license_filtered=n_license_filtered,
            expanded_to_related=expanded_to,
            notes=notes,
            summary=summary,
        )

    # Rank + LLM-refine + truncate.
    candidates.sort(key=lambda x: -x[0])
    shortlist_pairs = [(e, ing) for _score, e, ing in candidates[
                        :max_suggestions * 2]]

    suggestions: List[DownloadSuggestion] = []
    if llm_generate is not None:
        # The LLM refiner only sees the entries; we re-attach the
        # ingested flag after picking so the UI knows whether each
        # pick needs downloading.
        shortlist = [e for e, _ing in shortlist_pairs]
        ing_lookup = {e.id: ing for e, ing in shortlist_pairs}
        suggestions = _llm_refine(
            shortlist=shortlist,
            intent=intent, genres=genres, tones=tones,
            ingested=ingested, ingested_size_kb=ingested_size_kb,
            max_suggestions=max_suggestions,
            llm_generate=llm_generate)
        for s in suggestions:
            s.requires_download = not ing_lookup.get(s.corpus_id, False)
    if not suggestions:
        for i, (e, is_ingested) in enumerate(
                shortlist_pairs[:max_suggestions]):
            suggestions.append(DownloadSuggestion(
                corpus_id=e.id,
                name=e.name,
                description=e.description or "",
                license=e.license or "",
                size_kb=e.size_hint_kb or 0,
                reason=_rationale(
                    e, intent=intent, genres=genres, tones=tones),
                priority=i + 1,
                catalog_entry=e,
                requires_download=not is_ingested,
            ))

    n_ingested_in_picks = sum(
        1 for s in suggestions if not s.requires_download)
    n_to_download = sum(
        1 for s in suggestions if s.requires_download)

    if expanded_to:
        notes.append(
            f"Smart Pick expanded into adjacent genres "
            f"({', '.join(expanded_to)}) since the primary genre "
            f"pool was thin.")

    parts = []
    if n_to_download:
        parts.append(f"{n_to_download} to download")
    if n_ingested_in_picks:
        parts.append(f"{n_ingested_in_picks} already in your DB")
    summary = (
        f"{len(suggestions)} pick(s) — "
        + ", ".join(parts)
        + (f". Expanded to: {', '.join(expanded_to)}."
           if expanded_to else "."))

    return RecommendationResult(
        suggestions=suggestions,
        candidate_pool_size=n_pool,
        n_already_ingested=n_already_ingested,
        n_license_filtered=n_license_filtered,
        expanded_to_related=expanded_to,
        notes=notes,
        summary=summary,
    )


def recommend_downloads(*,
                        intent: str,
                        genres: List[str],
                        tones: List[str],
                        db_path: Path,
                        max_suggestions: int = 5,
                        llm_generate: Optional[
                            Callable[[str, str], str]] = None,
                        ) -> List[DownloadSuggestion]:
    """Pick a small, well-justified set of corpora to download.

    The deterministic pass produces a ranked shortlist of up to
    ``max_suggestions * 2`` candidates. If ``llm_generate`` is
    provided, we ask the LLM to refine the shortlist down to
    ``max_suggestions`` and supply per-entry rationale. Falls
    back to the deterministic top N when the LLM is missing,
    fails, or returns unparseable output.

    Returns the suggestions ordered by priority (1 = highest).
    Thin wrapper around :func:`recommend_downloads_with_diagnosis`
    — call that directly to also get the human-readable summary
    explaining empty results.
    """
    return recommend_downloads_with_diagnosis(
        intent=intent, genres=genres, tones=tones,
        db_path=db_path, max_suggestions=max_suggestions,
        llm_generate=llm_generate,
    ).suggestions


def _llm_refine(*,
                shortlist: List[Any],
                intent: str,
                genres: List[str],
                tones: List[str],
                ingested: Set[str],
                ingested_size_kb: int,
                max_suggestions: int,
                llm_generate: Callable[[str, str], str],
                ) -> List[DownloadSuggestion]:
    """Ask the LLM to refine the shortlist. Returns ``[]`` on any
    failure so the caller falls back to the deterministic ranking
    without surfacing errors to the user."""
    if not shortlist:
        return []

    catalog_blob = "\n".join(
        f"- id={e.id} | {e.name[:60]} | "
        f"tags={','.join((e.tags or [])[:5])} | "
        f"author={e.author or ''} | "
        f"size_kb={e.size_hint_kb or 0} | "
        f"desc={(e.description or '')[:120]}"
        for e in shortlist)
    ingested_blob = ", ".join(sorted(ingested)[:30]) or "(nothing)"

    system = (
        "You curate training corpora for fine-tuning. Given a "
        "shortlist of public-domain texts, the user's training "
        "intent, and what's already ingested, pick the subset "
        "(at most {max_n}) that best complements existing data. "
        "Be selective — do not pick everything. Skip any that are "
        "redundant with what's already ingested. Output ONLY in "
        "this format:\n"
        "PICK: <corpus_id> | <one-sentence reason>\n"
        "PICK: <corpus_id> | <one-sentence reason>\n"
        "...\n"
        "(One PICK line per chosen entry; nothing else.)"
    ).format(max_n=max_suggestions)

    prompt = (
        f"Training intent: {intent}\n"
        f"Genres: {', '.join(genres) or '(none)'}\n"
        f"Tones: {', '.join(tones) or '(none)'}\n"
        f"Already ingested ids: {ingested_blob}\n"
        f"Already-ingested data size (KB): {ingested_size_kb}\n\n"
        f"Shortlist (pick at most {max_suggestions}):\n"
        f"{catalog_blob}\n")

    try:
        raw = llm_generate(prompt, system) or ""
    except Exception:
        return []

    picks: List[DownloadSuggestion] = []
    valid_ids = {e.id: e for e in shortlist}
    for i, line in enumerate(raw.splitlines()):
        m = re.match(
            r'^\s*PICK\s*:\s*([A-Za-z0-9_-]+)\s*\|\s*(.+?)\s*$',
            line, re.IGNORECASE)
        if not m:
            continue
        cid = m.group(1).strip()
        reason = m.group(2).strip()
        if cid not in valid_ids:
            continue  # LLM hallucinated an id outside the shortlist
        e = valid_ids[cid]
        picks.append(DownloadSuggestion(
            corpus_id=cid,
            name=e.name,
            description=e.description or "",
            license=e.license or "",
            size_kb=e.size_hint_kb or 0,
            reason=reason,
            priority=len(picks) + 1,
            catalog_entry=e,
        ))
        if len(picks) >= max_suggestions:
            break

    return picks
