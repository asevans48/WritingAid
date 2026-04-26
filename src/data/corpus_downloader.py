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
from src.data.rephrase_database import RephraseDatabase, get_rephrase_database


CORPUS_DIR = Path.home() / ".creativeos" / "corpus_downloads"


@dataclass
class IngestResult:
    entry: CorpusEntry
    bytes_downloaded: int
    passages_found: int
    passages_logged: int
    db_path: Path


class CorpusLicenseError(RuntimeError):
    """Raised when we refuse to download because the license isn't safe."""


def _download(url: str, dest: Path, on_progress: Optional[Callable[[int], None]] = None
              ) -> int:
    """Stream the URL to disk. Returns bytes downloaded."""
    import urllib.request
    dest.parent.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(
        url, headers={"User-Agent": "CreativeOS/1.0 (corpus downloader)"})
    total = 0
    with urllib.request.urlopen(req, timeout=60) as resp, \
         open(dest, 'wb') as f:
        while True:
            chunk = resp.read(64 * 1024)
            if not chunk:
                break
            f.write(chunk)
            total += len(chunk)
            if on_progress:
                on_progress(total)
    return total


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
           on_progress: Optional[Callable[[int], None]] = None,
           on_log: Optional[Callable[[str], None]] = None,
           ) -> IngestResult:
    """Download (if needed) → adapter-parse → log to learning DB.

    Args:
        entry: The corpus entry to fetch.
        db: Override target database (default: unified rephrase DB).
        force: True to re-download even if a cached file exists.
        on_progress: Called with cumulative bytes during download.
        on_log: Optional log sink for status lines (UI uses this).

    Raises:
        CorpusLicenseError: if the entry's license isn't on the
            safelist and isn't ``user-attested``. The Training Studio
            shows an attestation prompt before flipping a custom
            entry to ``user-attested``.
    """
    log = on_log or (lambda *_: None)

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
            text_field=entry.hf_text_field,
            prompt_field=entry.hf_prompt_field,
            completion_field=entry.hf_completion_field,
            max_rows=entry.hf_max_rows or 5000,
            filter_field=getattr(entry, "hf_filter_field", "") or "",
            filter_value=getattr(entry, "hf_filter_value", "") or "",
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
        for prompt, completion, meta in rows:
            # Per-row genre: fuzzy-match the dataset's free-text label
            # (e.g. "Sci-Fi", "Psychological Horror", "Cyberpunk")
            # against our canonical taxonomy. Multiple matches are
            # comma-joined so a "gothic horror" row passes both filters.
            # Unmatched labels fall through verbatim — better to keep
            # the dataset's own label than drop the signal entirely.
            row_genre = default_genre
            if entry.hf_genre_field:
                raw = (meta.get(entry.hf_genre_field) or "")
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
                t = meta.get(entry.hf_title_field)
                if t and str(t).strip():
                    row_title = str(t).strip()

            db.log_corpus_pair(
                prompt=prompt, completion=completion,
                title=row_title,
                genre=row_genre,
                character_name=entry.author,
                notes=f"{notes_base} purpose={entry.purpose} medium={entry.medium}",
            )
            n_logged += 1
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
        for label, text in text_blobs:
            if not text or len(text) < 80:
                continue
            paragraphs = [p.strip()
                          for p in re.split(r'\n\s*\n+', text) if p.strip()]
            for para in paragraphs:
                if len(para) < 80 or len(para) > 2500:
                    continue
                if para.lstrip()[:1] in '#-*•':
                    continue
                m = re.match(r'(.+?[.!?])\s+(.+)$', para, re.DOTALL)
                if not m:
                    continue
                opener, rest = m.group(1).strip(), m.group(2).strip()
                if len(rest) < 60:
                    continue
                db.log_corpus_pair(
                    prompt=opener, completion=rest,
                    title=entry.name,
                    voice="",
                    genre=genre_tag,
                    character_name=entry.author or "",
                    notes=f"{notes_base} file={label}")
                n_logged += 1
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
        downloaded = _download(entry.url, dest, on_progress=on_progress)
        log(f"  saved {downloaded:,} bytes to {dest}")

    log("Parsing with adapter: " + entry.format)
    raw = _read_text(dest)
    passages = adapter_parse(entry.format, raw, title=entry.name)
    log(f"  extracted {len(passages)} passages")

    # Log corpus pairs (first sentence as prompt, rest as completion).
    # This teaches the model to continue prose in the source's voice.
    import re
    n_logged = 0
    for para in passages:
        m = re.match(r'(.+?[.!?])\s+(.+)$', para, re.DOTALL)
        if not m:
            continue
        opener = m.group(1).strip()
        rest = m.group(2).strip()
        if len(rest) < 60:
            continue
        notes = (f"corpus_id={entry.id} license={entry.license} "
                 f"author={entry.author}").strip()
        db.log_corpus_pair(prompt=opener, completion=rest,
                           title=entry.name,
                           genre=" ".join(entry.tags[:3]),
                           character_name=entry.author,
                           notes=notes)
        n_logged += 1
    log(f"  logged {n_logged} corpus pairs to learning DB")

    return IngestResult(
        entry=entry,
        bytes_downloaded=downloaded,
        passages_found=len(passages),
        passages_logged=n_logged,
        db_path=db.db_path,
    )
