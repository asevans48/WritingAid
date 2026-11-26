"""The AI chat's prose-profile requests (pure Python; the UI runs them).

Two requests, recognised in the writer's message so they work with any
model (``detect``), or emitted by the model as a ``<prose_profile>`` tag
(``chat_actions.ACTIONS_PROMPT_BLOCK``):

* **summary**: "prose profile", "summarise my prose", "how does this
  chapter compare to the genre?". The current chapter's measures beside
  the Prose Profile's targets (``prose_snapshot``), at once, no model.
* **review**: "review my prose", "analyse the tone and voice". The same
  summary at once, then the Critique's "Prose profile fit" report on the
  chapter (Analyze ▸ Prose; tone, style and voice need a model).

Deliberately conservative: a request to *change* the profile ("set the
tone to …") is not one of these.
"""

from __future__ import annotations

import re
from typing import Dict, Optional

_CHANGE = re.compile(r"^\s*(?:please\s+)?(?:set|change|update|make|edit|replace|add)\b", re.I)
_THING = r"(?:prose|writing|style|voice|tone)"
_WHOSE = r"(?:my|the|this|our|this\s+chapter'?s|the\s+chapter'?s|current\s+chapter'?s)"

_REVIEW_RX = [
    re.compile(rf"\b(?:review|critique|analy[sz]e|assess|evaluate|check|read)\s+{_WHOSE}\s+"
               rf"(?:\w+\s+)?{_THING}\b", re.I),
    re.compile(r"\bprose\s+(?:profile\s+)?(?:review|analysis|critique|fit)\b", re.I),
    re.compile(r"\b(?:full|deep|detailed)\s+prose\s+profile\b", re.I),
    re.compile(r"\b(?:does|is)\s+(?:this|the|my)\s+(?:chapter|prose|writing)\s+"
               r"(?:fit|match|hit)\s+(?:the|my)\s+(?:prose\s+)?(?:profile|tone|voice|style)\b", re.I),
]
_SUMMARY_RX = [
    re.compile(r"\bprose\s+(?:profile|summary|snapshot|stats|statistics|numbers|measures)\b", re.I),
    re.compile(rf"\b(?:summar(?:y|i[sz]e)|profile|measure)\s+(?:of\s+)?{_WHOSE}\s+"
               r"(?:chapter'?s?\s+)?(?:prose|writing|chapter)\b", re.I),
    re.compile(r"\bhow\s+(?:does|do|is|are)\s+(?:this|the|my)\s+(?:current\s+)?"
               r"(?:chapter|prose|writing|sentences?)\s+(?:compare|measure|stack|look|doing)\b"
               r".{0,40}\b(?:genre|profile|target|published)", re.I),
    re.compile(r"\b(?:on|off)\s+target\b.{0,30}\b(?:genre|profile)\b", re.I),
]


def detect(message: str) -> Optional[Dict[str, str]]:
    """``{"kind": "prose_profile", "depth": "summary"|"review"}`` or None."""
    text = (message or "").strip()
    if not text or len(text) > 300 or _CHANGE.match(text):
        return None
    if any(rx.search(text) for rx in _REVIEW_RX):
        return {"kind": "prose_profile", "depth": "review"}
    if any(rx.search(text) for rx in _SUMMARY_RX):
        return {"kind": "prose_profile", "depth": "summary"}
    return None
