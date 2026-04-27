"""Pluggable adapters that turn a downloaded corpus file into clean
passage strings ready for ingestion into the learning database.

Adapters all share the same interface:

    def parse(text: str, *, title: str = "") -> List[str]

They take raw downloaded text and return a list of cleanish passages
(roughly paragraph-sized). The caller (``corpus_downloader.ingest``)
turns each into a ``corpus`` row in the learning database.

Adapters never download anything themselves — that's the downloader's
job. They also never call out to the network. Some can call an LLM
to clean noisy formats (Wikisource XML, scanned OCR, etc.) — the
LLM-assisted adapter is gated on the OS-level shared LLM config.
"""

from __future__ import annotations

import re
from typing import Callable, Dict, List, Optional

from src.data.text_cleaner import (
    clean_passages as _cleanup_passages,
    clean_chat_message as _cleanup_chat,
)


# ── Generic helpers ───────────────────────────────────────────

_PARAGRAPH_RE = re.compile(r'\n\s*\n+')


def _split_paragraphs(text: str) -> List[str]:
    """Split text on blank lines, strip whitespace, drop trivial bits."""
    paras = []
    for raw in _PARAGRAPH_RE.split(text or ""):
        para = " ".join(raw.split())  # collapse whitespace inside a para
        if not para:
            continue
        paras.append(para)
    return paras


# Splitter targets for one (opener, rest) training pair. The old
# splitter used the FIRST sentence as opener, producing things like
# ``src="I trembled."`` (11 chars) — far too short for the model to
# pick up voice / cadence. This rewrite finds the earliest sentence
# boundary where both halves meet a minimum length.
_PREFERRED_OPENER_CHARS = 80
_MIN_OPENER_CHARS = 60
_MIN_REST_CHARS = 60
_MIN_PARAGRAPH_CHARS = _PREFERRED_OPENER_CHARS + _MIN_REST_CHARS

# Per-row cap on training pairs we extract from one source row.
# Without this, a single full-length book row in datasets like
# ``manu/project_gutenberg`` (avg ≈ 400k chars, ~1500 paragraphs)
# would produce thousands of pairs per book and starve the rest of
# the corpus pull — and the corpus downloader buffers everything in
# memory before inserting, so unbounded fan-out also risks OOM. 80
# pairs ≈ one long-short-story's worth of voice signal per source
# row, balanced against memory pressure across a 4000-row pull.
_MAX_PAIRS_PER_ROW = 80


def _split_paragraph_for_training(paragraph: str):
    """Split one paragraph into ``(opener, rest)`` for corpus training.

    Returns ``(None, None)`` if the paragraph is too short or has no
    usable sentence break. See module-level constants for the length
    thresholds.

    Why this matters: the model's input is the opener; its target is
    the completion. With 11-char openers the model has no signal
    about the author's voice / register / sentence rhythm and reverts
    to the base model's generic style.
    """
    if not paragraph or len(paragraph) < _MIN_PARAGRAPH_CHARS:
        return None, None
    sentences = re.split(r'(?<=[.!?])\s+', paragraph.strip())
    if len(sentences) < 2:
        return None, None

    def _try(opener_min: int):
        for split_at in range(1, len(sentences)):
            opener = " ".join(sentences[:split_at]).strip()
            rest = " ".join(sentences[split_at:]).strip()
            if (len(opener) >= opener_min
                    and len(rest) >= _MIN_REST_CHARS):
                return opener, rest
        return None, None

    pair = _try(_PREFERRED_OPENER_CHARS)
    if pair[0] is None:
        pair = _try(_MIN_OPENER_CHARS)
    return pair


def split_text_into_pairs(text: str,
                          max_pairs: int = _MAX_PAIRS_PER_ROW
                          ) -> List[tuple]:
    """Split a chunk of prose into multiple (opener, rest) pairs.

    Walks paragraph boundaries and emits one pair per qualifying
    paragraph. Used for HF rows that are full books / chapters where
    treating the whole row as a single training example wastes 99%
    of the prose. ``max_pairs`` caps fan-out so one mega-row doesn't
    dominate the dataset.

    A paragraph that's longer than ``2 * _MIN_PARAGRAPH_CHARS`` but
    has no sentence boundary that satisfies the splitter (one giant
    run-on, dialogue blob with no period) is skipped quietly — the
    splitter would reject it anyway, and trying to force-split would
    cut mid-sentence.
    """
    if not text:
        return []
    pairs: List[tuple] = []
    paragraphs = _split_paragraphs(text)
    for para in paragraphs:
        if _looks_like_heading(para):
            continue
        if len(para) > 4000:
            # Long ones we let through unchanged — the splitter
            # works on sentence boundaries inside the paragraph.
            pass
        opener, rest = _split_paragraph_for_training(para)
        if opener is None:
            continue
        pairs.append((opener, rest))
        if len(pairs) >= max_pairs:
            break
    return pairs


