"""Matching a replacement word to the form of the word it replaces.

"looked" → offer "glanced", not "glance"; "looking" → "glancing";
"looks" → "glances". Rule-based with a table of common irregular verbs —
enough for synonym lists, no dependencies.
"""

from __future__ import annotations

from typing import Dict

IRREGULAR_PAST: Dict[str, str] = dict(pair.split(":") for pair in """
go:went come:came see:saw run:ran take:took get:got make:made give:gave find:found
think:thought know:knew tell:told feel:felt leave:left stand:stood sit:sat hold:held
bring:brought begin:began speak:spoke say:said meet:met grow:grew draw:drew throw:threw
fly:flew rise:rose drive:drove ride:rode write:wrote break:broke choose:chose catch:caught
seek:sought fight:fought buy:bought teach:taught lose:lost send:sent spend:spent build:built
hear:heard keep:kept sleep:slept sweep:swept creep:crept weep:wept lead:led eat:ate fall:fell
wake:woke shake:shook strike:struck stride:strode steal:stole swing:swung cling:clung
hang:hung dig:dug spin:spun win:won shine:shone slide:slid hide:hid bite:bit light:lit
pay:paid wear:wore tear:tore bear:bore swear:swore freeze:froze forget:forgot
understand:understood set:set put:put cut:cut hit:hit shut:shut let:let spread:spread
burst:burst cast:cast sink:sank sing:sang ring:rang drink:drank swim:swam shrink:shrank
stink:stank spring:sprang bend:bent lend:lent dwell:dwelt kneel:knelt leap:leapt
mean:meant deal:dealt flee:fled feed:fed bleed:bled breed:bred grind:ground wind:wound
bind:bound slay:slew tread:trod forbid:forbade forgive:forgave arise:arose awake:awoke
behold:beheld sell:sold do:did have:had be:was
""".split())
_PAST_TO_BASE = {past: base for base, past in IRREGULAR_PAST.items() if past != base}
_VOWELS = set("aeiou")


def _cvc(word: str) -> bool:
    """Short consonant-vowel-consonant ending: stop → stopped, run → running."""
    return (len(word) >= 3 and word[-1] not in _VOWELS | set("wxy") and word[-2] in _VOWELS
            and word[-3] not in _VOWELS and len(word) <= 5)


def form_of(word: str) -> str:
    """"past", "ing", "s" or "base"."""
    w = (word or "").lower()
    if w in _PAST_TO_BASE or (w.endswith("ed") and len(w) > 4):
        return "past"
    if w.endswith("ing") and len(w) > 5:
        return "ing"
    if w.endswith("s") and not w.endswith(("ss", "us", "is")) and len(w) > 3:
        return "s"
    return "base"


def base_of(word: str) -> str:
    w = (word or "").lower()
    if w in _PAST_TO_BASE:
        return _PAST_TO_BASE[w]
    form = form_of(w)
    if form == "past":
        stem = w[:-2]
        if w.endswith("ied"):
            return w[:-3] + "y"
        if len(stem) >= 2 and stem[-1] == stem[-2] and stem[-1] not in "ls":
            return stem[:-1]                      # stopped → stop
        if stem.endswith(("at", "it", "iz", "iv", "ar", "or", "ur", "ac", "uc", "ag", "ov",
                          "as", "ap", "il", "ur")) or (stem.endswith(("c", "v", "z"))):
            return stem + "e"                     # glared → glare, gazed → gaze
        return stem
    if form == "ing":
        stem = w[:-3]
        if len(stem) >= 2 and stem[-1] == stem[-2] and stem[-1] not in "ls":
            return stem[:-1]
        if stem.endswith(("at", "iz", "iv", "ar", "ac", "ov", "as", "ap", "c", "v", "z")):
            return stem + "e"
        return stem
    if form == "s":
        if w.endswith("ies"):
            return w[:-3] + "y"
        if w.endswith(("ches", "shes", "sses", "xes", "zes")):
            return w[:-2]
        return w[:-1]
    return w


def inflect(base: str, form: str) -> str:
    b = (base or "").lower()
    if form == "past":
        if b in IRREGULAR_PAST:
            return IRREGULAR_PAST[b]
        if b.endswith("e"):
            return b + "d"
        if b.endswith("y") and len(b) > 1 and b[-2] not in _VOWELS:
            return b[:-1] + "ied"
        return b + b[-1] + "ed" if _cvc(b) else b + "ed"
    if form == "ing":
        if b.endswith("ie"):
            return b[:-2] + "ying"
        if b.endswith("e") and not b.endswith(("ee", "ye", "oe")):
            return b[:-1] + "ing"
        return b + b[-1] + "ing" if _cvc(b) else b + "ing"
    if form == "s":
        if b.endswith(("s", "x", "z", "ch", "sh")):
            return b + "es"
        if b.endswith("y") and len(b) > 1 and b[-2] not in _VOWELS:
            return b[:-1] + "ies"
        return b + "s"
    return b


def match_form(candidate: str, target: str) -> str:
    """``candidate`` in the same form as ``target`` (first word of a
    phrase: "turn up" for "came" → "turned up")."""
    words = (candidate or "").split()
    if not words:
        return candidate
    want = form_of(target)
    head = words[0]
    # A plain-form target ("home") leaves the candidate alone: "dwelling"
    # is a noun, not the -ing form of "dwell".
    if want != "base" and form_of(head) != want:
        head = inflect(base_of(head), want)
    out = " ".join([head] + words[1:])
    if target[:1].isupper():
        out = out[:1].upper() + out[1:]
    return out
