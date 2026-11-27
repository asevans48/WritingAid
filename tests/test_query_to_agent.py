"""9.3 addendum: the query letter addressed to the agent chosen in the agent
list, and Compose Email opening it as a draft. No model; nothing sent."""

import os
from urllib.parse import parse_qs, unquote, urlsplit

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from src.ai import query_address as qa
from src.ai import submission_package as sp
from src.data import submission_store as store
from src.models.project import AgentContact

from tests.test_submission_package import _no_real_settings, _project, _settle, app  # noqa: F401

VOSS = AgentContact(id="a1", name="Ada Voss", agency="Harbour Literary",
                    email="ada@harbour.example",
                    notes="Met at a conference.\nRepresents: gothic and literary horror.")
PLAIN = AgentContact(id="a2", name="Ben Kerr")


def _tab(tmp_path, app, monkeypatch, agents=(VOSS, PLAIN)):
    from src.ui import query_email, submission_package_view as spv
    from src.ui.agent_manager_widget import AgentManagerWidget
    monkeypatch.setattr(spv, "ai_available", lambda: False)
    opened = []
    monkeypatch.setattr(query_email, "open_url", lambda url: opened.append(url) or True)
    path, p = _project(tmp_path)
    p.agent_contacts = [a.model_copy() for a in agents]
    w = AgentManagerWidget()
    w.load_data(p.agent_contacts)
    w.set_project(p)
    w.resize(1024, 600)
    w.show()
    return w, p, opened


def _body(url):
    q = parse_qs(urlsplit(url).query)
    return q["body"][0].replace("\r\n", "\n"), q["subject"][0], unquote(urlsplit(url).path)


# ── The letter, no Qt ──────────────────────────────────────────────────

def test_no_agent_chosen_is_todays_letter(tmp_path):
    _, p = _project(tmp_path)
    plain = sp.template("query", p)
    assert plain.startswith("Dear [Agent's name],")
    assert sp.template("query", p, agent={}) == plain
    assert sp.template("query", p, agent=None) == plain


def test_the_letter_uses_the_agents_name_agency_and_what_they_represent(tmp_path):
    _, p = _project(tmp_path)
    info = qa.agent_info(VOSS)
    assert info["represents"] == "gothic and literary horror"
    text = sp.template("query", p, agent=info)
    assert text.startswith("Dear Ada Voss,")
    assert ("I'm querying you because you represent gothic and literary horror, and I hope "
            "THE PIER might be right for your list at Harbour Literary.") in text
    assert "[Agent's name]" not in text
    only_name = sp.template("query", p, agent=qa.agent_info(PLAIN))
    assert only_name.startswith("Dear Ben Kerr,") and "I'm querying you" not in only_name
    assert "your list at" not in only_name


def test_readdress_changes_only_the_greeting_and_the_apps_own_line():
    old, new = qa.agent_info(VOSS), qa.agent_info(PLAIN)
    letter = ("Dear Ada Voss,\n\nMy hook, rewritten by me.\n\n"
              + qa.agent_line(old, "The Pier") + "\n\nSincerely,\nAnn")
    out = qa.readdress(letter, old, new, "The Pier")
    assert out["found"]
    assert out["text"] == "Dear Ben Kerr,\n\nMy hook, rewritten by me.\n\nSincerely,\nAnn"
    assert qa.readdress("Hello there,\n\nNo greeting.", old, new, "x")["found"] is False


def test_mailto_opens_a_draft_with_the_address_subject_and_body():
    url = qa.mailto_url(qa.agent_info(VOSS), "Query: THE PIER", "Dear Ada Voss,\n\nLine & more?")
    body, subject, to = _body(url)
    assert url.startswith("mailto:ada@harbour.example?")
    assert subject == "Query: THE PIER" and body == "Dear Ada Voss,\n\nLine & more?"
    assert qa.mailto_url({}, "Query", "x").startswith("mailto:?")


# ── The store: nothing the writer wrote is lost ────────────────────────