def _looks_like_heading(p: str) -> bool:
    """Filter out chapter headers / bare numbers / ALL-CAPS lines."""
    if len(p) < 60:
        return True
    if p.isupper():
        return True
    if re.match(r'^(chapter|book|part|volume|act|scene)\s+', p, re.I):
        return True
    return False


# ── Adapters ──────────────────────────────────────────────────

def _parse_plain(text: str, **_) -> List[str]:
    """Plain-text adapter — paragraph split + run the shared cleaner.

    The cleaner does length filtering, junk-signature detection
    (boilerplate, tool-call JSON, page numbers, headings, …) and
    light character normalisation (HTML entities, ligatures, ZWSP).
    """
    paragraphs = _split_paragraphs(text)
    kept, _stats = _cleanup_passages(paragraphs, format_hint="plain")
    return kept


def _parse_markdown(text: str, **_) -> List[str]:
    """Markdown — strip structural lines, then run the shared cleaner.

    We treat headings / list bullets / code fences as paragraph
    breaks (so the body around them survives) but the lines
    themselves are dropped before paragraphs are reassembled. The
    cleaner downstream handles markdown-specific junk (front-matter
    delimiters, TODO comments).
    """
    cleaned = []
    for line in (text or "").splitlines():
        s = line.lstrip()
        if not s:
            cleaned.append("")
            continue
        if s.startswith(("#", ">", "-", "*", "+")):
            cleaned.append("")  # treat as paragraph break
            continue
        if s.startswith("```"):
            cleaned.append("")
            continue
        cleaned.append(line)
    paragraphs = _split_paragraphs("\n".join(cleaned))
    kept, _stats = _cleanup_passages(paragraphs, format_hint="markdown")
    return kept


def _parse_gutenberg(text: str, **_) -> List[str]:
    """Project Gutenberg — slice between START/END markers, then clean.

    Files always include ``*** START OF ...`` and ``*** END OF ...``
    markers. Even after slicing them out, the remaining body still
    has "Produced by …" transcription notes, "Transcriber's note"
    blocks, illustration markers, and italic-underscore artifacts —
    all handled by the gutenberg-format-hint pass of the cleaner.
    """
    body = text or ""
    m_start = re.search(r'\*\*\*\s*START OF .* \*\*\*', body)
    m_end = re.search(r'\*\*\*\s*END OF .* \*\*\*', body)
    if m_start and m_end and m_end.start() > m_start.end():
        body = body[m_start.end():m_end.start()]
    elif m_start:
        body = body[m_start.end():]
    # Collapse single newlines; keep blank-line paragraph breaks.
    body = re.sub(r'(?<!\n)\n(?!\n)', ' ', body)
    paragraphs = _split_paragraphs(body)
    kept, _stats = _cleanup_passages(paragraphs, format_hint="gutenberg")
    return kept


def _parse_epub(text: str, **_) -> List[str]:
    """Naive EPUB-extracted-text adapter. Real EPUB unzipping happens
    in the downloader; this adapter only sees flat text. We strip XML
    tags defensively in case they leaked through, then clean.
    """
    stripped = re.sub(r'<[^>]+>', '', text or "")
    paragraphs = _split_paragraphs(stripped)
    kept, _stats = _cleanup_passages(paragraphs, format_hint="plain")
    return kept


