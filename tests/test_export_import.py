"""9.2: export and import check. Each test is a line of
docs/publishing/export_checklist.md, checked on the exported file."""

import os
import zipfile

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.shared import Inches, Pt

from src.models.project import Chapter, Manuscript

ONE = ("The rain had not stopped for *three* days.\n\n"
       "Mara looked at the **harbor** & the boats < the pier.\n\n"
       "***\n\n"
       "Morning came. She said, “Go.” — and left.")
TWO = "Prologue words here.\n\nAnother *one*."


def _manuscript():
    m = Manuscript(title="Silvertide", author="Perry Slaughter")
    m.chapters = [Chapter(id="c1", number=1, title="A Silver Tide", content=ONE),
                  Chapter(id="c2", number=2, title="Prologue", content=TWO)]
    return m


@pytest.fixture
def standard(tmp_path):
    from src.export.manuscript_exporter import ManuscriptExporter
    path = tmp_path / "book.docx"
    assert ManuscriptExporter(_manuscript()).export_publisher_ready(str(path))
    return Document(str(path))


def _texts(doc):
    return [p.text for p in doc.paragraphs]


# ── Agent submission: standard manuscript format ──────────────────────

def test_body_font_spacing_indent(standard):
    normal = standard.styles["Normal"]
    assert normal.font.name == "Times New Roman" and normal.font.size == Pt(12)
    pf = normal.paragraph_format
    assert pf.line_spacing == 2.0 and pf.first_line_indent == Inches(0.5)
    assert pf.space_after == Pt(0) and pf.space_before == Pt(0)
    assert pf.alignment == WD_ALIGN_PARAGRAPH.LEFT            # ragged right, not justified


def test_margins_one_inch_on_every_section(standard):
    for s in standard.sections:
        assert s.top_margin == s.bottom_margin == s.left_margin == s.right_margin == Inches(1)


def test_title_page(standard):
    t = _texts(standard)
    assert t[0] == "Perry Slaughter"                          # top left
    assert standard.paragraphs[0].paragraph_format.alignment in (None, WD_ALIGN_PARAGRAPH.LEFT)
    i = t.index("Silvertide")
    assert standard.paragraphs[i].paragraph_format.alignment == WD_ALIGN_PARAGRAPH.CENTER
    assert t[i + 1] == "A Novel by Perry Slaughter"
    assert "about 100 words" in t                             # 35 words, counted from the text
    assert not standard.sections[0].header.paragraphs[0].text.strip()   # no header on it


def test_word_count_is_rounded():
    from src.export.standard_manuscript import approximate_words
    assert approximate_words(81_420) == "about 81,000 words"
    assert approximate_words(7_260) == "about 7,300 words"


def test_running_header_numbered_from_one(standard):
    text = standard.sections[1]
    assert not text.header.is_linked_to_previous
    hp = text.header.paragraphs[0]
    assert hp.text.startswith("Slaughter / Silvertide / ")
    assert hp.paragraph_format.alignment == WD_ALIGN_PARAGRAPH.RIGHT
    assert "PAGE" in "".join(e.text or "" for e in hp._p.iter(qn("w:instrText")))
    pg = text._sectPr.find(qn("w:pgNumType"))
    assert pg is not None and pg.get(qn("w:start")) == "1"


def test_each_chapter_starts_on_a_new_page_with_a_plain_centered_heading(standard):
    heads = [p for p in standard.paragraphs if p.style.name == "Heading 1"]
    assert [h.text for h in heads] == ["Chapter 1", "A Silver Tide", "Prologue"]
    h1 = standard.styles["Heading 1"]
    assert h1.font.name == "Times New Roman" and h1.font.size == Pt(12) and not h1.font.bold
    assert all(h.paragraph_format.alignment in (None, WD_ALIGN_PARAGRAPH.CENTER) for h in heads)
    assert heads[0].paragraph_format.space_before >= Inches(2)   # about a third down
    assert heads[2].paragraph_format.page_break_before           # chapter 2: new page
    assert standard.sections[1].start_type is not None           # chapter 1: new section/page


def test_scene_break_is_a_centered_hash(standard):
    breaks = [p for p in standard.paragraphs if p.text == "#"]
    assert len(breaks) == 1
    assert breaks[0].paragraph_format.alignment == WD_ALIGN_PARAGRAPH.CENTER


def test_italics_are_italics_not_asterisks(standard):
    assert not any("*" in t for t in _texts(standard))
    runs = [r for p in standard.paragraphs for r in p.runs]
    assert any(r.text == "three" and r.italic for r in runs)
    assert any(r.text == "harbor" and r.bold for r in runs)
    assert any("“Go.” —" in t for t in _texts(standard))   # quotes and dashes kept


def test_novella_kind_on_the_title_page(tmp_path):
    from src.export.manuscript_exporter import ManuscriptExporter
    path = tmp_path / "n.docx"
    ManuscriptExporter(_manuscript()).export_publisher_ready(str(path), kind="Novella")
    assert "A Novella by Perry Slaughter" in _texts(Document(str(path)))


# ── Self-publishing: EPUB for Kindle and Barnes & Noble ───────────────

def _epub(tmp_path, name="book.epub", kind="kindle"):
    from src.export.manuscript_exporter import ManuscriptExporter
    path = tmp_path / name
    ex = ManuscriptExporter(_manuscript())
    assert (ex.export_for_kindle if kind == "kindle" else ex.export_for_barnes_noble)(str(path))
    return path