def test_an_unedited_letter_is_filled_in_again_for_the_new_agent(tmp_path):
    _, p = _project(tmp_path)
    store.put_draft(p, None, "query", sp.template("query", p), "template")
    res = qa.address(p, None, qa.agent_info(VOSS), ask=lambda q: pytest.fail("not asked"))
    doc = store.document(p, None, "query")
    assert doc["text"].startswith("Dear Ada Voss,") and res["changed"]
    assert doc["to"]["name"] == "Ada Voss" and not store.is_edited(doc)
    assert any(v["text"].startswith("Dear [Agent's name],") for v in doc["versions"])
    # Back to no agent: today's text again.
    qa.address(p, None, {}, ask=lambda q: pytest.fail("not asked"))
    assert store.text(p, None, "query") == sp.template("query", p)


def test_an_edited_letter_is_asked_about_and_only_its_greeting_changes(tmp_path):
    _, p = _project(tmp_path)
    store.put_draft(p, None, "query", sp.template("query", p), "template")
    mine = "Dear [Agent's name],\n\nMy own hook, every word mine.\n\nSincerely,\nAnn"
    store.set_text(p, None, "query", mine)
    asked = []
    res = qa.address(p, None, qa.agent_info(VOSS), ask=lambda q: asked.append(q) or False)
    assert asked and "Dear Ada Voss," in asked[0] and res["declined"]
    assert store.text(p, None, "query") == mine                 # said no: untouched
    res = qa.address(p, None, qa.agent_info(VOSS), ask=lambda q: True)
    doc = store.document(p, None, "query")
    assert doc["text"] == mine.replace("[Agent's name]", "Ada Voss")
    assert store.is_edited(doc)                                  # still the writer's
    assert mine in [v["text"] for v in doc["versions"]] and res["kept"]
    # Already addressed so: nothing asked, nothing changed.
    assert not qa.address(p, None, qa.agent_info(VOSS), ask=lambda q: pytest.fail("asked"))["changed"]


def test_a_letter_with_no_greeting_is_left_as_it_is(tmp_path):
    _, p = _project(tmp_path)
    store.set_text(p, None, "query", "To whom it may concern: my letter.")
    res = qa.address(p, None, qa.agent_info(VOSS), ask=lambda q: pytest.fail("asked"))
    assert not res["changed"] and "left as it is" in res["note"]
    assert store.text(p, None, "query") == "To whom it may concern: my letter."


def test_a_model_query_gets_the_apps_greeting(tmp_path):
    class Fake:
        model = "fake"

        def generate_text(self, prompt, system, **kw):
            assert "Dear Ada Voss," in prompt
            return "Dear Agent,\n\n" + "The pier burns and Mara must choose. " * 8

    _, p = _project(tmp_path)
    out = sp.draft(Fake(), "query", p, agent=qa.agent_info(VOSS))
    assert out["text"].startswith("Dear Ada Voss,")


def test_an_older_file_and_the_to_key_round_trip(tmp_path):
    """A drafts file from before the addendum has no "to": no agent. The
    new key is kept by every later write."""
    _, p = _project(tmp_path)
    store.put_draft(p, None, "query", "Dear [Agent's name],\n\nx", "template")
    assert "to" not in store.document(p, None, "query")
    store.set_to(p, None, qa.agent_info(PLAIN))
    store.set_text(p, None, "query", "Dear [Agent's name],\n\ny")
    store.put_draft(p, None, "blurb", "b", "template")
    assert store.document(p, None, "query")["to"]["name"] == "Ben Kerr"


# ── The tab ────────────────────────────────────────────────────────────

