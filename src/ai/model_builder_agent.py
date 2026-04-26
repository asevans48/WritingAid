"""Model Builder Agent — turns a user's plain-English description of
the model they want into a concrete training recipe.

The recipe specifies:
  * Which source types to combine (rephrase, chat_writing, corpus, …)
  * Which catalog corpora to recommend downloading
  * Which export format to use (instruction SFT, plot prompt→story, DPO)
  * A suggested base model and hyperparameters
  * A natural-language summary the UI shows to the user

When the OS has an LLM configured, the agent uses it to interpret
the description; otherwise it falls back to deterministic keyword
matching so the studio works fully offline.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from src.data.corpus_catalog import CATALOG, CorpusEntry
from src.data.rephrase_database import (
    SOURCE_REPHRASE, SOURCE_CHAT_WRITING, SOURCE_CHAT_GENERAL,
    SOURCE_CORPUS, SOURCE_AGENT,
    SOURCE_WORLDBUILDING, SOURCE_CHARACTER, SOURCE_PLOT,
)
from src.data import genres as genre_taxonomy


# ── Built-in catalog awareness ────────────────────────────────
# The agent picks base models from the same catalog the Training
# Studio uses, after applying the user's include/exclude filter. This
# guarantees the agent never recommends a model the user has hidden.
def _included_training_ids() -> List[str]:
    try:
        from src.ui.model_picker_widget import included_training_base_model_ids
        return list(included_training_base_model_ids())
    except Exception:
        return []


def _pick_first_included(*candidates: str) -> Optional[str]:
    """Return the first candidate that the user hasn't excluded.

    Used by the heuristic backbone to map (intent, medium) preferences
    to a concrete base model. When none of the candidates is included,
    falls back to the first included model overall — and finally to
    None when the user has somehow excluded everything (defensive: the
    manager dialog refuses to save an all-empty selection).
    """
    included = _included_training_ids()
    if not included:
        return None
    included_set = set(included)
    for c in candidates:
        if c in included_set:
            return c
    return included[0]


# ── Corpus-aware base model recommendation ───────────────────
# Empirical rule of thumb: a LoRA fine-tune nudges weights toward the
# user's data. With too few examples on a too-large base, the signal
# gets drowned and the model "regresses" toward its pretraining. Match
# base size to dataset size, then bias by family on intent (Gemma for
# literary voice, Phi for reasoning/plot, Qwen for structured gen).

_CORPUS_SIZE_BANDS = (
    # (max_size_exclusive, band_name, human-readable phrase)
    (200, "tiny", "very small"),
    (1000, "small", "small but workable"),
    (5000, "medium", "mid-size"),
    (float("inf"), "large", "large"),
)

_BAND_CANDIDATES = {
    # Each entry maps an (intent-family) preference to an ordered list
    # of HuggingFace ids. The first one that survives the user's
    # exclusion filter wins. Rule of thumb: ≥10× more examples than
    # base parameters (in millions) for a meaningful voice transfer.
    "tiny": {
        "gemma": ["google/gemma-4-E2B-it",
                  "google/gemma-2-2b-it",
                  "meta-llama/Llama-3.2-1B-Instruct",
                  "Qwen/Qwen2.5-1.5B-Instruct"],
        "phi":   ["microsoft/Phi-3-mini-4k-instruct",
                  "Qwen/Qwen2.5-1.5B-Instruct"],
        "qwen":  ["Qwen/Qwen2.5-1.5B-Instruct",
                  "google/gemma-4-E2B-it",
                  "google/gemma-2-2b-it"],
    },
    "small": {
        "gemma": ["google/gemma-4-E2B-it",
                  "google/gemma-2-2b-it",
                  "google/gemma-3-4b-it",
                  "google/gemma-4-E4B-it"],
        "phi":   ["microsoft/Phi-4-mini-instruct",
                  "microsoft/Phi-3-mini-4k-instruct",
                  "Qwen/Qwen2.5-3B-Instruct"],
        "qwen":  ["Qwen/Qwen2.5-3B-Instruct",
                  "Qwen/Qwen3-4B",
                  "google/gemma-4-E2B-it",
                  "google/gemma-2-2b-it"],
    },
    "medium": {
        "gemma": ["google/gemma-3-4b-it",
                  "google/gemma-4-E4B-it",
                  "google/gemma-4-E2B-it",
                  "google/gemma-2-2b-it"],
        "phi":   ["microsoft/Phi-4-mini-instruct",
                  "microsoft/Phi-3-mini-4k-instruct"],
        "qwen":  ["Qwen/Qwen2.5-7B-Instruct",
                  "Qwen/Qwen3-8B",
                  "Qwen/Qwen2.5-3B-Instruct"],
    },
    "large": {
        "gemma": ["google/gemma-3-12b-it",
                  "google/gemma-4-E4B-it",
                  "google/gemma-3-4b-it"],
        "phi":   ["microsoft/Phi-4-mini-instruct"],
        "qwen":  ["Qwen/Qwen2.5-7B-Instruct",
                  "Qwen/Qwen3-14B",
                  "Qwen/Qwen3-8B"],
    },
}


def _intent_family(intent: str) -> str:
    """Map a training intent to a model family that suits it best."""
    if intent in ("worldbuilding", "character"):
        return "qwen"   # structured generation, named fields
    if intent in ("plot", "qa"):
        return "phi"    # reasoning-trained
    return "gemma"      # voice, literary prose


def _size_band(corpus_size: int) -> str:
    for cap, name, _phrase in _CORPUS_SIZE_BANDS:
        if corpus_size < cap:
            return name
    return "large"


# ── Host-aware LoRA hyperparameter recommendation ────────────
# We pick LoRA rank ``r`` (and derive ``alpha = 2 * r`` per the QLoRA
# paper convention) by combining three signals:
#   1. Host capabilities — total RAM/VRAM on the box that will run
#      the training. CUDA → use VRAM. MPS / Apple Silicon → unified
#      memory, return system RAM. CPU → system RAM. Smaller machines
#      get a smaller r so the adapter weights, gradients, and Adam
#      optimizer state actually fit.
#   2. Base model size — Gemma 4 31B chews more RAM than Gemma 2 2B,
#      and QLoRA's 4-bit loading roughly quarters that footprint. We
#      look up size from TRAINING_BASE_MODELS when possible; fall back
#      to a regex on the model id (``-2b-``, ``-7B-`` etc.) when not.
#   3. Corpus size — high r on a tiny corpus overfits. We cap r above
#      what the data can support, regardless of how much hardware the
#      host has.

def _detect_device_and_memory() -> tuple:
    """Return ``(device_name, total_gb)`` for the host's strongest device.

    Order: CUDA → MPS (unified) → CPU. RAM detection uses ``psutil`` if
    available; falls back to conservative defaults so this is always
    safe to call.
    """
    try:
        import torch
        if torch.cuda.is_available():
            try:
                props = torch.cuda.get_device_properties(0)
                return ("cuda", props.total_memory / (1024 ** 3))
            except Exception:
                return ("cuda", 12.0)  # rough mid-tier GPU fallback
        if (hasattr(torch.backends, "mps")
                and torch.backends.mps.is_available()):
            try:
                import psutil
                return ("mps", psutil.virtual_memory().total / (1024 ** 3))
            except Exception:
                return ("mps", 16.0)
    except Exception:
        pass
    try:
        import psutil
        return ("cpu", psutil.virtual_memory().total / (1024 ** 3))
    except Exception:
        return ("cpu", 8.0)


def _lookup_base_model_size_gb(model_id: str) -> float:
    """Pull the catalog's size estimate for a base model, with fallback.

    Returns 0 only when we have no information at all; callers should
    treat that as "skip the size-aware part of the calculation."
    """
    if not model_id:
        return 0.0
    try:
        from src.ui.model_picker_widget import TRAINING_BASE_MODELS
        for m in TRAINING_BASE_MODELS:
            if m.model_id == model_id:
                return float(m.size_gb)
    except Exception:
        pass
    # Last resort: parse param count from the model id.
    import re
    match = re.search(r"(\d+(?:\.\d+)?)[Bb]", model_id)
    if match:
        params_b = float(match.group(1))
        return params_b * 2.0  # ~2 bytes per param at bf16
    return 0.0


def recommend_lora_params(
    base_model_id: str = "",
    use_qlora: bool = False,
    corpus_size: int = 0,
) -> dict:
    """Pick LoRA rank and alpha based on host hardware + data size.

    Args:
        base_model_id: HuggingFace id of the base model. Empty →
            assume a mid-size 7B-class model for sizing.
        use_qlora: If True, the base model is loaded 4-bit so its RAM
            footprint is roughly quartered.
        corpus_size: Number of *eligible* training rows. 0 means
            unknown — we skip the corpus cap and just size by hardware.

    Returns a dict with keys ``r``, ``alpha``, ``device``,
    ``available_gb``, ``base_model_gb``, ``headroom_gb``,
    ``capped_by`` (str), ``rationale`` (multi-line string ready to
    show in the UI).
    """
    device, total_gb = _detect_device_and_memory()
    raw_base_gb = _lookup_base_model_size_gb(base_model_id) or 12.0
    effective_base_gb = (raw_base_gb / 4.0) if use_qlora else raw_base_gb

    # Reserve headroom for: dataset + activations + optimizer state +
    # OS overhead. ~4GB is a defensible floor that keeps the trainer
    # from OOM'ing on the way through the first batch.
    overhead_gb = 4.0
    headroom_gb = max(0.0, total_gb - effective_base_gb - overhead_gb)

    # Hardware-driven r ceiling. Each step roughly doubles adapter
    # memory; the buckets are calibrated against "what fits with the
    # base model + Adam optimizer state on a typical machine".
    if headroom_gb < 1.5:
        r_hardware = 4
    elif headroom_gb < 4:
        r_hardware = 8
    elif headroom_gb < 10:
        r_hardware = 16
    elif headroom_gb < 24:
        r_hardware = 32
    else:
        r_hardware = 64

    # Corpus-driven r ceiling. Higher rank == more adapter capacity ==
    # more risk of memorizing a tiny dataset. Capping by data size is
    # the same defensive reasoning behind ``recommend_base_for_corpus``.
    if corpus_size <= 0:
        r_corpus = 64  # unknown — let hardware decide
        corpus_phrase = "(no corpus size hint)"
    elif corpus_size < 200:
        r_corpus = 4
        corpus_phrase = f"only {corpus_size} examples — keep r tiny"
    elif corpus_size < 1000:
        r_corpus = 8
        corpus_phrase = f"{corpus_size} examples fits r=8 cleanly"
    elif corpus_size < 5000:
        r_corpus = 16
        corpus_phrase = f"{corpus_size} examples can push r=16"
    else:
        r_corpus = 32
        corpus_phrase = f"{corpus_size}+ examples gives r=32 headroom"

    if r_corpus < r_hardware:
        r = r_corpus
        capped_by = "corpus size"
    else:
        r = r_hardware
        capped_by = "hardware"

    # alpha — QLoRA paper convention. Some popular recipes use alpha = r
    # (no scaling); we follow the 2× convention that PEFT defaults to
    # for r=8 (alpha=16) and which generalizes well to higher ranks.
    alpha = 2 * r

    qlora_note = ""
    if use_qlora:
        qlora_note = (
            f" QLoRA loads the base 4-bit "
            f"({raw_base_gb:.1f}GB → {effective_base_gb:.1f}GB).")

    rationale_lines = [
        f"Detected {device.upper()} with ~{total_gb:.0f}GB available memory.",
        f"Base model footprint: {effective_base_gb:.1f}GB.{qlora_note}",
        f"Headroom after ~{overhead_gb:.0f}GB OS/dataset overhead: "
        f"{headroom_gb:.1f}GB.",
        f"Hardware can support r={r_hardware}; "
        f"corpus side: {corpus_phrase}.",
        f"Picking r={r} (capped by {capped_by}), "
        f"alpha={alpha} (2×r per QLoRA paper).",
    ]

    return {
        "r": r,
        "alpha": alpha,
        "device": device,
        "available_gb": round(total_gb, 1),
        "base_model_gb": round(effective_base_gb, 2),
        "headroom_gb": round(headroom_gb, 1),
        "capped_by": capped_by,
        "rationale": "\n".join(rationale_lines),
    }


def recommend_epochs(
    corpus_size: int = 0,
    intent: str = "voice",
    lora_r: int = 8,
) -> dict:
    """Pick a number of training epochs that fits the data + task + r.

    The classic LoRA heuristic is "2-3 epochs for most fine-tunes."
    We tighten that with three signals:

      * **Corpus size** — small corpora benefit from more passes
        (the model needs to see each example more than once); huge
        corpora overfit if you stay too long.
      * **Intent** — structured generation (plot / worldbuilding /
        character / Q&A) tends to need an extra pass over voice/style
        imitation, where a couple of passes already imprint the
        author's prose.
      * **LoRA r** — high-rank adapters have more capacity, so they
        memorize faster. We trim an epoch off when r ≥ 32 to avoid
        the rapid overfitting that comes with higher capacity.

    Returns ``{"epochs": int, "rationale": str}``. ``epochs`` is
    clamped to ``[1, 6]`` — the trainer accepts up to 20, but past 6
    LoRA fine-tunes almost always overfit on consumer datasets.
    """
    # Corpus size → base epochs. Buckets calibrated against community
    # rules of thumb for SFT on instruction-tuned bases.
    if corpus_size <= 0:
        epochs_base = 3            # unknown → middle-of-the-road
        size_phrase = "(no corpus size hint, defaulting to 3)"
    elif corpus_size < 100:
        epochs_base = 5
        size_phrase = (f"only {corpus_size} examples — needs more passes")
    elif corpus_size < 500:
        epochs_base = 4
        size_phrase = (f"{corpus_size} examples — moderate repetition")
    elif corpus_size < 2000:
        epochs_base = 3
        size_phrase = (f"{corpus_size} examples — standard 3 passes")
    elif corpus_size < 10000:
        epochs_base = 2
        size_phrase = (f"{corpus_size} examples — 2 passes is plenty")
    else:
        epochs_base = 1
        size_phrase = (f"{corpus_size}+ examples — one pass is enough")

    # Intent modifier
    if intent in ("plot", "qa"):
        intent_bonus = 1
        intent_phrase = (f"+1 for {intent} (structured output, "
                         f"more passes help)")
    elif intent in ("worldbuilding", "character"):
        intent_bonus = 1
        intent_phrase = (f"+1 for {intent} "
                         f"(typed generation, more passes help)")
    else:
        intent_bonus = 0
        intent_phrase = f"voice intent (no epoch bonus)"

    # High-rank adapters memorize fast — trim an epoch to dodge overfit.
    if lora_r >= 32:
        rank_adj = -1
        rank_phrase = (f"-1 because r={lora_r} ≥ 32 "
                       f"(high-capacity adapter overfits faster)")
    else:
        rank_adj = 0
        rank_phrase = f"r={lora_r} → no rank adjustment"

    epochs = max(1, min(6, epochs_base + intent_bonus + rank_adj))

    rationale_lines = [
        f"Corpus: {size_phrase} → base {epochs_base}",
        f"Intent: {intent_phrase}",
        f"Rank: {rank_phrase}",
        f"Picked epochs={epochs} (clamped to [1, 6]).",
    ]

    return {
        "epochs": epochs,
        "rationale": "\n".join(rationale_lines),
    }


def recommend_base_for_corpus(
    corpus_size: int,
    intent: str = "voice",
    medium: str = "books",
) -> Tuple[str, str]:
    """Pick a base model that fits the available training data.

    Args:
        corpus_size: how many *eligible* rows the trainer would see
            (after rating + source filters). 0 is allowed and produces
            a "no data yet" recommendation.
        intent: voice | plot | qa | worldbuilding | character | both
        medium: books | movies | tv | short | mixed (currently unused
            but kept in the signature for future per-medium tweaks).

    Returns:
        ``(model_id, explanation)``. The model_id is guaranteed to be
        in the user's allowed list (or empty when they've excluded
        everything — the caller can decide what to do then).

    The explanation is short and user-facing — the Training Studio
    surfaces it next to the stats so the user knows *why* a particular
    base was picked and can override if they disagree.
    """
    band = _size_band(max(0, int(corpus_size)))
    family = _intent_family(intent)
    candidates = _BAND_CANDIDATES[band].get(family, [])
    chosen = _pick_first_included(*candidates) or ""

    if corpus_size <= 0:
        why = ("No eligible training rows yet — collect more rephrases, "
               "rate them, or add a corpus before training.")
    elif band == "tiny":
        why = (f"Only {corpus_size} examples — start with a small "
               f"base so the LoRA can imprint your style instead of "
               f"getting drowned. Move up after you collect more data.")
    elif band == "small":
        why = (f"{corpus_size} examples is a sweet spot for a 2-4B "
               f"base. Trains in minutes; voice transfer is clear.")
    elif band == "medium":
        why = (f"{corpus_size} examples can push a mid-size base — "
               f"go for higher quality, training takes longer.")
    else:  # large
        why = (f"{corpus_size}+ examples gives you headroom for a "
               f"larger base. Expect longer training but stronger "
               f"voice and structure capture.")

    if intent in ("plot", "qa"):
        why += " Phi family chosen for its reasoning bias."
    elif intent in ("worldbuilding", "character"):
        why += " Qwen family chosen for structured-generation strength."
    elif chosen.startswith("google/gemma"):
        why += " Gemma family chosen for literary prose."

    return chosen, why


@dataclass
class TrainingRecipe:
    summary: str = ""                                  # 1–2 sentence rationale
    intent: str = "voice"                              # voice | plot | both | qa | worldbuilding | character
    medium: str = "books"                              # books | movies | tv | mixed | short
    source_types: List[str] = field(default_factory=list)
    recommended_corpora: List[str] = field(default_factory=list)  # corpus ids
    export_format: str = "instruction"                 # instruction | chat | dpo | plot_prompt
    base_model: str = "google/gemma-2-2b-it"
    epochs: int = 2
    learning_rate: float = 2e-4
    batch_size: int = 1
    lora_r: int = 8
    min_rating: str = "good"

    # Genre + author / comp suggestions (added so the agent can advise
    # the user on what additional sources to bring in). All are
    # CATALOG-validated when populated by the LLM-refine path.
    detected_genres: List[str] = field(default_factory=list)
    recommended_authors: List[str] = field(default_factory=list)
    recommended_comps: List[str] = field(default_factory=list)
    recommended_craft: List[str] = field(default_factory=list)  # craft corpus ids

    # When > 1, repeat user-voice rows N times during JSONL export so
    # the trained LoRA imprints the user's style instead of being
    # overwhelmed by larger genre corpora. The Training Studio reads
    # this and threads it through ``RephraseDatabase.export_jsonl``.
    user_voice_oversample: int = 1


# ── Heuristic backbone ────────────────────────────────────────

_INTENT_KEYWORDS = {
    "voice": ["voice", "style", "imitate", "tone", "prose", "writing style",
              "my voice", "in the style"],
    "plot": ["plot", "premise", "outline", "structure", "story arc",
             "synopsis", "beats", "from a prompt", "writing prompt"],
    "qa": ["chat", "answer", "q&a", "qa", "respond", "dialogue", "assistant"],
    "worldbuilding": ["worldbuilding", "world building", "lore", "setting",
                      "faction", "kingdom", "magic system", "geography",
                      "culture", "place", "location", "ecosystem"],
    "character": ["character", "protagonist", "antagonist", "love interest",
                  "backstory", "cast", "personality", "arc", "voice profile"],
}

_MEDIUM_KEYWORDS = {
    "movies": ["movie", "film", "screenplay", "feature", "cinema"],
    "tv": ["tv", "show", "episode", "series", "season", "sitcom",
           "drama series"],
    "books": ["book", "novel", "novella", "long-form", "manuscript"],
    "short": ["short story", "flash fiction", "fable", "tale"],
    "mixed": ["all", "mix", "everything", "varied"],
}

# Genre → corpus map is now sourced from src.data.genres so the
# Training Studio's checkbox UI, the agent's recipe builder, and the
# recipe summary all share the same canonical taxonomy. Aliases and
# misspellings ("horro", "westren", "sci-fi", "thrler") live there too.


def _heuristic_recipe(description: str, *,
                      goal_hint: str = "",
                      medium_hint: str = "",
                      corpus_size: int = 0) -> TrainingRecipe:
    text = (description or "").lower()
    rec = TrainingRecipe()

    # Detect intent
    scores = {k: 0 for k in _INTENT_KEYWORDS}
    for intent, kws in _INTENT_KEYWORDS.items():
        for kw in kws:
            if kw in text:
                scores[intent] += 1
    if goal_hint:
        scores[goal_hint] = scores.get(goal_hint, 0) + 5
    rec.intent = max(scores, key=scores.get) if any(scores.values()) else "voice"

    # Detect medium
    medium_scores = {k: 0 for k in _MEDIUM_KEYWORDS}
    for medium, kws in _MEDIUM_KEYWORDS.items():
        for kw in kws:
            if kw in text:
                medium_scores[medium] += 1
    if medium_hint:
        medium_scores[medium_hint] = medium_scores.get(medium_hint, 0) + 5
    rec.medium = (max(medium_scores, key=medium_scores.get)
                  if any(medium_scores.values()) else "books")

    # Source-type mix based on intent
    if rec.intent == "voice":
        rec.source_types = [SOURCE_REPHRASE, SOURCE_CHAT_WRITING, SOURCE_CORPUS]
        rec.export_format = "instruction"
    elif rec.intent == "plot":
        rec.source_types = [SOURCE_CORPUS, SOURCE_PLOT]
        rec.export_format = "plot_prompt"
        rec.epochs = 3
    elif rec.intent == "qa":
        rec.source_types = [SOURCE_CHAT_GENERAL, SOURCE_CHAT_WRITING]
        rec.export_format = "chat"
    elif rec.intent == "worldbuilding":
        rec.source_types = [SOURCE_WORLDBUILDING, SOURCE_AGENT]
        rec.export_format = "instruction"
        rec.epochs = 3
    elif rec.intent == "character":
        rec.source_types = [SOURCE_CHARACTER, SOURCE_AGENT]
        rec.export_format = "instruction"
        rec.epochs = 3
    else:  # both
        rec.source_types = [SOURCE_REPHRASE, SOURCE_CHAT_WRITING,
                            SOURCE_CORPUS]
        rec.export_format = "instruction"

    if "avoid" in text or "preference" in text or "don't" in text:
        rec.export_format = "dpo"
        rec.summary += "Detected avoidance intent — switching to DPO. "

    # Recommend corpora — match by purpose + medium + genre keywords.
    # Worldbuilding/character intents don't need fiction corpora to learn
    # the *task*, but we still surface a couple of richly-described
    # narratives so the model picks up evocative description style.
    matched: List[CorpusEntry] = []
    for entry in CATALOG:
        if rec.intent in ("voice", "qa") and entry.purpose == "plot":
            continue
        if rec.intent == "plot" and entry.purpose == "voice":
            continue
        if rec.intent in ("worldbuilding", "character"):
            # Prefer voice/both corpora — they have descriptive prose.
            if entry.purpose == "plot":
                continue
        if rec.medium not in (entry.medium, "mixed", "books") \
                and entry.medium != "mixed":
            # allow books fallback if medium is "books"
            if not (rec.medium == "books" and entry.medium == "books"):
                continue
        matched.append(entry)

    # Genre-specific bumps — fuzzy-match the description against the
    # canonical taxonomy (handles "horro", "westren", "sci-fi" etc.)
    # and MOVE matched genres' corpora to the front of ``matched``
    # so the recipe surfaces genre-relevant works first. Multiple
    # genres are supported — they layer in order, so the last-detected
    # genre's corpora end up at the very top.
    detected = genre_taxonomy.match_genres(text)
    rec.detected_genres = detected
    for genre_key in detected:
        for cid in reversed(genre_taxonomy.GENRES[genre_key]["corpora"]):
            e = next((c for c in CATALOG if c.id == cid), None)
            if e is None:
                continue
            if e in matched:
                matched.remove(e)
            matched.insert(0, e)
    # Surface genre-specific writing-craft documents too — Poe's
    # Philosophy of Composition for horror/mystery, Lovecraft's
    # Supernatural Horror for weird, etc.
    rec.recommended_craft = genre_taxonomy.craft_corpora_for(detected)
    rec.recommended_authors = genre_taxonomy.authors_for(detected)
    rec.recommended_comps = genre_taxonomy.comps_for(detected)

    # Always include at least one multi-narrative corpus when available
    multi = [e for e in CATALOG if e.narratives >= 1000]
    for e in multi[:2]:
        if e not in matched:
            matched.append(e)

    rec.recommended_corpora = [e.id for e in matched[:6]]

    # Hyperparameter heuristics
    if rec.intent == "voice":
        rec.lora_r = 16
        rec.epochs = 2
        # When training "in my voice", the user's rephrase data should
        # dominate the loss. Genre corpora are added as background
        # texture; without oversampling, a 100k-token genre corpus
        # would drown a 5k-token user dataset. 8× is a reasonable
        # default that keeps the user's voice the dominant signal
        # without ignoring the corpora entirely.
        rec.user_voice_oversample = 8
    elif rec.intent == "plot":
        rec.lora_r = 8
        rec.epochs = 3
        rec.learning_rate = 1e-4
    elif rec.intent in ("worldbuilding", "character"):
        # These tasks tend to have less training data — small adapter,
        # more epochs to compensate, lower LR for stability.
        rec.lora_r = 8
        rec.epochs = 4
        rec.learning_rate = 1e-4

    # Pick a base model that fits BOTH the user's intent AND the size
    # of their training data. ``recommend_base_for_corpus`` enforces:
    #   - exclusion filter (from Manage Built-in Models dialog)
    #   - size band: tiny <200, small <1000, medium <5000, else large
    #   - family bias: Phi for plot/qa, Qwen for worldbuilding/character,
    #     Gemma for voice/literary
    # When corpus_size is unknown (caller didn't pass it) we default to
    # the "small" band — a safe sweet spot for most users.
    effective_size = corpus_size if corpus_size > 0 else 500
    chosen, _why = recommend_base_for_corpus(
        effective_size, intent=rec.intent, medium=rec.medium)
    if chosen:
        rec.base_model = chosen
    # else: keep the dataclass default rec.base_model = "google/gemma-2-2b-it"

    rec.summary = (
        f"Goal: {rec.intent} · medium: {rec.medium} · "
        f"format: {rec.export_format} · base: {rec.base_model}. "
        f"Source mix: {', '.join(rec.source_types)}. "
        f"Recommended corpora: {len(rec.recommended_corpora)}."
    ) + (f" {rec.summary}" if rec.summary else "")

    return rec


# ── Public API ────────────────────────────────────────────────

def build_recipe(description: str, *,
                 goal_hint: str = "",
                 medium_hint: str = "",
                 corpus_size: int = 0,
                 use_llm: bool = True) -> TrainingRecipe:
    """Return a TrainingRecipe for the given description.

    Args:
        corpus_size: number of *eligible* training rows the user has
            collected. Drives the base-model size pick — too-small data
            on too-large a base wastes training time. Pass 0 to fall
            back to a generic "small" band default.

    If ``use_llm`` is True and the OS has an LLM configured, ask it to
    classify intent/medium and recommend corpora, then validate the
    answer against the catalog. Falls back to the heuristic backbone
    otherwise (or on any LLM failure).
    """
    base = _heuristic_recipe(description,
                             goal_hint=goal_hint,
                             medium_hint=medium_hint,
                             corpus_size=corpus_size)
    if not use_llm:
        return base

    try:
        from src.config.creativeos_config import get_creativeos_config
        cfg = get_creativeos_config()
        if cfg.get("disable_all_ai") or not cfg.has_llm_configured():
            return base
        # The LLM call is best-effort: if anything fails, return the
        # deterministic heuristic recipe so the user always gets a
        # workable suggestion.
        improved = _llm_refine(base, description, cfg)
        return improved or base
    except Exception as e:
        print(f"[model_builder_agent] LLM refine failed: {e}")
        return base


def _llm_refine(base: TrainingRecipe, description: str,
                cfg) -> Optional[TrainingRecipe]:
    """Ask the configured LLM to refine the heuristic recipe.

    The model returns JSON; we validate every field against the catalog
    so a hallucinated corpus id never makes it into the recipe.
    """
    import json
    from src.ai.llm_client import LLMClient, LLMProvider, HuggingFaceConfig

    s = cfg.shared_llm_settings()
    if s.get("prefer_local_model") and s.get("enable_local_models") and s.get("local_model_id"):
        is_mlx = "mlx" in s["local_model_id"].lower()
        hf_config = HuggingFaceConfig(
            model_id=s["local_model_id"], use_local=True,
            device=s.get("local_model_device", "auto"),
            quantization=s.get("local_model_quantization", "none")
                         if s.get("local_model_quantization") != "none" else None,
        )
        provider = LLMProvider.MLX_LOCAL if is_mlx else LLMProvider.HUGGINGFACE_LOCAL
        llm = LLMClient(provider=provider, hf_config=hf_config)
    else:
        provider_map = {
            "claude": LLMProvider.CLAUDE,
            "chatgpt": LLMProvider.CHATGPT,
            "openai": LLMProvider.CHATGPT,
            "gemini": LLMProvider.GEMINI,
        }
        provider_name = s.get("default_llm", "claude")
        api_key = (s.get("claude_api_key") if provider_name == "claude"
                   else s.get("chatgpt_api_key") if provider_name in ("chatgpt", "openai")
                   else s.get("gemini_api_key"))
        if not api_key:
            return None
        llm = LLMClient(
            provider=provider_map.get(provider_name, LLMProvider.CLAUDE),
            api_key=api_key)

    catalog_blob = "\n".join(
        f"- {e.id}: {e.name} (purpose={e.purpose}, medium={e.medium}, "
        f"narratives={e.narratives}, license={e.license})"
        for e in CATALOG)

    # Allowed base-model ids — only what the user kept enabled in the
    # Manage Built-in Models dialog. We pass them to the LLM AND
    # validate the response against this set so a hallucinated id (or
    # a hidden one) never leaks into the recipe.
    allowed_bases = _included_training_ids()
    bases_blob = ("\n".join(f"- {bid}" for bid in allowed_bases)
                  if allowed_bases else "(no built-in bases enabled)")

    system = (
        "You are CreativeOS's training recipe agent. The user has "
        "described what model they want. Return ONLY JSON matching the "
        "schema below — no commentary.\n\n"
        "{\n"
        "  \"intent\": \"voice|plot|both|qa|worldbuilding|character\",\n"
        "  \"medium\": \"books|movies|tv|short|mixed\",\n"
        "  \"source_types\": [\"rephrase\"|\"chat_writing\"|\"chat_general\""
        "|\"corpus\"|\"agent\"|\"worldbuilding\"|\"character\"|\"plot\"],\n"
        "  \"recommended_corpora\": [\"<id from catalog>\", ...],\n"
        "  \"export_format\": \"instruction|chat|dpo|plot_prompt\",\n"
        "  \"base_model\": \"<HF id from the allowed list>\",\n"
        "  \"epochs\": <int>,\n"
        "  \"learning_rate\": <float>,\n"
        "  \"lora_r\": <int>,\n"
        "  \"summary\": \"1-2 sentence rationale for the recipe\"\n"
        "}")
    prompt = (
        f"Catalog of available corpora (only use ids from this list):\n"
        f"{catalog_blob}\n\n"
        f"Allowed base models (the user has enabled these — pick one):\n"
        f"{bases_blob}\n\n"
        f"User description:\n{description}\n\n"
        f"Heuristic baseline (you may improve it): "
        f"{json.dumps({'intent': base.intent, 'medium': base.medium, 'sources': base.source_types, 'corpora': base.recommended_corpora, 'base_model': base.base_model})}\n\n"
        f"Return ONLY the JSON object."
    )

    try:
        out = llm.generate_text(prompt=prompt, system_prompt=system,
                                max_tokens=800, temperature=0.1)
    except Exception as e:
        print(f"[model_builder_agent] generate failed: {e}")
        return None

    out = (out or "").strip()
    if out.startswith("```"):
        # Strip markdown fence
        out = out.split("```")[1]
        if out.startswith("json"):
            out = out[4:]
        out = out.strip("` \n")
    try:
        data = json.loads(out)
    except Exception:
        return None

    # Validate corpora ids
    valid_ids = {e.id for e in CATALOG}
    cor = [c for c in data.get("recommended_corpora", []) if c in valid_ids]
    if not cor:
        cor = base.recommended_corpora

    # Validate the base model choice against the user's enabled set so
    # the LLM can't sneak past the include/exclude filter (or hallucinate
    # an id that the Training Studio doesn't offer).
    proposed_base = (data.get("base_model") or "").strip()
    allowed_set = set(allowed_bases)
    if proposed_base and proposed_base not in allowed_set:
        # Fall back to whatever the heuristic already picked — that one
        # is guaranteed to be on the allowed list (see _heuristic_recipe).
        print(f"[model_builder_agent] LLM proposed disallowed base "
              f"'{proposed_base}'; falling back to '{base.base_model}'")
        proposed_base = base.base_model
    if not proposed_base:
        proposed_base = base.base_model

    refined = TrainingRecipe(
        summary=data.get("summary", base.summary),
        intent=data.get("intent", base.intent),
        medium=data.get("medium", base.medium),
        source_types=[s for s in data.get("source_types", base.source_types)
                      if s in (SOURCE_REPHRASE, SOURCE_CHAT_WRITING,
                               SOURCE_CHAT_GENERAL, SOURCE_CORPUS,
                               SOURCE_AGENT, SOURCE_WORLDBUILDING,
                               SOURCE_CHARACTER, SOURCE_PLOT)]
                     or base.source_types,
        recommended_corpora=cor,
        export_format=data.get("export_format", base.export_format),
        base_model=proposed_base,
        epochs=int(data.get("epochs", base.epochs) or base.epochs),
        learning_rate=float(data.get("learning_rate", base.learning_rate)
                            or base.learning_rate),
        batch_size=base.batch_size,
        lora_r=int(data.get("lora_r", base.lora_r) or base.lora_r),
        min_rating=base.min_rating,
    )
    return refined