def test_epub_chapters_are_valid_xhtml_with_real_italics(tmp_path):
    from lxml import etree
    path = _epub(tmp_path)
    with zipfile.ZipFile(path) as z:
        chapters = sorted(n for n in z.namelist() if n.endswith(".xhtml") and "chapter_" in n)
        assert len(chapters) == 2
        for n in chapters:
            etree.fromstring(z.read(n))                       # parses: escaped, well formed
        one = z.read(chapters[0]).decode()
        assert "<em>three</em>" in one and "<strong>harbor</strong>" in one
        assert "&amp;" in one and "&lt;" in one and "*" not in one.replace("* * *", "")
        assert "* * *" in one                                  # the scene break
        assert z.read("mimetype") == b"application/epub+zip"


def test_epub_metadata_toc_and_a_stable_identifier(tmp_path):
    from ebooklib import epub
    a = epub.read_epub(str(_epub(tmp_path, "a.epub")))
    b = epub.read_epub(str(_epub(tmp_path, "b.epub", kind="bn")))
    assert a.get_metadata("DC", "title")[0][0] == "Silvertide"
    assert a.get_metadata("DC", "creator")[0][0] == "Perry Slaughter"
    assert a.get_metadata("DC", "language")[0][0] == "en"
    ident = a.get_metadata("DC", "identifier")[0][0]
    assert ident.startswith("urn:uuid:") and ident == b.get_metadata("DC", "identifier")[0][0]
    assert [t.title for t in a.toc] == ["A Silver Tide", "Prologue"]


# ── Other formats: no asterisks ────────────────────────────────────────

def test_word_rtf_text_keep_formatting_without_asterisks(tmp_path):
    from src.export.manuscript_exporter import ManuscriptExporter
    ex = ManuscriptExporter(_manuscript())
    ex.export_document(str(tmp_path / "b.docx"), "docx")
    doc = Document(str(tmp_path / "b.docx"))
    assert any(r.italic and r.text == "three" for p in doc.paragraphs for r in p.runs)
    ex.export_document(str(tmp_path / "b.txt"), "txt")
    assert "*three*" not in (tmp_path / "b.txt").read_text() and "three days" in \
        (tmp_path / "b.txt").read_text()
    ex.export_document(str(tmp_path / "b.rtf"), "rtf")
    assert r"\i three\i0" in (tmp_path / "b.rtf").read_text()


# ── Import from Word ──────────────────────────────────────────────────

def test_import_keeps_italics_bold_and_headings(tmp_path):
    from src.export.docx_import import docx_to_markdown
    doc = Document()
    doc.add_heading("The Storm", 1)
    p = doc.add_paragraph("She ")
    p.add_run("ran").italic = True
    p.add_run(" to the ")
    p.add_run("harbor").bold = True
    p.add_run(".")
    doc.add_paragraph("")
    doc.add_paragraph("Next line.")
    doc.save(str(tmp_path / "in.docx"))
    assert docx_to_markdown(str(tmp_path / "in.docx")) == \
        "## The Storm\nShe *ran* to the **harbor**.\n\nNext line."


def test_round_trip_through_standard_format_keeps_the_prose(tmp_path, standard):
    from src.export.docx_import import paragraph_markdown
    from src.export.manuscript_exporter import _paragraphs
    body = [paragraph_markdown(p) for p in standard.paragraphs if p.style.name == "Normal"]
    for para in _paragraphs(ONE) + _paragraphs(TWO):
        if para.strip() == "***":
            assert "#" in body                                 # the break, as a "#"
        else:
            assert para in body, para


@pytest.fixture(scope="module")
def app():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def test_importing_into_a_chapter_is_one_undo_step(app, tmp_path):
    from src.ui.enhanced_text_editor import EnhancedTextEditor
    doc = Document()
    doc.add_paragraph("New text from Word.")
    doc.save(str(tmp_path / "in.docx"))
    ed = EnhancedTextEditor()
    ed.setPlainText("My chapter, written by hand.")
    assert ed.import_from_docx(str(tmp_path / "in.docx"))
    assert ed.toPlainText() == "New text from Word."
    ed.undo()
    assert ed.toPlainText() == "My chapter, written by hand."   # nothing lost


def test_import_asks_before_replacing_text_and_defaults_to_cancel(app, monkeypatch):
    from PyQt6.QtWidgets import QMessageBox
    from src.ui import import_guard
    assert import_guard.may_replace(None, "   ")               # empty: no question
    seen = {}

    def exec_(box):
        seen["default"] = box.defaultButton().text()
        seen["text"] = box.text()
        return 0
    monkeypatch.setattr(QMessageBox, "exec", exec_)
    assert not import_guard.may_replace(None, "Some words here.")
    assert "3 words" in seen["text"] and seen["default"] == "Cancel"


# ── The Export menu follows the publishing goal ───────────────────────

def test_the_route_s_format_comes_first(monkeypatch):
    from types import SimpleNamespace as NS
    from PyQt6.QtWidgets import QApplication, QMenu
    QApplication.instance() or QApplication([])
    from src.ui import export_route
    menu = QMenu()
    for t in export_route.FORMATS:
        menu.addAction(t)
    menu.addSeparator()
    menu.addAction("Export Book &Outline (Chapter Plans)")
    monkeypatch.setattr(export_route, "_goal", lambda p: NS(route="agent", kind="novel"))
    export_route.order(menu, object())
    names = [a.text() for a in menu.actions() if a.text()]
    assert names[0] == "Export &Publisher Ready" and len(names) == 5
    assert names[-1] == "Export Book &Outline (Chapter Plans)"
    monkeypatch.setattr(export_route, "_goal", lambda p: NS(route="self", kind="novella"))
    export_route.order(menu, object())
    assert [a.text() for a in menu.actions() if a.text()][0] == "Export for &Kindle"
    assert export_route.kind_label(object()) == "Novella"
