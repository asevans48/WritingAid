"""Compose Email on an agent's page (9.3 addendum).

Opens a draft in the writer's own mail program, addressed to the agent's
stored email, with the submission package's query letter (addressed to
this agent) as the body. **Nothing is sent**: the mail program shows the
draft and the writer sends it, or doesn't. Only if the mail program can't
be opened is the letter copied instead (so the clipboard is never
replaced behind the writer's back).

No model. An edited letter has only its greeting changed, and only after
the writer says yes (``query_address.address``); otherwise it is used as
the writer left it.
"""

from __future__ import annotations

from typing import Any, Optional

from src.ai import query_address as qa
from src.ui import notify


def open_url(url: str) -> bool:
    """Hand a mailto: link to the system (tests replace this)."""
    from PyQt6.QtCore import QUrl
    from PyQt6.QtGui import QDesktopServices
    return bool(QDesktopServices.openUrl(QUrl(url, QUrl.ParsingMode.TolerantMode)))


def _copy(text: str) -> None:
    try:
        from PyQt6.QtWidgets import QApplication
        QApplication.clipboard().setText(text)
    except Exception as e:
        print(f"[query email] copy: {e}")


def _ask(parent: Any, question: str) -> bool:
    from PyQt6.QtWidgets import QMessageBox
    return QMessageBox.question(
        parent, "Query letter", question,
        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
    ) == QMessageBox.StandardButton.Yes


def compose(parent: Any, agent: Any, manager: Optional[Any] = None, ask=None) -> dict:
    """Address the query letter to ``agent`` and open it as an email draft.
    Returns {"url", "body", "opened", ...} for the caller and tests."""
    info = qa.agent_info(agent)
    project = getattr(manager, "project", None)
    view = getattr(manager, "package_view", None)
    who = info.get("name") or "the agent"
    if project is None:                       # no project: an empty draft to the agent, as before
        url = qa.mailto_url(info, "Query", "")
        opened = open_url(url)
        if not opened:
            notify.notice(parent, "Email", "Couldn't open your mail program.")
        return {"url": url, "body": "", "opened": opened}
    scope = getattr(view, "scope", None) if view is not None else None
    if view is not None:
        view.flush()                          # the writer's latest typing first
    from src.ai import submission_package as sp
    from src.data import submission_store as store
    saved = store.comps(project, scope)
    comps = sp.chosen_comps(saved["chosen"], saved["own"])
    res = qa.address(project, scope, info, ask or (lambda q: _ask(parent, q)),
                     chosen_comps=comps)
    if view is not None:
        view.refresh_query()
    title = sp.facts(project, scope)["title"]
    body = res["text"]
    url = qa.mailto_url(info, f"Query: {title}", body)
    opened = open_url(url)
    to = f" to {info['email']}" if info.get("email") else " (add the agent's address in To)"
    if opened:
        notify.done(parent, "Email",
                    f"Your mail program has a draft{to} with your query letter to {who}. "
                    "Nothing is sent until you send it.")
    else:
        _copy(body)
        notify.notice(parent, "Email",
                      "Couldn't open your mail program. Your query letter is copied: "
                      "paste it into a new email.")
    res.update(url=url, body=body, opened=opened)
    return res
