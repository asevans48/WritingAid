"""The query letter addressed to an agent from the agent list (9.3 addendum).

The submission package's query letter starts "Dear [Agent's name],". Once
the writer picks an agent (the package's "To" list, or Compose Email on
an agent's page), the letter is addressed to them:

* the greeting uses the agent's name;
* one line uses what the agent list already holds: the agency, and what
  they represent when the agent's Notes have a line such as
  "Represents: gothic and literary horror" (also "Looking for:",
  "Wishlist:", "MSWL:");
* with no agent chosen, the letter is today's text, unchanged.

**The writer's text is kept** (rule 15). A letter the app filled in and
the writer hasn't touched is filled in again for the new agent. A letter
the writer has edited, or one the model drafted, has only its greeting
(and the app's own agent line, if still there word for word) changed, and
for an edited one only after the writer says yes. Either way the text it
replaces goes into the document's earlier versions first.

No model, no Qt, nothing sent: Compose Email only opens a draft in the
writer's mail program (``mailto_url``).
"""

from __future__ import annotations

import re
from typing import Any, Callable, Dict, Optional
from urllib.parse import quote

PLACEHOLDER = "Dear [Agent's name],"
_GREETING = re.compile(r"^[ \t]*Dear\b[^\n]*,[ \t]*$", re.MULTILINE)
_WANTS = re.compile(r"^\s*(?:represents?|reps|looking for|wants|wish ?list|mswl)\s*[:\-–—]\s*(.+?)\s*$",
                    re.IGNORECASE | re.MULTILINE)


def _s(x: Any) -> str:
    return x.strip() if isinstance(x, str) else ""


def represents(notes: str) -> str:
    """What the agent represents, from a "Represents: …" line in their
    Notes (the first such line), else ""."""
    m = _WANTS.search(notes or "")
    return m.group(1).rstrip(".;, ") if m else ""


def agent_info(agent: Any) -> Dict[str, str]:
    """The parts of an agent the letter uses (an AgentContact or a dict)."""
    if agent is None:
        return {}
    get = agent.get if isinstance(agent, dict) else (lambda k, d="": getattr(agent, k, d))
    info = {"id": _s(get("id", "")), "name": _s(get("name", "")),
            "agency": _s(get("agency", "")), "email": _s(get("email", "")),
            "represents": _s(get("represents", "")) or represents(_s(get("notes", "")))}
    return info if any(info.values()) else {}


def greeting(info: Optional[Dict[str, str]]) -> str:
    name = _s((info or {}).get("name"))
    return f"Dear {name}," if name else PLACEHOLDER


def agent_line(info: Optional[Dict[str, str]], title: str) -> str:
    """The letter's one line about this agent, from what the list holds;
    "" when it holds nothing to say."""
    info = info or {}
    wants, agency = _s(info.get("represents")), _s(info.get("agency"))
    book = _s(title).upper() or "this book"
    if wants and agency:
        return (f"I'm querying you because you represent {wants}, and I hope {book} "
                f"might be right for your list at {agency}.")
    if wants:
        return f"I'm querying you because you represent {wants}, and I hope {book} might suit you."
    if agency:
        return f"I hope {book} might be right for your list at {agency}."
    return ""


def readdress(text: str, old: Optional[Dict[str, str]], new: Optional[Dict[str, str]],
              title: str) -> Dict[str, Any]:
    """Change only the greeting (the first "Dear …," line), and the app's
    own agent line for ``old`` if it is still there word for word. The
    rest is the writer's. Returns {"text", "found"} ("found": a greeting
    was there to change)."""
    m = _GREETING.search(text or "")
    if not m:
        return {"text": text, "found": False}
    out = text[:m.start()] + greeting(new) + text[m.end():]
    before, after = agent_line(old, title), agent_line(new, title)
    if before and before != after and before in out:
        out = out.replace(before + "\n\n", after + "\n\n" if after else "", 1) \
            if before + "\n\n" in out else out.replace(before, after, 1)
    return {"text": out, "found": True}


def same_agent(a: Optional[Dict[str, str]], b: Optional[Dict[str, str]]) -> bool:
    a, b = a or {}, b or {}
    return all(_s(a.get(k)) == _s(b.get(k)) for k in ("name", "agency", "represents"))


def address(project: Any, scope: Optional[str], info: Optional[Dict[str, str]],
            ask: Callable[[str], bool], chosen_comps=()) -> Dict[str, Any]:
    """Address the stored query letter to ``info`` (None: no agent, today's
    text). ``ask(question)`` is asked before an edited letter's greeting
    is changed. Returns {"text", "changed", "kept", "declined", "note"}."""
    from src.ai import submission_package as sp
    from src.data import submission_store as store
    info = info or {}
    entry = store.document(project, scope, "query")
    cur = entry.get("text") or ""
    old = entry.get("to") if isinstance(entry.get("to"), dict) else {}
    res = {"text": cur, "changed": False, "kept": False, "declined": False, "note": ""}
    title = sp.facts(project, scope)["title"]
    edited = store.is_edited(entry)
    if not cur.strip() or (entry.get("source") == "template" and not edited):
        new = sp.template("query", project, scope, chosen_comps=chosen_comps, agent=info)
        if new != cur or not same_agent(old, info):
            got = store.put_draft(project, scope, "query", new, "template", to=info)
            res.update(text=new, changed=new != cur, kept=got["kept"])
        return res
    if same_agent(old, info) and greeting(info) in cur:
        return res                                     # already addressed so
    moved = readdress(cur, old, info, title)
    if not moved["found"]:
        res["note"] = ("Your query letter has no “Dear …,” line, so it was left as it is.")
        return res
    if moved["text"] == cur:
        store.set_to(project, scope, info)
        return res
    if edited:
        first = moved["text"][_GREETING.search(moved["text"]).start():].split("\n", 1)[0]
        if not ask(f"You've edited your query letter. Change only its greeting to “{first}”? "
                   "The rest stays as you wrote it, and the current text is kept in "
                   "More ▾ › Earlier versions."):
            res["declined"] = True
            return res
    got = store.readdress(project, scope, moved["text"], info)
    res.update(text=moved["text"], changed=True, kept=got["kept"],
               note="Greeting updated; the rest of your letter is as you wrote it."
               if edited else "")
    return res


def mailto_url(info: Optional[Dict[str, str]], subject: str, body: str) -> str:
    """A mailto: link that opens a draft (never sends). The agent's address
    when stored; otherwise the writer fills in To."""
    to = quote(_s((info or {}).get("email")), safe="@.+-_")
    body = (body or "").replace("\r\n", "\n").replace("\n", "\r\n")
    return f"mailto:{to}?subject={quote(subject, safe='')}&body={quote(body, safe='')}"
