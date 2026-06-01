"""Native print support for chapters and whole manuscripts.

Two entry points:
    print_chapter(parent, chapter)             # one chapter
    print_manuscript(parent, manuscript, name) # all chapters

Each opens the platform's standard QPrintDialog so the user can pick
a printer, page range, copies, etc., then renders the chapter prose
to a QTextDocument and prints it. The dialog handles printer
discovery — we do not enumerate printers ourselves.

Design notes:
  * HTML rendering via QTextDocument keeps the formatting clean and
    works identically on macOS / Linux / Windows.
  * Page breaks between chapters use CSS ``page-break-before: always``
    which QTextDocument respects when printing.
  * If a chapter has ``html_content``, prefer it (preserves italics /
    bold from the rich-text editor); fall back to plain ``content``
    wrapped in paragraphs.
  * ``manuscript_to_html`` is exposed for tests so the formatter can
    be exercised without spinning up a QPrintDialog.
"""

from __future__ import annotations

import html
from typing import Any, List, Optional

from PyQt6.QtCore import QMarginsF
from PyQt6.QtGui import QPageLayout, QPageSize, QTextDocument
from PyQt6.QtPrintSupport import QPrintDialog, QPrinter
from PyQt6.QtWidgets import QMessageBox, QWidget


# ---------------------------------------------------------------------
# HTML rendering — pure functions, no Qt dialogs
# ---------------------------------------------------------------------
_DOC_CSS = """
<style>
  body {
    font-family: 'Georgia', 'Times New Roman', serif;
    font-size: 12pt;
    line-height: 1.5;
  }
  h1.chapter-title {
    font-size: 18pt;
    font-weight: bold;
    text-align: center;
    margin-top: 2em;
    margin-bottom: 2em;
    page-break-after: avoid;
  }
  h1.chapter-title.page-break {
    page-break-before: always;
  }
  p { margin: 0 0 1em 0; text-indent: 1.5em; }
  p.first { text-indent: 0; }
  .manuscript-header {
    text-align: center;
    margin-bottom: 3em;
    font-size: 14pt;
  }
  .manuscript-header .title { font-weight: bold; font-size: 22pt; }
  .chapter-blank {
    font-style: italic;
    color: #666;
    text-align: center;
    margin: 1em 0;
  }
</style>
"""


def chapter_to_html(chapter: Any, first_chapter: bool = True) -> str:
    """Render a single chapter as an HTML fragment.

    ``first_chapter`` controls whether the title forces a page break
    before itself. The first chapter in a manuscript should NOT page-
    break (the title page or header is on page 1); subsequent
    chapters should.
    """
    title = (getattr(chapter, "title", "") or "Untitled Chapter").strip()
    number = getattr(chapter, "number", 0)
    body_html = _chapter_body_html(chapter)
    title_class = "chapter-title" + (
        "" if first_chapter else " page-break")
    heading = (
        f"Chapter {number}: {html.escape(title)}"
        if number else html.escape(title))
    return (
        f'<h1 class="{title_class}">{heading}</h1>\n'
        f'{body_html}'
    )


def manuscript_to_html(
    manuscript: Any,
    project_name: str = "",
) -> str:
    """Render an entire manuscript as a single HTML document.

    Chapters appear in their stored order. Page breaks between
    chapters via CSS. A header at the top shows the project name and
    chapter count.
    """
    chapters = list(getattr(manuscript, "chapters", []) or [])
    title = (project_name or "Manuscript").strip()
    header_html = (
        f'<div class="manuscript-header">'
        f'<div class="title">{html.escape(title)}</div>'
        f'<div>{len(chapters)} chapter'
        f'{"" if len(chapters) == 1 else "s"}</div>'
        f'</div>\n'
    )
    if not chapters:
        body = '<p class="chapter-blank">(no chapters in this manuscript)</p>'
    else:
        body = "\n".join(
            chapter_to_html(ch, first_chapter=(i == 0))
            for i, ch in enumerate(chapters))
    return f"<html><head>{_DOC_CSS}</head><body>{header_html}{body}</body></html>"


