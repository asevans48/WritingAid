"""Standard manuscript format for agent submissions (piece 9.2).

"Export Publisher Ready" writes this. It follows William Shunn's novel
manuscript format as his sample manuscript shows it
(https://www.shunn.net/format/novel/), with what the sample does not show
taken from the common standard; ``docs/publishing/export_checklist.md``
says which is which. An agent's or publisher's own guidelines override.

* **Title page**, no header: at the top left the writer's real name,
  address, phone and email (single-spaced; from ``writer_contact``, the
  manuscript's author when no name is set; empty fields left out), the
  title about halfway down with "A Novel by <byline>" under it (the pen
  name, else the name), and "about N words" near the bottom.
* **Every text page** has a header at the right: "Surname / Title / N",
  numbered from 1 on the first page of text.
* **Body:** Times New Roman 12 point, double-spaced, 1-inch margins, the
  first line of each paragraph indented half an inch, no extra space
  between paragraphs, left-aligned (not justified).
* **Each chapter starts on a new page,** its heading about a third of the
  way down, centered, in the body font: "Chapter N" and the chapter's
  title on the next line (when the title is not already "Chapter …",
  "Prologue", …).
* **Scene breaks** (a line of ``***``, ``* * *``, ``#`` …) become a centered
  "#".
* **Italics and bold** written in the editor (``*word*``, ``**word**``)
  come out as italics and bold, never as asterisks.

Reads the manuscript only; writes only the file it is given.
"""

from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Optional

from docx import Document
from docx.enum.section import WD_SECTION
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches, Pt, RGBColor

from src.utils.markdown_editor import get_line_style, inline_runs, is_scene_break, MarkdownStyle

FONT = "Times New Roman"
SIZE = Pt(12)
CHAPTER_DROP = Inches(2.5)        # space above a chapter heading: about a third down
TITLE_DROP = Inches(3)
WORDS_DROP = Inches(3)
NAMED_STARTS = ("chapter", "prologue", "epilogue", "part ", "interlude", "afterword",
                "foreword", "preface", "introduction")


def approximate_words(n: int) -> str:
    """"about 80,000 words": to the nearest thousand from 10,000 words, to
    the nearest hundred below that."""
    step = 1000 if n >= 10_000 else 100
    rounded = max(step, int(round(n / step)) * step) if n else 0
    return f"about {rounded:,} words"


def surname(author: str) -> str:
    parts = [p for p in re.split(r"\s+", (author or "").strip()) if p]
    return parts[-1] if parts else ""


def chapter_heading_lines(chapter: Any, index: int) -> List[str]:
    title = (getattr(chapter, "title", "") or "").strip()
    number = getattr(chapter, "number", None) or index
    if not title:
        return [f"Chapter {number}"]
    if title.lower().startswith(NAMED_STARTS):
        return [title]
    return [f"Chapter {number}", title]


def _set_font(style_or_run_font) -> None:
    style_or_run_font.name = FONT
    style_or_run_font.size = SIZE


def _style(doc) -> None:
    normal = doc.styles["Normal"]
    _set_font(normal.font)
    normal.element.rPr.rFonts.set(qn("w:eastAsia"), FONT)
    pf = normal.paragraph_format
    pf.line_spacing = 2.0
    pf.space_before = Pt(0)
    pf.space_after = Pt(0)
    pf.first_line_indent = Inches(0.5)
    pf.alignment = WD_ALIGN_PARAGRAPH.LEFT
    # Chapter headings keep the Heading 1 style (Word's navigation pane and
    # the app's own import use it), drawn in the body font.
    h1 = doc.styles["Heading 1"]
    _set_font(h1.font)
    h1.font.bold = False
    h1.font.italic = False
    h1.font.color.rgb = RGBColor(0, 0, 0)
    hpf = h1.paragraph_format
    hpf.alignment = WD_ALIGN_PARAGRAPH.CENTER
    hpf.first_line_indent = Inches(0)
    hpf.line_spacing = 2.0
    hpf.space_after = Pt(0)
    hpf.keep_with_next = True


def _margins(section) -> None:
    for side in ("top_margin", "bottom_margin", "left_margin", "right_margin"):
        setattr(section, side, Inches(1))


def _plain(doc, text: str = "", align=None, indent: bool = False, before=None):
    p = doc.add_paragraph()
    if text:
        p.add_run(text)
    pf = p.paragraph_format
    if align is not None:
        pf.alignment = align
    if not indent:
        pf.first_line_indent = Inches(0)
    if before is not None:
        pf.space_before = before
    return p


