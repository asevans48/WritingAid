"""9.2 addendum (24 Nov 2026): the writer's contact details on the standard
manuscript title page, edited in one place (Publishing tab; also Settings)."""

import json
import os
import zipfile

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from docx import Document
from docx.shared import Inches

from src.data import writer_contact as wc
from src.export import standard_manuscript as sm
from src.models.project import Chapter, Manuscript, WriterProject

SCRATCH = ("/private/tmp/claude-501/-Users-aseva-gitcode-WritingAid/"
           "3d64fcf9-08aa-4695-bd52-3a5591f01962/scratchpad")

FULL = {"name": "Mary Ellen Smith", "phone": "(555) 123-4567",
        "email": "mary@example.com", "address": "12 Harbor Road\n\nPortland, ME 04101\n"}


class FakeConfig:
    """``CreativeOSConfig``'s get/set, in memory."""
    def __init__(self, settings=None):
        self.settings = dict(settings or {})

    def get(self, key, default=None):
        return self.settings.get(key, default)

    def set(self, key, value):
        self.settings[key] = value


def _manuscript(author="Perry Slaughter"):
    m = Manuscript(title="Silvertide", author=author)
    m.chapters = [Chapter(id="c1", number=1, title="A Silver Tide",
                          content="Rain *fell*.\n\n***\n\nMorning came.")]
    return m


def _write(tmp_path, ms, contact, name="book.docx"):
    path = tmp_path / name
    assert sm.write(ms, str(path), contact=contact)
    return path


def _title_page(doc):
    texts = [p.text for p in doc.paragraphs]
    end = next(i for i, t in enumerate(texts) if t.startswith("about "))
    return texts[:end + 1]


# ── Nothing filled in: the title page is exactly as before ─────────────

@pytest.mark.parametrize("author", ["Perry Slaughter", ""])
def test_empty_details_change_nothing(tmp_path, author):
    empty = _write(tmp_path, _manuscript(author), {}, "a.docx")
    blank = _write(tmp_path, _manuscript(author), {f: "" for f in wc.FIELDS}, "b.docx")
    with zipfile.ZipFile(empty) as a, zipfile.ZipFile(blank) as b:
        for part in ("word/document.xml", "word/header1.xml", "word/styles.xml"):
            assert a.read(part) == b.read(part)
    doc = Document(str(empty))
    if author:
        assert _title_page(doc) == ["Perry Slaughter", "Silvertide",
                                    "A Novel by Perry Slaughter", "about 100 words"]
        assert doc.paragraphs[0].paragraph_format.line_spacing is None   # as before: Normal
    else:
        assert _title_page(doc) == ["Silvertide", "about 100 words"]
    title = next(p for p in doc.paragraphs if p.text == "Silvertide")
    assert title.paragraph_format.space_before == Inches(3)
    header = doc.sections[1].header.paragraphs[0].text
    assert header.startswith("Slaughter / Silvertide / " if author else "Silvertide / ")


def test_export_with_no_stored_details_reads_defaults(tmp_path, monkeypatch):
    monkeypatch.setattr(wc, "_config", lambda config=None: FakeConfig())
    path = tmp_path / "x.docx"
    assert sm.write(_manuscript(), str(path))                  # contact loaded, empty
    assert _title_page(Document(str(path)))[0] == "Perry Slaughter"


# ── Filled in: Shunn's top-left block and the byline ──────────────────

def test_full_details_on_the_title_page(tmp_path):
    os.makedirs(SCRATCH, exist_ok=True)
    path = _write(tmp_path, _manuscript("Perry Slaughter"), FULL)
    doc = Document(str(path))
    assert _title_page(doc) == [
        "Mary Ellen Smith", "12 Harbor Road", "Portland, ME 04101",
        "(555) 123-4567", "mary@example.com",
        "Silvertide", "A Novel by Perry Slaughter", "about 100 words"]
    for p in doc.paragraphs[:5]:
        assert p.paragraph_format.line_spacing == 1.0          # single-spaced block
        assert p.paragraph_format.alignment in (None, 0)       # top left
    assert doc.sections[1].header.paragraphs[0].text.startswith("Slaughter / Silvertide / ")
    # A sample for the writer to open (the scratch folder may be cleared).
    _write_sample = os.path.join(SCRATCH, "sample-title-page-with-contact.docx")
    sm.write(_manuscript("Perry Slaughter"), _write_sample, contact=FULL)
    assert [p.text for p in Document(_write_sample).paragraphs[:5]] == _title_page(doc)[:5]


def test_byline_falls_back_to_the_name_and_blank_fields_are_left_out(tmp_path):
    doc = Document(str(_write(tmp_path, _manuscript(""), {"name": "Mary Smith",
                                                         "email": "m@example.com"})))
    assert _title_page(doc) == ["Mary Smith", "m@example.com", "Silvertide",
                                "A Novel by Mary Smith", "about 100 words"]
    assert doc.sections[1].header.paragraphs[0].text.startswith("Smith / Silvertide / ")


