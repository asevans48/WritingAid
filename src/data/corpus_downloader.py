"""Coordinator: download a corpus, run its adapter, log passages to
the unified learning database as ``corpus`` rows.

Downloads are explicit user actions in the Training Studio. We never
auto-download. License checking happens before the network call —
entries that aren't on the safelist are rejected unless the user has
already attested to permission via the registry's ``user-attested``
license label.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from src.data.corpus_catalog import CorpusEntry, is_license_safe
from src.data.corpus_adapters import parse as adapter_parse, fetch_hf_dataset


# Splitter helper lives in ``corpus_adapters`` so both the local-
# folder ingestion path here and the HF fetcher there can use it
# without a circular import. Re-export for the existing callers
# that import it from this module (the upload / project-import
# helpers in the training tool window).
from src.data.corpus_adapters import (  # noqa: F401
    _PREFERRED_OPENER_CHARS,
    _MIN_OPENER_CHARS,
    _MIN_REST_CHARS,
    _MIN_PARAGRAPH_CHARS,
    _split_paragraph_for_training,
    split_text_into_pairs,
)
from src.data.rephrase_database import RephraseDatabase, get_rephrase_database


CORPUS_DIR = Path.home() / ".creativeos" / "corpus_downloads"


def _resolve_meta_path(meta: dict, path: str):
    """Read ``path`` from ``meta`` with dotted JSON-string support.

    A path like ``METADATA.bookshelves`` means "parse
    ``meta['METADATA']`` as JSON, then look up 'bookshelves' in
    the result." Mirrors ``_read_field`` in ``corpus_adapters``;
    we duplicate it here because the downloader sees the
    already-streamed row dict (the adapter has its own copy in
    its hot loop).
    """
    if not path:
        return None
    if "." not in path:
        return meta.get(path)
    col, key = path.split(".", 1)
    raw = meta.get(col)
    if isinstance(raw, str):
        import json as _json
        try:
            parsed = _json.loads(raw)
        except (ValueError, TypeError):
            return None
    elif isinstance(raw, dict):
        parsed = raw
    else:
        return None
    for part in key.split("."):
        if isinstance(parsed, dict):
            parsed = parsed.get(part)
        else:
            return None
    return parsed


@dataclass
class IngestResult:
    entry: CorpusEntry
    bytes_downloaded: int
    passages_found: int
    passages_logged: int
    db_path: Path


class CorpusLicenseError(RuntimeError):
    """Raised when we refuse to download because the license isn't safe."""


def _download(url: str, dest: Path,
              on_progress: Optional[Callable[[int, int, str], None]] = None
              ) -> int:
    """Stream the URL to disk. Returns bytes downloaded.

    ``on_progress(current, total, label)`` is invoked every chunk so
    the UI can render a real progress bar. ``total`` is read from the
    server's ``Content-Length`` header when present (the common case
    on Project Gutenberg + S3) and is ``0`` otherwise — UI should
    fall back to an indeterminate bar when total is 0.
    """
    import urllib.request
    dest.parent.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(
        url, headers={"User-Agent": "CreativeOS/1.0 (corpus downloader)"})
    bytes_done = 0
    with urllib.request.urlopen(req, timeout=60) as resp, \
         open(dest, 'wb') as f:
        # ``Content-Length`` is the canonical pre-flight size header.
        # Some servers (rare for static files) omit it; we treat
        # ``0`` as "unknown" downstream so the UI uses a busy bar.
        try:
            total_size = int(resp.headers.get("Content-Length") or 0)
        except (TypeError, ValueError):
            total_size = 0
        label = f"downloading {dest.name}"
        while True:
            chunk = resp.read(64 * 1024)
            if not chunk:
                break
            f.write(chunk)
            bytes_done += len(chunk)
            if on_progress:
                on_progress(bytes_done, total_size, label)
    return bytes_done


def _read_text(path: Path) -> str:
    for enc in ("utf-8", "latin-1", "utf-16"):
        try:
            return path.read_text(encoding=enc)
        except (UnicodeError, UnicodeDecodeError):
            continue
    return path.read_text(encoding="utf-8", errors="replace")


