"""Quality checks and learned examples for AI rewrites.

Shared by Suggestions and Rephrase:

* ``check_rewrite`` — deterministic checks a model (local ones especially)
  often fails: misspelled or invented names, a switch of point of view or
  tense, a wildly different length, text copied from around the passage,
  new clichés / adverbs / passive voice, and drift from the author's
  measured voice. "Serious" problems mean the rewrite should be replaced.
* ``examples_prompt`` — the writer's own best-rated past rewrites (and
  ones they rejected), as examples for the next prompt.
* ``diff_html`` — word-level changes between the original and a rewrite.
"""

from __future__ import annotations

import difflib
import html
import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

_WORD_RX = re.compile(r"[A-Za-z][A-Za-z'’\-]*")
_NAME_RX = re.compile(r"(?<![A-Za-z'’])([A-Z][a-z]+(?:[-'’][A-Za-z]+)*)")
_QUOTE_RX = re.compile(r'"[^"\n]*"|“[^”\n]*”')
_FIRST = {"i", "me", "my", "mine", "myself"}
_FIRST_PLURAL = {"we", "us", "our", "ours", "ourselves"}
_THIRD = {"he", "she", "him", "her", "his", "hers", "himself", "herself",
          "they", "them", "their", "themselves"}
_PAST = {"was", "were", "had", "did", "said", "went", "came", "saw", "knew", "thought",
         "felt", "looked", "turned", "ran", "took", "made", "stood", "sat"}
_PRESENT = {"is", "are", "has", "does", "says", "goes", "comes", "sees", "knows", "thinks",
            "feels", "looks", "turns", "am", "runs", "takes", "makes", "stands", "sits"}
_LENGTH_WORDS = ("short", "long", "length", "expand", "cut", "trim", "condense", "brief",
                 "concise", "elaborate", "more detail", "fewer words")
_STYLE_KINDS = {"cliche": "a cliché", "adverb": "-ly adverbs", "passive": "passive voice",
                "intensifier": "weak intensifiers", "wordy": "wordy phrasing"}
_COMMON_CAPS = {"I", "God", "Mr", "Mrs", "Ms", "Dr", "Sir", "Lady", "Lord", "Captain",
                "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday",
                "January", "February", "March", "April", "May", "June", "July", "August",
                "September", "October", "November", "December", "English", "OK"}
_dictionary = None

# Phrases local models (Gemma especially) reach for again and again.
# (label shown to the writer, pattern)
STOCK_PHRASES = [
    ("bruised (sky / light)", r"\bbruis(?:ed|e)[- ](?:sky|skies|light|purple|clouds?|horizon|dark)|"
                               r"\b(?:sky|skies|horizon|clouds?)\b[^.]{0,20}\bbruise"),
    ("heart hammering", r"\bheart\s+(?:was\s+)?(?:hammer|pound|thunder|slamm)\w*"),
    ("breath she didn't know she was holding", r"breath (?:he|she|they|I) (?:didn't|did not) know"),
    ("let out a breath", r"\blet out a (?:shaky |long |slow )?breath"),
    ("breath hitched", r"\bbreath (?:hitch|caught)\w*"),
    ("the weight of …", r"\bthe (?:full |crushing |heavy )?weight of (?:it|the|her|his|their|what|every)"),
    ("swallowed by / swallowed them",
     r"\b(?:fog|mist|dark(?:ness)?|night|sea|water|shadows?|silence)\s+swallow\w*"
     r"|\bswallow(?:ed|ing|s)? (?:them|him|her|the light|the sound|whole)|\bswallowed by\b"),
    ("fog / mist clung", r"\b(?:fog|mist|silence|darkness|smoke)\s+(?:clung|clinging)"),
    ("a testament to", r"\ba testament to\b"),
    ("tapestry of", r"\btapestry of\b"),
    ("symphony of", r"\bsymphony of\b"),
    ("dance of", r"\b(?:a|the) dance of\b"),
    ("palpable", r"\bpalpable\b"),
    ("the air thick with", r"\b(?:air|room|silence)\s+(?:was\s+)?(?:thick|heavy|electric)\s+with\b"),
    ("time stood still", r"\btime (?:seemed to )?(?:stood|stand|stop(?:ped)?) still\b"),
    ("something shifted", r"\bsomething (?:shifted|changed) (?:in|between)\b"),
    ("knuckles white", r"\bknuckles\s+(?:turn(?:ed|ing)?\s+)?white|\bwhite-knuckled\b"),
    ("jaw clenched / tightened", r"\bjaw (?:clench|tighten|set)\w*"),
    ("ghost of a smile", r"\bghost of a (?:smile|grin|laugh)"),
    ("a flicker of …", r"\ba flicker of\b"),
    ("barely above a whisper", r"\bbarely (?:above|more than) a whisper"),
    ("sent a shiver / chill", r"\b(?:sent|a) (?:shivers?|chills?) (?:down|up|ran|crept|through)"),
    ("couldn't help but", r"\bcould(?:n't| not) help but\b"),
    ("it was as if", r"\bit was as (?:if|though)\b"),
    ("eyes that held", r"\beyes (?:that )?held\b"),
    ("copper / metallic tang", r"\b(?:coppery|metallic|copper) (?:tang|taste)\b"),
    ("ozone", r"\bozone\b"),
    ("unspoken …", r"\bunspoken (?:words?|question|tension|promise)"),
    ("electric silence / tension", r"\belectric (?:silence|tension|air)"),
    ("a beat passed", r"\ba beat (?:passed|of silence)|\bfor a heartbeat\b"),
    ("in that moment", r"\bin that moment\b"),
]
_STOCK_RX = [(label, re.compile(rx, re.I)) for label, rx in STOCK_PHRASES]

