"""Unified dataset importer — handles CSV, TSV, JSON, ZIP, Wikipedia, Britannica.

Each format is handled by a dedicated function. The download worker calls
the appropriate one based on DatasetInfo.format.
"""

import io
import logging
import tempfile
import zipfile
from pathlib import Path
from typing import List, Optional, Callable

from src.knowledge.knowledge_store import KnowledgeArticle

logger = logging.getLogger(__name__)

ProgressCallback = Optional[Callable[[str, int, int], None]]


def import_dataset(dataset_info, api_key: str = "",
                   progress: ProgressCallback = None,
                   project=None) -> List[KnowledgeArticle]:
    """Import a dataset based on its format field.

    Args:
        dataset_info: DatasetInfo object from the registry
        api_key: API key if required
        progress: Optional progress callback(message, current, total)

    Returns:
        List of KnowledgeArticle ready for the knowledge store.
    """
    fmt = dataset_info.format

    if fmt == "wikipedia_project":
        return _import_wikipedia_project(dataset_info, progress, project)
    elif fmt == "wikipedia_api":
        return _import_wikipedia_curated(dataset_info, progress)
    elif fmt == "huggingface":
        return _import_huggingface(dataset_info, progress)
    elif fmt == "britannica_api":
        return _import_britannica(dataset_info, api_key, progress)
    elif fmt == "csv":
        return _import_csv_url(dataset_info, progress)
    elif fmt == "tsv":
        return _import_tsv_url(dataset_info, progress)
    elif fmt == "csv_zip":
        return _import_csv_zip(dataset_info, progress)
    elif fmt == "tsv_zip":
        return _import_tsv_zip(dataset_info, progress)
    elif fmt == "json":
        return _import_json_url(dataset_info, progress)
    else:
        raise ValueError(f"Unknown dataset format: {fmt}")


def import_custom_file(file_path: str, source_name: str,
                       progress: ProgressCallback = None) -> List[KnowledgeArticle]:
    """Import a user-provided CSV, TSV, or JSON file into the knowledge store.

    Attempts to auto-detect columns for title and content.
    """
    path = Path(file_path)
    suffix = path.suffix.lower()

    if progress:
        progress(f"Reading {path.name}...", 0, 1)

    if suffix == ".csv":
        return _parse_csv_file(path, source_name)
    elif suffix in (".tsv", ".tab"):
        return _parse_tsv_file(path, source_name)
    elif suffix == ".json":
        return _parse_json_file(path, source_name)
    else:
        raise ValueError(f"Unsupported file format: {suffix}. Use CSV, TSV, or JSON.")


# ── Format handlers ──────────────────────────────────────────────

def _import_wikipedia_project(info, progress: ProgressCallback, project=None) -> list:
    if not project:
        raise ValueError(
            "No project loaded. Open a project first, then download "
            "project-specific Wikipedia articles."
        )
    from src.knowledge.wikipedia_importer import download_project_articles
    articles = download_project_articles(project, progress_callback=progress)
    return [
        KnowledgeArticle(
            title=a["title"], content=a["content"], source=info.id,
            category="Wikipedia (Project)", url=a.get("url", "")
        ) for a in articles if a.get("title") and a.get("content")
    ]


def _import_wikipedia_curated(info, progress: ProgressCallback) -> list:
    from src.knowledge.wikipedia_importer import download_worldbuilding_articles
    articles = download_worldbuilding_articles(progress_callback=progress)
    return [
        KnowledgeArticle(
            title=a["title"], content=a["content"], source=info.id,
            category="Wikipedia", url=a.get("url", "")
        ) for a in articles if a.get("title") and a.get("content")
    ]


def _import_huggingface(info, progress: ProgressCallback) -> list:
    from src.knowledge.wikipedia_importer import download_simple_wikipedia
    articles = download_simple_wikipedia(progress_callback=progress, max_articles=50000)
    return [
        KnowledgeArticle(
            title=a["title"], content=a["content"], source=info.id,
            category="Wikipedia", url=a.get("url", "")
        ) for a in articles if a.get("title") and a.get("content")
    ]


def _import_britannica(info, api_key: str, progress: ProgressCallback) -> list:
    if not api_key:
        raise ValueError("Britannica API key is required.")
    from src.knowledge.britannica_importer import download_britannica_articles
    from src.knowledge.wikipedia_importer import WORLDBUILDING_CATEGORIES
    articles = download_britannica_articles(
        WORLDBUILDING_CATEGORIES[:50], api_key, progress_callback=progress
    )
    return [
        KnowledgeArticle(
            title=a["title"], content=a["content"], source=info.id,
            category="Britannica", url=a.get("url", "")
        ) for a in articles if a.get("title") and a.get("content")
    ]


def _download_url(url: str) -> bytes:
    """Download a URL and return raw bytes."""
    import requests
    resp = requests.get(url, timeout=120, stream=True)
    resp.raise_for_status()
    return resp.content


def _import_csv_url(info, progress: ProgressCallback) -> list:
    if progress:
        progress(f"Downloading {info.name}...", 0, 1)
    data = _download_url(info.source_url)
    return _parse_csv_bytes(data, info.id, info.category)


def _import_tsv_url(info, progress: ProgressCallback) -> list:
    if progress:
        progress(f"Downloading {info.name}...", 0, 1)
    data = _download_url(info.source_url)
    return _parse_tsv_bytes(data, info.id, info.category)