def test_name_only_looks_like_the_old_author_line(tmp_path):
    a = _write(tmp_path, _manuscript("Perry Slaughter"), {}, "a.docx")
    b = _write(tmp_path, _manuscript(""), {"name": "Perry Slaughter"}, "b.docx")
    with zipfile.ZipFile(a) as za, zipfile.ZipFile(b) as zb:
        assert za.read("word/document.xml") == zb.read("word/document.xml")


# ── Storage: app-wide, new key only ───────────────────────────────────

def test_stored_once_for_the_app_and_other_settings_kept(tmp_path, monkeypatch):
    import src.config.creativeos_config as cc
    monkeypatch.setattr(cc, "CREATIVEOS_DIR", tmp_path)
    monkeypatch.setattr(cc, "CREATIVEOS_CONFIG_FILE", tmp_path / "config.json")
    old = {"default_llm": "server", "server_url": "http://x", "something_else": [1, 2]}
    (tmp_path / "config.json").write_text(json.dumps(old))
    cfg = cc.CreativeOSConfig()
    assert wc.load(cfg) == {f: "" for f in wc.FIELDS}          # an old settings file opens as is
    wc.set_field("phone", "555", cfg)
    wc.set_field("address", "1 Road\nTown", cfg)
    on_disk = json.loads((tmp_path / "config.json").read_text())
    for k, v in old.items():
        assert on_disk[k] == v
    assert on_disk["writer_contact"] == {"phone": "555", "address": "1 Road\nTown"}
    assert wc.load(cc.CreativeOSConfig())["address"] == "1 Road\nTown"


def test_damaged_values_read_as_empty_and_unknown_keys_kept():
    cfg = FakeConfig({"writer_contact": {"name": 5, "email": "e@x", "fax": "1"}})
    assert wc.load(cfg) == {"name": "", "phone": "", "email": "e@x", "address": ""}
    wc.set_field("name", "N", cfg)
    assert cfg.settings["writer_contact"]["fax"] == "1"
    assert wc.load(FakeConfig({"writer_contact": "junk"})) == {f: "" for f in wc.FIELDS}
    with pytest.raises(ValueError):
        wc.set_field("fax", "1", cfg)


def test_pen_name_is_the_project_s_byline_and_survives_save_and_load(tmp_path):
    p = WriterProject(name="Book")
    p.manuscript.author = "Old Name"
    sp = p.create_subproject("Novella")
    own = p.create_subproject("Other")
    own.manuscript.author = "Someone Else"
    path = tmp_path / "book.json"
    p.save_project(str(path))
    loaded = WriterProject.load_project(str(path))
    wc.set_pen_name(loaded, "M. E. Smith")
    assert wc.pen_name(loaded) == "M. E. Smith"
    loaded.save_project(str(path))
    again = WriterProject.load_project(str(path))
    assert again.get_main_manuscript().author == "M. E. Smith"
    by_name = {s.name: s.manuscript.author for s in again.subprojects}
    assert by_name == {"Novella": "M. E. Smith", "Other": "Someone Else"}
    assert sp.id in {s.id for s in again.subprojects}


# ── The form ──────────────────────────────────────────────────────────

@pytest.fixture
def app():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def test_publishing_tab_form_stores_as_typed(app):
    from src.ui.writer_contact_form import ContactForm
    cfg = FakeConfig({"writer_contact": {"email": "kept@x"}})
    form = ContactForm(config=cfg)
    assert form.email.text() == "kept@x"
    assert not form.pen.isVisibleTo(form)                      # no project, no pen name row
    form.phone.setText("555")
    form.address.setPlainText("1 Road\nTown")
    assert wc.load(cfg) == {"name": "", "phone": "555", "email": "kept@x",
                            "address": "1 Road\nTown"}
    p = WriterProject(name="Book")
    p.manuscript.author = "Pen"
    seen = []
    form.changed.connect(lambda: seen.append(1))
    form.set_project(p)
    assert form.pen.text() == "Pen" and form.pen.isVisibleTo(form) and not seen
    form.pen.setText("New Pen")
    assert p.manuscript.author == "New Pen" and seen


def test_settings_page_stores_on_save_only(app):
    from src.ui.writer_contact_form import settings_page
    cfg = FakeConfig()
    page = settings_page(config=cfg)
    page.form.name.setText("Mary")
    assert wc.load(cfg)["name"] == ""                          # Cancel would leave it
    page.form.save()
    assert wc.load(cfg)["name"] == "Mary"


def test_publishing_tab_has_the_form_and_no_new_buttons(app):
    from PyQt6.QtWidgets import QGroupBox, QPushButton, QToolButton
    from src.ui.agent_manager_widget import AgentManagerWidget
    w = AgentManagerWidget()
    assert w.contact_form is not None
    assert not w.contact_form.findChildren((QPushButton, QToolButton, QGroupBox))