def _parse_with_llm(text: str, *, title: str = "", **_) -> List[str]:
    """Use the configured LLM to clean unfamiliar formats (Wikisource
    MediaWiki XML, OCR'd scans, mixed markup, etc.) into usable
    paragraph-style prose.

    Falls back to the plain-text adapter if no LLM is configured or
    the call fails — never silently drops the corpus.
    """
    try:
        from src.config.creativeos_config import get_creativeos_config
        cfg = get_creativeos_config()
        if cfg.get("disable_all_ai", False):
            return _parse_plain(text)
        if not cfg.has_llm_configured():
            return _parse_plain(text)

        from src.ai.llm_client import LLMClient, LLMProvider, HuggingFaceConfig
    except Exception:
        return _parse_plain(text)

    # Process in chunks so even very large files work
    chunks = []
    raw = (text or "").strip()
    chunk_size = 8000
    for i in range(0, len(raw), chunk_size):
        chunks.append(raw[i:i + chunk_size])

    try:
        # Build whatever LLMClient the OS has available
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
                return _parse_plain(text)
            llm = LLMClient(
                provider=provider_map.get(provider_name, LLMProvider.CLAUDE),
                api_key=api_key)
    except Exception as e:
        print(f"[corpus_adapter:llm] LLM init failed: {e}")
        return _parse_plain(text)

    paragraphs: List[str] = []
    system = ("You clean raw text dumps into paragraph-separated prose. "
              "Preserve the author's words verbatim — only remove markup, "
              "page numbers, headers/footers, navigation links, and "
              "metadata. Output paragraphs separated by blank lines. "
              "No commentary, no summaries.")
    for chunk in chunks[:50]:  # safety cap
        prompt = (f"Clean this raw corpus text into paragraph-separated "
                  f"prose. Source: {title or 'unknown'}.\n\n{chunk}")
        try:
            cleaned = llm.generate_text(
                prompt=prompt, system_prompt=system,
                max_tokens=min(4000, len(chunk) * 2), temperature=0.0)
        except Exception as e:
            print(f"[corpus_adapter:llm] generation failed: {e}")
            continue
        paragraphs.extend(_parse_plain(cleaned))
    return paragraphs or _parse_plain(text)


# Adapter dispatch table — keep keys in sync with CorpusEntry.format
ADAPTERS: Dict[str, Callable[..., List[str]]] = {
    "txt": _parse_plain,
    "plain": _parse_plain,
    "markdown": _parse_markdown,
    "md": _parse_markdown,
    "gutenberg": _parse_gutenberg,
    "epub": _parse_epub,
    "llm": _parse_with_llm,
}


def parse(format_label: str, text: str, *, title: str = "") -> List[str]:
    """Pick an adapter by name and run it. Falls back to plain text."""
    fn = ADAPTERS.get((format_label or "txt").lower(), _parse_plain)
    return fn(text, title=title)


# ── HuggingFace datasets adapter ──────────────────────────────
#
# This adapter is invoked from the downloader (not via ADAPTERS) because
# its source isn't a single text blob — it streams structured rows from
# the `datasets` library. We expose a function that returns a list of
# (prompt, completion, metadata) tuples so the downloader can log
# either as plain corpus pairs or as plot-format examples.