# Concrete things a rewrite must not invent (a gun, a wound, a horse…).
FACT_WORDS = {
    # Words that are usually figurative ("dead calm", "blade of grass", a
    # ship's bow) are left out.
    "weapon": """gun guns rifle rifles pistol pistols revolver musket shotgun crossbow arrow
        arrows sword swords knife knives dagger axe spear bomb grenade cannon harpoon
        bullet bullets""",
    "injury": """bleeding bled corpse corpses killed fracture""",
    "vehicle or animal": """car truck horse horses carriage wagon train helicopter plane dog dogs
        cat motorbike bicycle""",
}
_FACT_INDEX = {w: kind for kind, words in FACT_WORDS.items() for w in words.split()}


def avoid_phrases() -> List[str]:
    """Phrases the writer asked never to see (Suggestions › Avoid a phrase)."""
    try:
        from src.config.creativeos_config import get_creativeos_config
        return [p for p in get_creativeos_config().get("avoid_phrases", []) or []
                if isinstance(p, str) and p.strip()]
    except Exception:
        return []


def add_avoid_phrase(phrase: str) -> bool:
    phrase = " ".join((phrase or "").split())
    if len(phrase) < 3:
        return False
    from src.config.creativeos_config import get_creativeos_config
    cfg = get_creativeos_config()
    current = list(cfg.get("avoid_phrases", []) or [])
    if phrase.lower() in (p.lower() for p in current):
        return False
    cfg.set("avoid_phrases", current + [phrase])
    return True


def stock_phrases_in(text: str, extra: Iterable[str] = ()) -> List[str]:
    """Labels of the stock phrases (and the writer's avoided ones) in ``text``."""
    found = [label for label, rx in _STOCK_RX if rx.search(text or "")]
    for phrase in extra:
        if re.search(r"\b" + re.escape(phrase) + r"\b", text or "", re.I):
            found.append(phrase)
    return found


def avoid_prompt(extra: Iterable[str] = ()) -> str:
    """Prompt line listing stock phrasing to stay away from."""
    labels = [label for label, _ in STOCK_PHRASES] + list(extra)
    return ("Avoid stock phrasing, including: " + "; ".join(labels)
            + ". Find a fresh, specific image instead.")


def new_facts(candidate: str, context: str) -> List[str]:
    """Concrete things in ``candidate`` that appear nowhere in ``context``."""
    have = set(_words(context))
    out = []
    for w in dict.fromkeys(_words(candidate)):
        if w in _FACT_INDEX and w not in have and w.rstrip("s") not in have \
                and w + "s" not in have:
            out.append(w)
    return out


