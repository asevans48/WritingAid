"""British and period spellings, accepted when the writer says so.

The spell checker's dictionary is American. Two settings (Settings →
Writing Analysis) widen what it accepts:

* **British spellings** (``spelling_british``): a word is accepted when its
  American form is a known word: colour → color, realise → realize, centre →
  center, travelled → traveled, defence → defense, anaemia → anemia … The
  American twin must exist, so a typo is not let through. Mixing the two in
  one book is still reported by the Consistency check.
* **Older, period spellings** (``spelling_period``): spellings found in
  older novels (connexion, shew, gaol, waggon, to-day's parts, 'tis, o'er …).

Both are off by default, so nothing changes until the writer turns one on.
No Qt. The settings live with the app's other settings (``ai_config``).
"""

from __future__ import annotations

import re
from typing import Callable, Dict, Iterable, List

KEY_BRITISH = "spelling_british"
KEY_PERIOD = "spelling_period"

_state = {"british": False, "period": False, "version": 0, "loaded": False}


def _read() -> Dict[str, bool]:
    try:
        from src.config.ai_config import get_ai_config
        s = get_ai_config().get_settings()
        return {"british": bool(s.get(KEY_BRITISH, False)), "period": bool(s.get(KEY_PERIOD, False))}
    except Exception:
        return {"british": False, "period": False}


def current() -> Dict[str, bool]:
    """{"british": bool, "period": bool}, read from the settings once."""
    if not _state["loaded"]:
        _state.update(_read(), loaded=True)
    return {"british": _state["british"], "period": _state["period"]}


def version() -> int:
    """Goes up whenever the settings change (spell checkers drop their caches)."""
    current()
    return _state["version"]


def reload() -> bool:
    """Read the settings again (after Settings is saved); True if they changed."""
    new = _read()
    changed = (new["british"], new["period"]) != (_state["british"], _state["period"]) \
        or not _state["loaded"]
    _state.update(new, loaded=True)
    if changed:
        _state["version"] += 1
    return changed


def set_for_session(british: bool, period: bool) -> None:
    """Set without saving (tests, and the benchmark scripts)."""
    _state.update(british=bool(british), period=bool(period), loaded=True)
    _state["version"] += 1


# ── British → American ─────────────────────────────────────────────────

# Words whose American form no rule reaches.
_PAIRS = {
    "grey": "gray", "aeroplane": "airplane", "tyre": "tire", "kerb": "curb", "cheque": "check",
    "plough": "plow", "sceptic": "skeptic", "sceptical": "skeptical", "jewellery": "jewelry",
    "pyjamas": "pajamas", "aluminium": "aluminum", "cosy": "cozy", "draught": "draft",
    "storey": "story", "moustache": "mustache", "manoeuvre": "maneuver", "programme": "program",
    "learnt": "learned", "burnt": "burned", "dreamt": "dreamed", "spelt": "spelled",
    "leapt": "leaped", "knelt": "kneeled", "smelt": "smelled", "spoilt": "spoiled",
    "whilst": "while", "amongst": "among", "towards": "toward", "mum": "mom",
    "omelette": "omelet", "doughnut": "donut", "axe": "ax", "furore": "furor",
    "speciality": "specialty", "judgement": "judgment", "ageing": "aging", "arse": "ass",
    "tonne": "ton", "practise": "practice", "licence": "license", "defence": "defense",
    "offence": "offense", "pretence": "pretense", "enquiry": "inquiry", "enquire": "inquire",
    "gaol": "jail", "carcase": "carcass", "connexion": "connection", "sulphur": "sulfur",
    "catalogue": "catalog", "analogue": "analog", "dialogue": "dialog", "fulfil": "fulfill",
    "skilful": "skillful", "wilful": "willful", "enrol": "enroll", "instalment": "installment",
    "woollen": "woolen", "marvellous": "marvelous", "jeweller": "jeweler",
}

_RULES = [
    # colour, favourite, neighbourhood, honourable …
    (re.compile(r"our(?=(?:s|ed|ing|ite|ites|able|ably|hood|hoods|ly|ful|fully|less|er|ers|"
                r"ist|ists|ism|y)?$)"), "or"),
    # realise, organisation, recognising …
    (re.compile(r"is(?=(?:e|es|ed|ing|er|ers|ation|ations|able)$)"), "iz"),
    (re.compile(r"ys(?=(?:e|es|ed|ing|er|ers)$)"), "yz"),
    # centre, theatre, sombre, calibre (+s, +d)
    (re.compile(r"(?<=[tbcgh])re(?=s?$)"), "er"),
    (re.compile(r"(?<=[tbcgh])red$"), "ered"),
    (re.compile(r"(?<=[tbcgh])ring$"), "ering"),
    # travelled, cancelling, traveller, modelled
    (re.compile(r"ll(?=(?:ed|ing|er|ers|ous)$)"), "l"),
    # defence, offence
    (re.compile(r"ence$"), "ense"),
    # anaemia, paediatric, foetus, oestrogen
    (re.compile(r"ae"), "e"),
    (re.compile(r"oe"), "e"),
    # mould, moult, smoulder
    (re.compile(r"oul(?=[dt])"), "ol"),
    # analogue, catalogue
    (re.compile(r"ogue(?=s?$)"), "og"),
    # skilful, instalment, enrol: British single l
    (re.compile(r"l(?=(?:ful|fully|ment|ments)$)"), "ll"),
]


def american_forms(word_lower: str) -> List[str]:
    """American spellings ``word_lower`` could be the British form of."""
    out: List[str] = []
    base = word_lower
    if base in _PAIRS:
        out.append(_PAIRS[base])
    for plural in ("s", "es", "d", "ed"):
        if base.endswith(plural) and base[:-len(plural)] in _PAIRS:
            out.append(_PAIRS[base[:-len(plural)]] + plural)
    for rx, repl in _RULES:
        new = rx.sub(repl, base)
        if new != base and new not in out:
            out.append(new)
    return out


# ── Period spellings ───────────────────────────────────────────────────

PERIOD_WORDS = frozenset("""
connexion connexions shew shewed shewn shewing shews gaol gaoler gaols waggon waggons
despatch despatched despatches despatching gipsy gipsies clew clews phantasy develope
chuse chuses chusing staid ancle ancles alarum alarums hallo halloa holloa hullo
tis twas twere twill twould oer eer neer een whate'er where'er
thou thee thy thine thyself hast hath doth dost didst wilt shalt art wert canst wouldst
shouldst couldst mayst ye yon yonder hither thither whither whence thence hence
betwixt amongst whilst ere anon aught naught nought forsooth prithee methinks methought
perchance mayhap verily wherefore whereat whereupon heretofore
tho thro altho bye goodbye good-bye
cocoanut cocoanuts negro mediaeval encyclopaedia aesthetic diarrhoea
surprize surprized expence expences shewd controul compleat compleatly
dreamt learnt burnt spelt wont
""".split())


def accepts(word_lower: str, is_known: Callable[[str], bool]) -> bool:
    """True when an unknown word is fine under the writer's settings.
    ``is_known`` tests a word against the base dictionary."""
    s = current()
    if s["period"] and word_lower.replace("'", "") in PERIOD_WORDS or \
            (s["period"] and word_lower in PERIOD_WORDS):
        return True
    if s["british"]:
        return any(is_known(form) for form in american_forms(word_lower))
    return False


def describe() -> str:
    s = current()
    on = [name for key, name in (("british", "British"), ("period", "period")) if s[key]]
    return " and ".join(on) + " spellings accepted" if on else "American spellings only"