def test_the_to_list_addresses_the_letter_in_the_package(tmp_path, app, monkeypatch):
    w, p, _ = _tab(tmp_path, app, monkeypatch)
    w.agent_list.setCurrentRow(0)
    _settle(app)
    view = w.package_view
    assert not view.to_pick.isVisibleTo(view)                    # only for the query letter
    view.show_document("query")
    _settle(app)
    assert view.to_pick.isVisibleTo(view)
    assert view.to_pick.currentText() == view.NO_AGENT
    assert view.editor.toPlainText().startswith("Dear [Agent's name],")
    labels = [view.to_pick.itemText(i) for i in range(view.to_pick.count())]
    assert labels == [view.NO_AGENT, "To: Ada Voss · Harbour Literary", "To: Ben Kerr"]
    view.to_pick.setCurrentIndex(1)
    assert view.editor.toPlainText().startswith("Dear Ada Voss,")
    assert "Harbour Literary" in view.editor.toPlainText()
    # The writer edits; choosing another agent asks first, and No keeps it all.
    view.editor.setPlainText(view.editor.toPlainText().replace("Thank you", "Many thanks"))
    monkeypatch.setattr(view, "_ask", lambda q: False)
    view.to_pick.setCurrentIndex(2)
    assert view.editor.toPlainText().startswith("Dear Ada Voss,")
    assert "Many thanks" in store.text(p, None, "query")
    assert view.to_pick.currentText().startswith("To: Ada Voss")  # the list shows the truth
    monkeypatch.setattr(view, "_ask", lambda q: True)
    view.to_pick.setCurrentIndex(2)
    text = view.editor.toPlainText()
    assert text.startswith("Dear Ben Kerr,") and "Many thanks" in text
    assert "earlier text is kept" in view.status.text()
    # A redraft from the story keeps the agent.
    view.draft(use_model=False)
    _settle(app)
    assert view.editor.toPlainText().startswith("Dear Ben Kerr,")
    w.close()


def test_compose_email_opens_a_draft_with_the_letter_and_sends_nothing(tmp_path, app, monkeypatch):
    w, p, opened = _tab(tmp_path, app, monkeypatch)
    w.agent_list.setCurrentRow(1)
    page = w.current_agent_widget
    assert page.agent.name == "Ada Voss"
    page._compose_email()
    assert len(opened) == 1                                       # one draft, opened, not sent
    body, subject, to = _body(opened[0])
    assert to == "ada@harbour.example" and subject == "Query: The Pier"
    assert body.startswith("Dear Ada Voss,") and "Mara Venn" in body
    assert store.text(p, None, "query") == body                   # the package has it too
    # The package, opened afterwards, shows the same letter and agent.
    w.agent_list.setCurrentRow(0)
    w.package_view.show_document("query")
    assert w.package_view.editor.toPlainText() == body
    assert w.package_view.to_pick.currentText().startswith("To: Ada Voss")
    w.close()


def test_compose_email_keeps_an_edited_letter_when_the_writer_says_no(tmp_path, app, monkeypatch):
    from src.ui import query_email
    w, p, opened = _tab(tmp_path, app, monkeypatch)
    mine = "Dear [Agent's name],\n\nEvery word of this is mine.\n\nAnn"
    store.put_draft(p, None, "query", "made", "template")
    store.set_text(p, None, "query", mine)
    w.agent_list.setCurrentRow(2)
    page = w.current_agent_widget
    monkeypatch.setattr(query_email, "_ask", lambda parent, q: False)
    page._compose_email()
    assert _body(opened[-1])[0] == mine and store.text(p, None, "query") == mine
    assert _body(opened[-1])[2] == ""                             # no address stored: To left empty
    monkeypatch.setattr(query_email, "_ask", lambda parent, q: True)
    page._compose_email()
    assert _body(opened[-1])[0] == mine.replace("[Agent's name]", "Ben Kerr")
    assert mine in [v["text"] for v in store.document(p, None, "query")["versions"]]
    w.close()


def test_when_the_mail_program_cannot_open_the_letter_is_copied(tmp_path, app, monkeypatch):
    from PyQt6.QtWidgets import QApplication
    from src.ui import query_email
    w, p, _ = _tab(tmp_path, app, monkeypatch)
    monkeypatch.setattr(query_email, "open_url", lambda url: False)
    w.agent_list.setCurrentRow(1)
    w.current_agent_widget._compose_email()
    assert QApplication.clipboard().text().startswith("Dear Ada Voss,")
    w.close()