TWIN_PREFIX = "is nearly the same as suggestion"
SAME_OPENING_PREFIX = "opens the same way as suggestion"


def twin_problems(texts: Sequence[str]) -> Dict[int, str]:
    """Index → problem, for a rewrite whose narration is mostly the same
    wording as an earlier one's. Dialogue is ignored: keeping the author's
    lines is right, so it would make every rewrite look alike."""
    out: Dict[int, str] = {}
    words = [_words(_narration(t)) for t in texts]
    for j in range(len(texts)):
        for i in range(j):
            if min(len(words[i]), len(words[j])) < 8:
                continue
            if difflib.SequenceMatcher(None, words[i], words[j], autojunk=False).ratio() >= 0.7:
                out[j] = f"{TWIN_PREFIX} {i + 1}"
                break
    return out


def same_openings(texts: Sequence[str]) -> Dict[int, str]:
    """Index → note, for rewrites opening with the same three words as an
    earlier one (often right when the fix is to lead with the cause)."""
    out: Dict[int, str] = {}
    words = [_words(t)[:3] for t in texts]
    for j in range(len(texts)):
        for i in range(j):
            if words[i] and words[i] == words[j]:
                out[j] = f"{SAME_OPENING_PREFIX} {i + 1}"
                break
    return out


def _known_word(word: str) -> bool:
    """Is ``word`` ordinary English (so a capital is just emphasis)?"""
    global _dictionary
    if _dictionary is None:
        try:
            from spellchecker import SpellChecker
            _dictionary = SpellChecker()
        except Exception:
            _dictionary = False
    return bool(_dictionary) and bool(_dictionary.known([word.lower()]))


def _narration(text: str) -> str:
    return _QUOTE_RX.sub(" ", text or "")


def _words(text: str) -> List[str]:
    return [w.lower().replace("’", "'") for w in _WORD_RX.findall(text or "")]


def person_and_tense(text: str) -> Tuple[str, str]:
    """('first'|'third'|'', 'past'|'present'|'') of the narration, or ''
    when there's too little signal to say."""
    counts = Counter(_words(_narration(text)))
    first = sum(counts[w] for w in _FIRST)
    third = sum(counts[w] for w in _THIRD)
    person = ("first" if first >= 2 and first > third * 0.5 else
              "third" if third >= 2 and first == 0 else "")
    past = sum(counts[w] for w in _PAST) + sum(n for w, n in counts.items()
                                                if w.endswith("ed") and len(w) > 4)
    present = sum(counts[w] for w in _PRESENT)
    tense = ("past" if past >= 2 and past > present * 2 else
             "present" if present >= 2 and present > past * 2 else "")
    return person, tense


@dataclass
class RewriteCheck:
    serious: List[str] = field(default_factory=list)   # replace the rewrite
    minor: List[str] = field(default_factory=list)     # show as a note
    voice_fit: Optional[float] = None

    @property
    def ok(self) -> bool:
        return not self.serious

    @property
    def notes(self) -> List[str]:
        return self.serious + self.minor

    def rank(self) -> Tuple[int, int, float]:
        return (len(self.serious), len(self.minor), -(self.voice_fit or 0.0))


def _name_problems(candidate: str, context: str, known_names: Iterable[str]) -> List[str]:
    def bare(word: str) -> str:            # "Mara's" → "Mara"
        return re.sub(r"[’']s?$", "", word)

    known_tokens = {bare(t) for n in known_names for t in re.findall(r"[A-Za-z][A-Za-z'’\-]+", n)}
    in_context = {bare(w) for w in _NAME_RX.findall(context)}
    out, seen = [], set()
    for m in _NAME_RX.finditer(candidate):
        word = bare(m.group(1))
        if word in seen or word in known_tokens or word in in_context or word in _COMMON_CAPS:
            continue
        seen.add(word)
        before = candidate[:m.start()].rstrip()
        sentence_start = not before or before[-1] in ".!?…\"“”'’:—\n"
        ordinary = _known_word(word)
        close = difflib.get_close_matches(word, known_tokens, n=1, cutoff=0.8)
        if close and not (ordinary and sentence_start):
            out.append(f"spells “{word}” — your notes have “{close[0]}”")
            continue
        if not sentence_start and not ordinary:
            out.append(f"introduces “{word}”, which isn't in the passage or your notes")
    return out


