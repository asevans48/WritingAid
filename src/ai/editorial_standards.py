"""How an editor puts a finding: the same rules for every Critique report.

Editing standards agree on how feedback reaches an author (Editors Canada,
*Professional Editorial Standards* 2024; see ``docs/publishing/
background.md``): queries are clear, succinct and actionable; the editor
queries where intent is unclear, keeps queries few, never alters the
intended meaning and keeps the author's voice. Fiction may break the usual
rules on purpose.

``with_standards`` adds those rules to a report's system prompt, in one
place, so every report (and the passage critique) follows them:

* **Passage, effect, option.** Each point quotes the passage, says what it
  does to a reader, and gives one option.
* **Ask where the author may have meant it.** A fragment, dialect, a
  withheld fact, a rule broken for effect: a question, not an instruction.
* **Meaning and voice are the author's.**
* **Few, well-chosen points.** About the text, never about the writer.

It never changes a report's answer format, and adding it twice does
nothing.
"""

from __future__ import annotations

MARK = "HOW TO PUT A FINDING"

STANDARDS = (
    f"{MARK} (professional editing standards; they apply inside whatever answer format "
    "you are given, and never change that format):\n"
    "- Passage, effect, option: quote the passage, say what it does to a reader, and "
    "give one option for the author.\n"
    "- Where the author may have meant it (a fragment, dialect, a withheld fact, a rule "
    "broken for effect, their own voice), ask instead of instructing: \"If this is "
    "intended, keep it; if not, consider …\".\n"
    "- Never propose a change that alters what the author means, and keep their voice.\n"
    "- A few well-chosen points beat many: no padding, no point made twice.\n"
    "- Describe what the text does. Never judge the writer.")

STANDARDS_COMPACT = (
    f"{MARK}: quote the passage, say its effect on a reader, give one option. If the "
    "author may have meant it, ask instead of instructing. Keep the author's meaning and "
    "voice. Keep the answer format you are given.")


def with_standards(system_prompt: str, compact: bool = False) -> str:
    """``system_prompt`` with the standards added once (shorter for
    on-device models)."""
    system_prompt = system_prompt or ""
    if MARK in system_prompt:
        return system_prompt
    block = STANDARDS_COMPACT if compact else STANDARDS
    return (system_prompt.rstrip() + "\n\n" + block).strip()