def ingest(entry: CorpusEntry, *,
           db: Optional[RephraseDatabase] = None,
           force: bool = False,
           on_progress: Optional[Callable[[int, int, str], None]] = None,
           on_log: Optional[Callable[[str], None]] = None,
           ) -> IngestResult:
    """Download (if needed) → adapter-parse → log to learning DB.

    Args:
        entry: The corpus entry to fetch.
        db: Override target database (default: unified rephrase DB).
        force: True to re-download even if a cached file exists.
        on_progress: ``(current, total, label)`` callback. ``total``
            is ``0`` when indeterminate (HF datasets without a
            row-count cap, HTTP servers without ``Content-Length``).
            Called repeatedly across phases — download/streaming,
            then again during DB insertion — so the UI bar should
            reset its scale every time the label changes.
        on_log: Optional log sink for status lines (UI uses this).

    Raises:
        CorpusLicenseError: if the entry's license isn't on the
            safelist and isn't ``user-attested``. The Training Studio
            shows an attestation prompt before flipping a custom
            entry to ``user-attested``.
    """
    log = on_log or (lambda *_: None)
    progress = on_progress or (lambda *_: None)

    # License gate — never download copyrighted material on the user's behalf.
    if not is_license_safe(entry.license) and entry.license != "user-attested":
        raise CorpusLicenseError(
            f"Refusing to download '{entry.name}': license "
            f"'{entry.license}' is not on the safelist. The user must "
            f"attest to permission via the corpus registry first.")

    db = db or get_rephrase_database()
    CORPUS_DIR.mkdir(parents=True, exist_ok=True)

    # ── HuggingFace dataset path ────────────────────────────
    if entry.format == "hf_dataset":
        log(f"Streaming HuggingFace dataset: {entry.url}…")
        rows, status = fetch_hf_dataset(
            entry.url,
            split=entry.hf_split or "train",
            # Optional dataset configuration name. Required for
            # datasets like PAWS that expose multiple configs;
            # empty string for single-config datasets.
            config=getattr(entry, "hf_config", "") or "",
            text_field=entry.hf_text_field,
            prompt_field=entry.hf_prompt_field,
            completion_field=entry.hf_completion_field,
            max_rows=entry.hf_max_rows or 5000,
            filter_field=getattr(entry, "hf_filter_field", "") or "",
            filter_value=getattr(entry, "hf_filter_value", "") or "",
            on_progress=progress,
        )
        if status == "missing-datasets-library":
            raise RuntimeError(
                "The 'datasets' package isn't installed. Run:\n"
                "  pip install datasets\n"
                "then retry, or pick a non-HF corpus.")
        if status != "ok" and not rows:
            raise RuntimeError(f"HuggingFace fetch failed: {status}")
        log(f"  pulled {len(rows)} rows ({status})")

        notes_base = (f"corpus_id={entry.id} license={entry.license} "
                      f"author={entry.author} hf_dataset={entry.url}").strip()
        # Default genre tag falls back to the entry-level tags when the
        # dataset has no per-row genre column. When ``hf_genre_field``
        # is set on the catalog entry, we read each row's genre and
        # map it through the canonical taxonomy below.
        default_genre = ",".join(entry.tags[:3])
        # Lazy-import the fuzzy matcher so this module stays cheap to
        # load on platforms where the genres module isn't needed.
        try:
            from src.data.genres import match_genres
        except Exception:
            match_genres = lambda _t: []  # noqa: E731

        n_logged = 0
        # Switch the progress bar from "streaming" to "writing" — the
        # DB insert phase is also non-trivial when we just expanded
        # 4000 book rows into 320,000 paragraph pairs.
        progress(0, len(rows), f"writing {len(rows):,} pairs to DB")
        for prompt, completion, meta in rows:
            # Per-row genre: fuzzy-match the dataset's free-text label
            # (e.g. "Sci-Fi", "Psychological Horror", "Cyberpunk")
            # against our canonical taxonomy. Multiple matches are
            # comma-joined so a "gothic horror" row passes both filters.
            # Unmatched labels fall through verbatim — better to keep
            # the dataset's own label than drop the signal entirely.
            # Field paths may be dotted (``METADATA.bookshelves``) for
            # datasets that JSON-encode metadata into one column;
            # ``_resolve_meta_path`` parses that the same way the
            # adapter does. Plain field names work as before.
            row_genre = default_genre
            if entry.hf_genre_field:
                raw = (_resolve_meta_path(meta, entry.hf_genre_field)
                       or "")
                raw = str(raw).strip()
                if raw:
                    canonical = match_genres(raw)
                    if canonical:
                        row_genre = ",".join(canonical)
                    else:
                        # Keep the original label lower-cased so the
                        # genre filter can still match exact strings
                        # users type, even if it's not in the taxonomy.
                        row_genre = raw.lower()

            row_title = entry.name
            if entry.hf_title_field:
                t = _resolve_meta_path(meta, entry.hf_title_field)
                if t and str(t).strip():
                    row_title = str(t).strip()

            # Route by the catalog entry's declared purpose so the
            # row's ``source_type`` actually matches what it teaches.
            # Without this, every catalog corpus lands as
            # source_type='corpus' regardless of purpose — which means
            # a BookSum download (purpose='plot') wouldn't appear in
            # the Browse-rows "plot" filter and the trainer's per-
            # source eligibility counts would mis-bucket it. The
            # purpose= tag in notes is kept for backward-compat with
            # the rebuild flow, which keys off ``corpus_id=`` only.
            row_notes = (f"{notes_base} purpose={entry.purpose} "
                         f"medium={entry.medium}")
            common = dict(prompt=prompt, completion=completion,
                          notes=row_notes, genre=row_genre)
            purpose = (entry.purpose or "").lower()
            if purpose == "plot":
                db.log_plot(**common)
            elif purpose == "character":
                db.log_character(character_name=entry.author, **common)
            elif purpose == "worldbuilding":
                db.log_worldbuilding(**common)
            else:
                # "voice", "both", or anything unrecognised stays in
                # the SOURCE_CORPUS bucket — that's the most
                # inclusive default, and "both" is genuinely either
                # so the corpus filter (which already trains on this
                # bucket) is the right home.
                db.log_corpus_pair(
                    title=row_title, character_name=entry.author,
                    **common)
            n_logged += 1
            # Update the bar every 200 inserts. SQLite inserts run
            # ~30k/s on a typical SSD; 200 keeps the progress bar
            # smooth without flooding the signal queue.
            if n_logged % 200 == 0:
                progress(n_logged, len(rows),
                         f"writing pairs to DB")
        progress(n_logged, len(rows), "writing pairs to DB")
        log(f"  logged {n_logged} corpus pairs to learning DB")
        return IngestResult(
            entry=entry,
            bytes_downloaded=0,
            passages_found=len(rows),
            passages_logged=n_logged,
            db_path=db.db_path,
        )

    # ── Local folder / zip path ────────────────────────────
    # When the user registers a corpus they already have on disk (a
    # downloaded archive of contemporary literature, a directory of
    # plaintext chapters, etc.), the entry's ``url`` field holds the
    # local path instead of an HTTP URL. We walk the directory or
    # extract the zip, then ingest each text file via the same
    # passage-splitter the upload dialog uses — keeping ingest shape
    # consistent across all corpus sources.
    if entry.format in ("local_folder", "local_zip"):
        import re
        from pathlib import Path as _Path
        local_path = _Path(entry.url)
        if not local_path.exists():
            raise RuntimeError(
                f"Local corpus path doesn't exist: {local_path}\n"
                f"It may have been moved or deleted since you "
                f"registered the entry. Re-register or fix the path "
                f"in the corpus registry.")

        # Build the (label, text) pairs.
        text_blobs = []
        if entry.format == "local_zip":
            log(f"Extracting texts from zip: {local_path}…")
            import zipfile
            TEXT_EXTS = {".txt", ".md", ".markdown", ".text", ".rtf",
                         ".tex", ".log"}
            try:
                with zipfile.ZipFile(local_path, "r") as zf:
                    for info in zf.infolist():
                        name = info.filename
                        if (info.is_dir()
                                or name.startswith("__MACOSX/")
                                or name.endswith("/.DS_Store")
                                or "/." in name
                                or name.startswith(".")):
                            continue
                        if _Path(name).suffix.lower() not in TEXT_EXTS:
                            continue
                        try:
                            raw = zf.read(info)
                        except Exception:
                            continue
                        text = None
                        for enc in ("utf-8", "latin-1", "utf-16"):
                            try:
                                text = raw.decode(enc)
                                break
                            except Exception:
                                continue
                        if text:
                            text_blobs.append((_Path(name).stem, text))
            except zipfile.BadZipFile as e:
                raise RuntimeError(f"Not a valid zip archive: {e}")
        else:  # local_folder
            log(f"Walking folder: {local_path}…")
            TEXT_EXTS = {".txt", ".md", ".markdown", ".text", ".rtf",
                         ".tex"}
            for p in local_path.rglob("*"):
                if not p.is_file():
                    continue
                if p.suffix.lower() not in TEXT_EXTS:
                    continue
                if p.name.startswith(".") or "/__MACOSX" in str(p):
                    continue
                try:
                    text = p.read_text(encoding="utf-8", errors="replace")
                except Exception as e:
                    log(f"  could not read {p.name}: {e}")
                    continue
                text_blobs.append((p.stem, text))
        log(f"  found {len(text_blobs)} text file(s)")

        # Ingest each text via the corpus continuation pattern (first
        # sentence → rest). All rows share the same corpus_id so they
        # group as one collection in the per-corpus filter.
        notes_base = (f"corpus_id={entry.id} license={entry.license} "
                      f"author={entry.author or 'local'} "
                      f"local_path={local_path}")
        genre_tag = ",".join(entry.tags[:3])
        n_logged = 0
        progress(0, len(text_blobs), "ingesting local files")
        for fi, (label, text) in enumerate(text_blobs, 1):
            if not text or len(text) < 80:
                continue
            paragraphs = [p.strip()
                          for p in re.split(r'\n\s*\n+', text) if p.strip()]
            for para in paragraphs:
                if len(para) < 100 or len(para) > 2500:
                    continue
                if para.lstrip()[:1] in '#-*•':
                    continue
                opener, rest = _split_paragraph_for_training(para)
                if not opener or not rest:
                    continue
                db.log_corpus_pair(
                    prompt=opener, completion=rest,
                    title=entry.name,
                    voice="",
                    genre=genre_tag,
                    character_name=entry.author or "",
                    notes=f"{notes_base} file={label}")
                n_logged += 1
            progress(fi, len(text_blobs), "ingesting local files")
        log(f"  logged {n_logged} corpus pairs to learning DB")
        return IngestResult(
            entry=entry, bytes_downloaded=0,
            passages_found=sum(1 for _ in text_blobs),
            passages_logged=n_logged, db_path=db.db_path)

    # ── HTTP download path (txt / gutenberg / markdown / etc.) ──
    suffix = ".txt" if entry.format != "epub" else ".epub"
    dest = CORPUS_DIR / f"{entry.id}{suffix}"

    if dest.exists() and not force:
        log(f"Using cached file: {dest}")
        downloaded = dest.stat().st_size
    else:
        log(f"Downloading {entry.url}…")
        downloaded = _download(entry.url, dest, on_progress=progress)
        log(f"  saved {downloaded:,} bytes to {dest}")

    log("Parsing with adapter: " + entry.format)
    progress(0, 0, f"parsing {entry.name}")
    raw = _read_text(dest)
    passages = adapter_parse(entry.format, raw, title=entry.name)
    log(f"  extracted {len(passages)} passages")

    # Log corpus pairs. Multi-sentence opener (≥80 chars) so the
    # model has enough context to pick up voice / cadence rather
    # than learning to extend a single short sentence.
    progress(0, len(passages), "writing pairs to DB")
    n_logged = 0
    for i, para in enumerate(passages, 1):
        opener, rest = _split_paragraph_for_training(para)
        if not opener or not rest:
            continue
        notes = (f"corpus_id={entry.id} license={entry.license} "
                 f"author={entry.author}").strip()
        db.log_corpus_pair(prompt=opener, completion=rest,
                           title=entry.name,
                           genre=" ".join(entry.tags[:3]),
                           character_name=entry.author,
                           notes=notes)
        n_logged += 1
        if i % 200 == 0:
            progress(i, len(passages), "writing pairs to DB")
    progress(len(passages), len(passages), "writing pairs to DB")
    log(f"  logged {n_logged} corpus pairs to learning DB")

    return IngestResult(
        entry=entry,
        bytes_downloaded=downloaded,
        passages_found=len(passages),
        passages_logged=n_logged,
        db_path=db.db_path,
    )