def _page_field(run) -> None:
    """A PAGE field: the page number, filled in by the word processor."""
    begin = OxmlElement("w:fldChar")
    begin.set(qn("w:fldCharType"), "begin")
    code = OxmlElement("w:instrText")
    code.set(qn("xml:space"), "preserve")
    code.text = " PAGE "
    end = OxmlElement("w:fldChar")
    end.set(qn("w:fldCharType"), "end")
    for el in (begin, code, end):
        run._r.append(el)


def _number_from_one(section) -> None:
    sect = section._sectPr
    for old in sect.findall(qn("w:pgNumType")):
        sect.remove(old)
    pg = OxmlElement("w:pgNumType")
    pg.set(qn("w:start"), "1")
    sect.append(pg)


def _body(doc, content: str, heading_lines: Iterable[str]) -> None:
    from src.export.manuscript_exporter import _paragraphs
    skip = {h.strip().lower() for h in heading_lines}
    for para in _paragraphs(content):
        if is_scene_break(para):
            _plain(doc, "#", align=WD_ALIGN_PARAGRAPH.CENTER)
            continue
        style, text = get_line_style(para)
        if style != MarkdownStyle.NORMAL:
            if text.strip().lower() in skip:          # the chapter's own title, again
                continue
            _plain(doc, text.strip(), align=WD_ALIGN_PARAGRAPH.CENTER)
            continue
        p = doc.add_paragraph()
        for chunk, bold, italic in inline_runs(para):
            run = p.add_run(chunk)
            if bold:
                run.bold = True
            if italic:
                run.italic = True


def write(manuscript: Any, output_path: str, kind: str = "Novel",
          contact: Optional[Dict[str, str]] = None) -> bool:
    """Write ``manuscript`` (a ``Manuscript``) in standard manuscript format.
    ``contact`` is the writer's details (``writer_contact.load()`` when not
    given)."""
    from src.data import writer_contact
    if contact is None:
        contact = writer_contact.load()
    doc = Document()
    _style(doc)
    title = (getattr(manuscript, "title", "") or "Untitled").strip()
    author = writer_contact.byline(getattr(manuscript, "author", "") or "", contact)
    block = writer_contact.contact_block(getattr(manuscript, "author", "") or "", contact)
    chapters = list(getattr(manuscript, "chapters", None) or [])
    # Counted from the text (the stored total can be out of date).
    from src.utils.markdown_editor import strip_markdown
    words = sum(len(strip_markdown(getattr(c, "content", "") or "").split()) for c in chapters) \
        or int(getattr(manuscript, "total_word_count", 0) or 0)

    # Title page (its own section: no header, not numbered).
    first = doc.sections[0]
    _margins(first)
    for line in block:
        p = _plain(doc, line)
        if len(block) > 1:                    # Shunn's contact block is single-spaced
            p.paragraph_format.line_spacing = 1.0
    # The title stays about halfway down however long the block is.
    drop = TITLE_DROP if len(block) <= 1 else max(Inches(1), TITLE_DROP - Pt(12) * (len(block) - 1))
    _plain(doc, title, align=WD_ALIGN_PARAGRAPH.CENTER, before=drop)
    if author:
        _plain(doc, f"A {kind} by {author}", align=WD_ALIGN_PARAGRAPH.CENTER)
    _plain(doc, approximate_words(words), align=WD_ALIGN_PARAGRAPH.CENTER, before=WORDS_DROP)

    # The text: a new section with the running header, numbered from 1.
    text = doc.add_section(WD_SECTION.NEW_PAGE)
    _margins(text)
    _number_from_one(text)
    header = text.header
    header.is_linked_to_previous = False
    hp = header.paragraphs[0] if header.paragraphs else header.add_paragraph()
    hp.paragraph_format.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    hp.paragraph_format.first_line_indent = Inches(0)
    hp.paragraph_format.line_spacing = 1.0
    name = surname(author)
    hp.add_run(f"{name} / {title} / " if name else f"{title} / ")
    _page_field(hp.add_run())

    for i, chapter in enumerate(chapters, 1):
        lines = chapter_heading_lines(chapter, i)
        for n, line in enumerate(lines):
            h = doc.add_paragraph(line, style="Heading 1")
            if n == 0:
                h.paragraph_format.space_before = CHAPTER_DROP
                h.paragraph_format.page_break_before = i > 1
        _body(doc, getattr(chapter, "content", "") or "", lines)
    doc.save(output_path)
    return True