def fetch_hf_dataset(
    dataset_id: str,
    *,
    split: str = "train",
    config: str = "",
    text_field: str = "",
    prompt_field: str = "",
    completion_field: str = "",
    max_rows: int = 5000,
    filter_field: str = "",
    filter_value: str = "",
    on_progress: Optional[Callable[[int, int, str], None]] = None,
):
    """Stream rows from a HuggingFace dataset and return them as
    (prompt, completion, row_metadata) tuples.

    Args:
        config: dataset configuration name. Required for any HF
            dataset that exposes ``BUILDER_CONFIGS`` — e.g. PAWS,
            which has ``labeled_final`` / ``labeled_swap`` /
            ``unlabeled_final``. Recent versions of the
            ``datasets`` package raise *"Config name is missing"*
            when you call ``load_dataset`` on such a dataset
            without specifying one. Empty string means "dataset
            has only one default config".

    The caller (corpus_downloader) decides how to log them — narrative
    voice corpora typically use the "first sentence → rest" pattern,
    while plot corpora use the prompt/completion fields directly.

    Returns ``[]`` if the ``datasets`` library isn't installed (the
    coordinator surfaces an instruction to ``pip install datasets``
    in that case).
    """
    try:
        from datasets import load_dataset
    except ImportError:
        return [], "missing-datasets-library"

    try:
        if config:
            ds = load_dataset(
                dataset_id, config, split=split, streaming=True)
        else:
            ds = load_dataset(
                dataset_id, split=split, streaming=True)
    except Exception as e:
        return [], f"load-failed: {e}"

    # JSON-path field reader. Some datasets (notably
    # ``sedthh/gutenberg_english``) keep useful metadata —
    # bookshelves, subjects, title — JSON-encoded inside one
    # column. A field name with a dot ``column.key`` means
    # "parse ``record[column]`` as JSON, then look up ``key`` in
    # the result." Plain (no-dot) field names work as before.
    import json as _json

    def _read_field(record: dict, path: str) -> Any:
        if not path:
            return None
        if "." not in path:
            return record.get(path)
        col, key = path.split(".", 1)
        raw = record.get(col)
        if isinstance(raw, str):
            try:
                parsed = _json.loads(raw)
            except (ValueError, TypeError):
                return None
        elif isinstance(raw, dict):
            parsed = raw
        else:
            return None
        # Allow further nesting via repeated dotting in ``key``.
        for part in key.split("."):
            if isinstance(parsed, dict):
                parsed = parsed.get(part)
            else:
                return None
        return parsed

    rows: list = []
    cols_seen: list = []
    n = 0
    # Pre-stringify the filter target for tolerant equality on
    # numeric vs string fields (PAWS' ``label`` is int 1; user might
    # pass "1" or 1 either way).
    filter_target = (str(filter_value).strip()
                     if filter_field and filter_value != "" else None)
    # Progress reporting cadence: every N records polled. Reporting
    # per-row would flood the UI thread; every 50 keeps the bar
    # responsive without spamming signals.
    progress_every = 50
    if on_progress:
        on_progress(0, max_rows, f"streaming {dataset_id}")
    for record in ds:
        if not cols_seen:
            cols_seen = list(record.keys())

        # Row-filter — drop records where ``filter_field != filter_value``.
        # Used by paraphrase datasets like PAWS to keep only label=1
        # (true paraphrase pairs) and skip label=0.
        if filter_target is not None and filter_field:
            row_val = _read_field(record, filter_field)
            if row_val is None or str(row_val).strip() != filter_target:
                continue

        if prompt_field and completion_field:
            # Plot/structured corpus. Clean both halves through the
            # chat-message cleaner — these are short structured pairs,
            # not full passages, so the chat path's normalisation is
            # the right fit (HTML entities, ligatures, JSON-shape
            # rejection). Drop if either side becomes junk.
            p_raw = (str(_read_field(record, prompt_field) or "")).strip()
            c_raw = (str(_read_field(record, completion_field) or "")).strip()
            if not p_raw or not c_raw or len(c_raw) < 30:
                continue
            p, p_drop = _cleanup_chat(p_raw)
            c, c_drop = _cleanup_chat(c_raw)
            if p_drop or c_drop or len(c) < 30:
                continue
            rows.append((p, c, dict(record)))
        else:
            # Voice/narrative corpus — text-only
            if text_field:
                text = _read_field(record, text_field)
            else:
                # Auto-detect the first text-like column
                text = None
                for k in cols_seen:
                    val = record.get(k)
                    if isinstance(val, str) and len(val) > 80:
                        text = val
                        break
                if text is None:
                    # ROCStories-style: stitch sentence1..sentence5
                    parts = []
                    for i in range(1, 8):
                        v = record.get(f"sentence{i}")
                        if v:
                            parts.append(str(v))
                    text = " ".join(parts) if parts else None
            if not text or len(text) < 80:
                continue
            # Voice/narrative path. Most rows in datasets like
            # ``manu/project_gutenberg`` or ``deepmind/pg19`` are
            # full books or chapters — one row = many paragraphs.
            # The old code took the first sentence of the row and
            # threw the rest into one completion, wasting 99% of
            # the prose. Now we split into paragraph-aligned
            # ``(opener, rest)`` pairs so a 100k-char book yields
            # ~hundreds of training pairs instead of one.
            text_clean, drop_reason = _cleanup_chat(text)
            if drop_reason or len(text_clean) < 80:
                continue
            row_meta = dict(record)
            pairs = split_text_into_pairs(text_clean)
            if not pairs:
                # Single-paragraph or no-sentence-boundary rows: fall
                # back to the old half-and-half split so short stories
                # / sentence-level datasets (TinyStories, etc.) still
                # produce one pair instead of being silently dropped.
                half = len(text_clean) // 2
                p_text = text_clean[:half].strip()
                c_text = text_clean[half:].strip()
                if len(c_text) >= 60 and len(p_text) >= 30:
                    rows.append((p_text, c_text, row_meta))
            else:
                for p_text, c_text in pairs:
                    rows.append((p_text, c_text, row_meta))

        n += 1
        if on_progress and n % progress_every == 0:
            on_progress(n, max_rows, f"streaming {dataset_id}")
        if n >= max_rows:
            break

    if on_progress:
        on_progress(n, max_rows, f"streaming {dataset_id}")
    return rows, "ok"
