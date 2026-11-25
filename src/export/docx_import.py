"""A Word document as the editor's text (piece 9.2).

The editor stores a chapter as Markdown: ``*italic*``, ``**bold**`` and
``# heading`` lines. Importing used to put Word's italics and headings into
the editor as display formatting only, so they were lost when the chapter
was saved. Here they become Markdown, which the editor shows formatted and
saves as written.

* Word's "Title" style → ``# ``; "Heading 1" → ``## `` … (the editor's own
  mapping, ``markdown_editor.HEADING_PREFIXES``).
* Italic and bold runs → ``*…*``, ``**…**``, ``***…***``.
* One line per Word paragraph; an empty paragraph stays an empty line.

Font names, sizes and colours are not kept: the editor's text has no place
for them (it never had, once saved).

No Qt. Reads the file only.
"""

from __future__ import annotations

from typing import List

from docx import Document

from src.utils.markdown_editor import HEADING_PREFIXES, MarkdownStyle, runs_to_markdown

_HEADINGS = {
    "Title": HEADING_PREFIXES[MarkdownStyle.TITLE],
    "Heading 1": HEADING_PREFIXES[MarkdownStyle.HEADING_1],
    "Heading 2": HEADING_PREFIXES[MarkdownStyle.HEADING_2],
    "Heading 3": HEADING_PREFIXES[MarkdownStyle.HEADING_3],
    "Heading 4": HEADING_PREFIXES[MarkdownStyle.HEADING_4],
}


def paragraph_markdown(para) -> str:
    style = para.style.name if para.style is not None else ""
    prefix = _HEADINGS.get(style)
    if prefix is not None:
        return prefix + para.text.strip() if para.text.strip() else ""
    runs = [(r.text, bool(r.bold), bool(r.italic)) for r in para.runs]
    return runs_to_markdown(runs)


def docx_to_markdown(file_path: str) -> str:
    doc = Document(file_path)
    lines: List[str] = [paragraph_markdown(p) for p in doc.paragraphs]
    while lines and not lines[-1].strip():
        lines.pop()
    return "\n".join(lines)