def single_chapter_html(chapter: Any) -> str:
    """Render one chapter wrapped in the full document shell.

    Used by ``print_chapter`` so the same CSS applies as in the
    manuscript-wide path.
    """
    body = chapter_to_html(chapter, first_chapter=True)
    return f"<html><head>{_DOC_CSS}</head><body>{body}</body></html>"


def _chapter_body_html(chapter: Any) -> str:
    """Prefer the chapter's rich-text HTML if present; otherwise wrap
    plain text in paragraph tags so it prints with paragraph spacing
    rather than as a single wall of text."""
    html_content = (getattr(chapter, "html_content", "") or "").strip()
    if html_content:
        # The editor's html_content already includes markup; trust it.
        return html_content
    plain = (getattr(chapter, "content", "") or "").strip()
    if not plain:
        return '<p class="chapter-blank">(no content)</p>'
    # Split on blank lines into paragraphs; preserve single-line
    # breaks within a paragraph via <br>.
    paragraphs = [p.strip() for p in plain.split("\n\n") if p.strip()]
    rendered = []
    for i, para in enumerate(paragraphs):
        escaped = html.escape(para).replace("\n", "<br>")
        cls = ' class="first"' if i == 0 else ""
        rendered.append(f"<p{cls}>{escaped}</p>")
    return "\n".join(rendered)


# ---------------------------------------------------------------------
# Printer-dialog entry points
# ---------------------------------------------------------------------
def print_chapter(parent: Optional[QWidget], chapter: Any) -> bool:
    """Open the system print dialog and print one chapter.

    Returns True if the user clicked Print and the document was sent
    to the printer; False if the dialog was cancelled or an error
    occurred. Errors surface as a QMessageBox so users see what went
    wrong rather than a silent failure.
    """
    title = (getattr(chapter, "title", "") or "Untitled").strip()
    body_html = single_chapter_html(chapter)
    return _print_html_with_dialog(
        parent, body_html, doc_name=f"Chapter — {title}")


def print_manuscript(
    parent: Optional[QWidget],
    manuscript: Any,
    project_name: str = "",
) -> bool:
    """Open the system print dialog and print every chapter in the
    manuscript, with page breaks between chapters. Returns True on
    success (user printed), False if cancelled or empty."""
    chapters = list(getattr(manuscript, "chapters", []) or [])
    if not chapters:
        QMessageBox.information(
            parent, "Nothing to print",
            "This manuscript has no chapters yet.")
        return False
    body_html = manuscript_to_html(manuscript, project_name=project_name)
    return _print_html_with_dialog(
        parent, body_html,
        doc_name=(project_name or "Manuscript"))


# ---------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------
def _print_html_with_dialog(
    parent: Optional[QWidget],
    html_body: str,
    doc_name: str,
) -> bool:
    """Common path: render html_body via QTextDocument into a QPrinter
    after the user picks a printer via QPrintDialog.

    Errors during print are caught and surfaced to the user, since a
    failed print is the kind of thing they need to know about (driver
    issue, printer offline, etc.) rather than silently swallow.
    """
    printer = QPrinter(QPrinter.PrinterMode.HighResolution)
    printer.setDocName(doc_name)
    # Reasonable defaults; the dialog lets the user override.
    layout = QPageLayout(
        QPageSize(QPageSize.PageSizeId.Letter),
        QPageLayout.Orientation.Portrait,
        QMarginsF(20, 20, 20, 20),  # mm
        QPageLayout.Unit.Millimeter,
    )
    printer.setPageLayout(layout)

    dialog = QPrintDialog(printer, parent)
    dialog.setWindowTitle(f"Print: {doc_name}")
    if dialog.exec() != QPrintDialog.DialogCode.Accepted:
        return False

    try:
        doc = QTextDocument()
        doc.setHtml(html_body)
        doc.print(printer)
    except Exception as e:
        QMessageBox.critical(
            parent, "Print failed",
            f"Could not print '{doc_name}':\n{e}")
        return False
    return True