_STOP = set("""the a an and or but of to in on at by for with from as is was were be been are it
its this that these those not no so than then into about over his her him she he they them their
there here had has have did does do would could should will just only very what when where which
who whom while all any each some out off down upward back again still even once across
through toward towards onto upon""".split())


def split_sentences(text: str) -> List[str]:
    """Sentences of ``text`` (paragraph by paragraph)."""
    from src.ai.passage_critique import _sentence_spans
    out = []
    for para in (text or "").split("\n"):
        out += [para[s:e] for s, e in _sentence_spans(para)]
    return out


def _stem(word: str) -> str:
    for suffix in ("ingly", "edly", "ing", "ed", "ly", "es", "s"):
        if word.endswith(suffix) and len(word) - len(suffix) >= 3:
            return word[:-len(suffix)]
    return word


def content_words(text: str, ignore: frozenset = frozenset()) -> set:
    words = (re.sub(r"'s$", "", w).strip("'-") for w in _words(text))
    return {_stem(w) for w in words if len(w) >= 3 and w not in _STOP and w not in ignore}


def _capitalized(*texts: str) -> frozenset:
    """Names (and other capitalised words) — shared by any two sentences
    about the same people, so they don't count as retelling."""
    return frozenset(w.lower() for t in texts for w in _NAME_RX.findall(t or "")) - {"i"}


def similarity(a: str, b: str, ignore: frozenset = frozenset()) -> float:
    """Content-word overlap of two sentences, 0–1 (catches paraphrase,
    not just copying). Names in ``ignore`` don't count."""
    wa, wb = content_words(a, ignore), content_words(b, ignore)
    if len(wa) < 3 or len(wb) < 3:
        return 0.0
    return len(wa & wb) / min(len(wa), len(wb))


def restated_sentences(text: str, earlier: str, *, threshold: float = 0.6,
                       against: str = "") -> List[Tuple[str, str]]:
    """Sentences of ``text`` that retell a sentence of ``earlier``:
    (sentence, the earlier sentence). With ``against`` (the passage being
    replaced), a sentence that's closer to the passage itself is fine —
    unless that passage sentence is itself a retelling."""
    earlier_sents = split_sentences(earlier)[-14:]
    # A retelling often merges two neighbouring sentences into one.
    earlier_sents += [f"{a} {b}" for a, b in zip(earlier_sents, earlier_sents[1:])]

    names = _capitalized(text, earlier, against)
    sim = lambda a, b: similarity(a, b, names)

    def retells(sent):
        return max((sim(sent, e) for e in earlier_sents), default=0.0) >= threshold

    own = [o for o in split_sentences(against) if not retells(o)]
    out = []
    for sent in split_sentences(text):
        # Short sentences share a word or two with anything nearby.
        if len(content_words(sent, names)) < 4:
            continue
        best = max(earlier_sents, key=lambda e: sim(sent, e), default="")
        score = sim(sent, best) if best else 0.0
        if score < threshold:
            continue
        if own and max(sim(sent, o) for o in own) >= score:
            continue
        out.append((sent, best))
    return out


def _copied_context(candidate: str, original: str, around: str, n: int = 8) -> bool:
    def grams(text):
        w = _words(text)
        return {" ".join(w[i:i + n]) for i in range(len(w) - n + 1)}
    return bool((grams(candidate) & grams(around)) - grams(original))


def _style_counts(text: str) -> Counter:
    from src.utils.style_checks import analyze_document
    return Counter(i.kind for i in analyze_document(text, kinds=set(_STYLE_KINDS)))