def _import_csv_zip(info, progress: ProgressCallback) -> list:
    if progress:
        progress(f"Downloading {info.name}...", 0, 1)
    data = _download_url(info.source_url)
    return _extract_and_parse_zip(data, info.id, info.category, delimiter=",")


def _import_tsv_zip(info, progress: ProgressCallback) -> list:
    if progress:
        progress(f"Downloading {info.name}...", 0, 1)
    data = _download_url(info.source_url)
    return _extract_and_parse_zip(data, info.id, info.category, delimiter="\t")


def _import_json_url(info, progress: ProgressCallback) -> list:
    if progress:
        progress(f"Downloading {info.name}...", 0, 1)
    import json
    data = _download_url(info.source_url)
    return _parse_json_bytes(data, info.id, info.category)


# ── Parsers ──────────────────────────────────────────────────────

def _guess_title_content_cols(headers: list) -> tuple:
    """Guess which columns hold the title and content."""
    headers_lower = [h.lower().strip() for h in headers]

    title_candidates = ["title", "name", "dish", "city", "person", "term", "word", "entry"]
    content_candidates = ["content", "description", "text", "summary", "abstract",
                          "ingredients", "body", "definition", "notes", "biography"]

    title_col = 0
    content_col = 1 if len(headers) > 1 else 0

    for i, h in enumerate(headers_lower):
        if h in title_candidates:
            title_col = i
            break

    for i, h in enumerate(headers_lower):
        if h in content_candidates:
            content_col = i
            break

    return title_col, content_col


def _row_to_article(row: list, headers: list, title_col: int,
                    content_col: int, source: str, category: str) -> Optional[KnowledgeArticle]:
    """Convert a CSV/TSV row to a KnowledgeArticle, merging all columns as context."""
    if not row or len(row) <= max(title_col, content_col):
        return None

    title = str(row[title_col]).strip()
    if not title:
        return None

    # Build content from all columns (not just the content column)
    parts = []
    for i, val in enumerate(row):
        val = str(val).strip()
        if val and i < len(headers):
            header = headers[i] if i < len(headers) else f"col_{i}"
            if i == title_col:
                continue  # Skip title, it's already the title
            parts.append(f"{header}: {val}")

    content = "\n".join(parts) if parts else str(row[content_col]).strip()
    if not content:
        return None

    return KnowledgeArticle(
        title=title, content=content, source=source, category=category
    )


def _parse_csv_bytes(data: bytes, source: str, category: str) -> list:
    import csv
    text = data.decode("utf-8", errors="replace")
    reader = csv.reader(io.StringIO(text))
    rows = list(reader)
    if len(rows) < 2:
        return []
    headers = rows[0]
    title_col, content_col = _guess_title_content_cols(headers)
    articles = []
    for row in rows[1:]:
        a = _row_to_article(row, headers, title_col, content_col, source, category)
        if a:
            articles.append(a)
    return articles


def _parse_tsv_bytes(data: bytes, source: str, category: str) -> list:
    import csv
    text = data.decode("utf-8", errors="replace")
    reader = csv.reader(io.StringIO(text), delimiter="\t")
    rows = list(reader)
    if len(rows) < 2:
        return []
    headers = rows[0]
    title_col, content_col = _guess_title_content_cols(headers)
    articles = []
    for row in rows[1:]:
        a = _row_to_article(row, headers, title_col, content_col, source, category)
        if a:
            articles.append(a)
    return articles


def _parse_json_bytes(data: bytes, source: str, category: str) -> list:
    import json
    parsed = json.loads(data.decode("utf-8", errors="replace"))
    if isinstance(parsed, list):
        items = parsed
    elif isinstance(parsed, dict):
        # Try common wrapper keys
        for key in ("data", "articles", "entries", "items", "results"):
            if key in parsed and isinstance(parsed[key], list):
                items = parsed[key]
                break
        else:
            items = [parsed]
    else:
        return []

    articles = []
    for item in items:
        if not isinstance(item, dict):
            continue
        title = ""
        for k in ("title", "name", "dish", "term", "entry"):
            if k in item and item[k]:
                title = str(item[k]).strip()
                break
        if not title:
            title = str(list(item.values())[0]).strip()[:80] if item else ""

        parts = []
        for k, v in item.items():
            if k.lower() in ("title", "name", "id", "url") or not v:
                continue
            parts.append(f"{k}: {v}")
        content = "\n".join(parts)

        if title and content:
            articles.append(KnowledgeArticle(
                title=title, content=content, source=source, category=category
            ))
    return articles


def _extract_and_parse_zip(data: bytes, source: str, category: str,
                           delimiter: str) -> list:
    """Extract CSV/TSV files from a ZIP and parse them."""
    articles = []
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        for name in zf.namelist():
            if name.endswith(('.csv', '.tsv', '.txt', '.tab')):
                file_data = zf.read(name)
                if delimiter == "\t":
                    articles.extend(_parse_tsv_bytes(file_data, source, category))
                else:
                    articles.extend(_parse_csv_bytes(file_data, source, category))
    return articles


def _parse_csv_file(path: Path, source: str) -> list:
    return _parse_csv_bytes(path.read_bytes(), source, source)


def _parse_tsv_file(path: Path, source: str) -> list:
    return _parse_tsv_bytes(path.read_bytes(), source, source)


def _parse_json_file(path: Path, source: str) -> list:
    return _parse_json_bytes(path.read_bytes(), source, source)