def check_rewrite(original: str, candidate: str, *, voice: Any = None,
                  known_names: Iterable[str] = (), before: str = "", after: str = "",
                  focus: str = "", notes: str = "",
                  avoid: Optional[Iterable[str]] = None) -> RewriteCheck:
    """Problems with ``candidate`` as a replacement for ``original``.

    ``notes`` is the story-bible text the model was given (new concrete
    facts are fine if they come from it); ``avoid`` the writer's banned
    phrases (default: from settings).
    """
    check = RewriteCheck()
    if not (candidate or "").strip():
        check.serious.append("is empty")
        return check
    names = list(known_names)
    check.serious += _name_problems(candidate, f"{before}\n{original}\n{after}", names)

    context = f"{before[-1500:]}\n{original}"
    want_person, want_tense = person_and_tense(context)
    context_words = _words(_narration(context))
    if (not want_person and len(context_words) >= 12
            and not any(w in _FIRST for w in context_words)):
        want_person = "third"              # no "I" anywhere around it
    want_person = getattr(voice, "person", "") or want_person
    want_tense = getattr(voice, "tense", "") or want_tense
    got_person, got_tense = person_and_tense(candidate)
    if want_person in ("first", "third") and got_person and got_person != want_person:
        check.serious.append(f"switches the narration to {got_person} person")
    if want_tense and got_tense and got_tense != want_tense:
        check.serious.append(f"switches to {got_tense} tense")

    n_orig, n_new = len(_words(original)), len(_words(candidate))
    length_asked = any(w in (focus or "").lower() for w in _LENGTH_WORDS)
    if n_orig >= 8 and not length_asked and not 0.4 <= n_new / n_orig <= 2.5:
        check.serious.append(f"is {'much shorter' if n_new < n_orig else 'much longer'} "
                             f"({n_new} words vs {n_orig})")
    if _copied_context(candidate, original, f"{before[-2000:]}\n{after[:2000]}"):
        check.serious.append("repeats text from before or after the passage")
    else:
        retold = restated_sentences(candidate, before[-2500:], against=original)
        if retold:
            check.serious.append(f"retells “{_short(retold[0][1])}”, which comes before the passage")
        elif restated_sentences(candidate, after[:1500], against=original):
            check.serious.append("retells what comes after the passage")

    scene = f"{before}\n{original}\n{after}"
    invented = new_facts(candidate, f"{scene}\n{notes}\n{focus}")
    if invented:
        check.serious.append("adds " + ", ".join(f"“{w}”" for w in invented[:3])
                             + ", which isn't in the scene or your notes")

    avoid = avoid_phrases() if avoid is None else list(avoid)
    stock = [p for p in stock_phrases_in(candidate, avoid)
             if p not in stock_phrases_in(scene, avoid)]
    if len(stock) >= 2 or any(p in avoid for p in stock):
        check.serious.append("leans on stock phrasing (" + ", ".join(stock[:3]) + ")")
    elif stock:
        check.minor.append(f"uses the stock phrase “{stock[0]}”")
    rates = getattr(voice, "punctuation_per_100_sentences", None) or {}
    if (getattr(voice, "can_judge_absence", False) and rates.get("em-dashes", 1) == 0
            and re.search(r"—|--", candidate) and not re.search(r"—|--", original)):
        check.minor.append("adds em-dashes, which you don't use")

    try:
        was, now = _style_counts(original), _style_counts(candidate)
        for kind, label in _STYLE_KINDS.items():
            added = now[kind] - was[kind]
            if added >= (1 if kind == "cliche" else 2):
                check.minor.append(f"adds {label}")
    except Exception as e:
        print(f"[rewrite-check] style check failed: {e}")

    if voice is not None and hasattr(voice, "fit_score"):
        check.voice_fit = voice.fit_score(candidate)
        if check.voice_fit is not None and check.voice_fit < 0.55:
            check.minor.append(f"is a weak match for your voice ({check.voice_fit:.0%})")
    return check


def _short(text: str, n: int = 70) -> str:
    text = " ".join(text.split())
    return text if len(text) <= n else text[:n - 1] + "…"


def known_names_for(project: Any) -> List[str]:
    """Character and world element names, for spelling checks."""
    if project is None:
        return []
    names = [c.name for c in getattr(project, "characters", None) or [] if c.name]
    try:
        from src.ai.canon_index import collect_world_entities
        for e in collect_world_entities(getattr(project, "worldbuilding", None)):
            names.append(e.name)
            names.extend(e.aliases)
    except Exception:
        pass
    return names


# ── Learned examples ─────────────────────────────────────────────────

def _overlap(a: str, b: str) -> float:
    wa, wb = set(_words(a)), set(_words(b))
    return len(wa & wb) / (len(wa | wb) or 1)


def examples_prompt(passage: str, project_path: str = "", *, chosen: int = 2,
                    rejected: int = 1, max_chars: int = 500, db: Any = None) -> str:
    """The writer's best-rated past rewrites (and rejected ones) closest to
    ``passage``, as a prompt block. "" when there's nothing rated yet."""
    try:
        if db is None:
            from src.data.rephrase_database import get_rephrase_database
            db = get_rephrase_database()
        rows = db.rated_examples(project_path=project_path)
    except Exception as e:
        print(f"[examples] rated rewrites unavailable: {e}")
        return ""

    def pick(items, n):
        usable = [r for r in items if r.get("source_text") and r.get("output_text")
                  and len(r["source_text"]) <= max_chars and len(r["output_text"]) <= max_chars]
        usable.sort(key=lambda r: (-(r.get("rating") == "excellent")
                                   - (r.get("project_path") == project_path) * 0.5
                                   - _overlap(passage, r["source_text"])))
        return usable[:n]

    good, bad = pick(rows.get("chosen", []), chosen), pick(rows.get("rejected", []), rejected)
    if not good and not bad:
        return ""
    lines = ["REWRITES THIS AUTHOR RATED (learn their taste; don't reuse the content):"]
    for r in good:
        lines.append(f"• Original: \"{r['source_text']}\"\n  They chose: \"{r['output_text']}\"")
    for r in bad:
        lines.append(f"• Original: \"{r['source_text']}\"\n  They rejected: \"{r['output_text']}\"")
    return "\n".join(lines)


def log_rated_rewrite(source: str, output: str, rating: str, *, accepted: bool,
                      project_path: str = "", style: str = "suggestion",
                      before: str = "", after: str = "", genre: str = "") -> bool:
    """Save a rated rewrite for training and future examples (only when
    the writer has turned on data collection)."""
    try:
        from src.data.rephrase_database import get_rephrase_database, is_collection_enabled
        if not is_collection_enabled():
            return False
        if not source.strip() or not output.strip() or source.strip() == output.strip():
            return False
        get_rephrase_database().log_rephrase(
            source_text=source.strip(), output_text=output.strip(), style=style,
            surrounding_before=before, surrounding_after=after, genre=genre,
            accepted=accepted, rating=rating, project_path=project_path)
        return True
    except Exception as e:
        print(f"[examples] could not save rating: {e}")
        return False


# ── Showing changes ──────────────────────────────────────────────────

def diff_html(original: str, rewrite: str) -> str:
    """Word-level diff: removed words struck through red, added green."""
    a = re.findall(r"\S+|\s+", original or "")
    b = re.findall(r"\S+|\s+", rewrite or "")
    out: List[str] = []
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if tag == "equal":
            out.append(html.escape("".join(a[i1:i2])))
            continue
        if tag in ("delete", "replace") and "".join(a[i1:i2]).strip():
            out.append("<span style='color:#b91c1c;text-decoration:line-through'>"
                       f"{html.escape(''.join(a[i1:i2]))}</span>")
        if tag in ("insert", "replace") and "".join(b[j1:j2]).strip():
            out.append("<span style='color:#15803d;font-weight:600'>"
                       f"{html.escape(''.join(b[j1:j2]))}</span>")
    return "".join(out).replace("\n", "<br>")


def best_first(items: Sequence[Any], checks: Sequence[RewriteCheck]) -> List[int]:
    """Indices ordered best first (fewest problems, then voice fit); stable."""
    return sorted(range(len(items)), key=lambda i: (checks[i].rank(), i))
