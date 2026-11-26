"""A model names and refines the voice groups (piece V.3).

With a model set up, each group V.2 made or merged (and each of the
writer's own groups left without a name) gets a short human name and a
one-line description, written from a few sample passages. The model may
also be asked two things, and only ever proposes (V.5 shows the proposals
with Accept and Decline):

* whether two groups kept apart as a borderline case (their separation
  between ``SAME`` and ``APART``) are really one voice;
* over ``MAX_AUTO_GROUPS`` groups, which of the closest pairs reads most
  alike, to choose V.5's "more than 8 voices" merge suggestion.

Names the writer gave are never changed (``voice_groups.name_from_model``
ignores them); a merged group whose part had the writer's name keeps it
(``voice_groups.merge_groups``). Without a model, or with a failed or
unreadable reply, nothing changes and the plain-words description stands.

**The model** is the one Rephrase uses (``word_suggest.get_llm``: the
Rephrase task model, else the default). Work runs on a background thread,
never the GUI thread. An on-device model is never loaded for this: it is
used only when it is already in memory, and only while no other feature
is generating with it (``mlx_utils.MLX_GENERATE_LOCK``, tried without
waiting long). One short call per group; local models get compact
prompts (``is_local_llm``).

The model's verdicts are kept in the groups file under ``model_advice``
(an older app ignores the key), so a regroup does not lose them and the
same question is not asked twice.
"""

from __future__ import annotations

import re
import threading
import time
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from src.ai import voice_groups as vg

MAX_PER_RUN = 8                 # groups named in one run
BORDERLINE_PER_RUN = 2          # "same voice?" questions in one run
MOST_ALIKE_CANDIDATES = 3       # pairs offered when there are more than 8 groups
BUSY_WAIT = 30.0                # seconds to wait for an on-device model in use
NAME_MAX_WORDS = 5
NAME_MAX_CHARS = 40
DESCRIPTION_MAX_CHARS = 160

SYSTEM = ("You describe a writer's prose voice for the writer: how it is written, "
          "never what happens in it. Be brief and concrete. Follow the answer format exactly.")


class Busy(Exception):
    """The on-device model is in use by another feature."""


# ── Prompts and replies ──────────────────────────────────────────────

def _clip(text: str, n: int) -> str:
    """At most ``n`` characters, ending at a sentence where possible."""
    text = " ".join((text or "").split())
    if len(text) <= n:
        return text
    cut = text[:n]
    end = max(cut.rfind(". "), cut.rfind("! "), cut.rfind("? "), cut.rfind('." '))
    return (cut[:end + 1] if end > n // 2 else cut.rstrip() + "…").strip()


def naming_prompt(samples: Sequence[str], measures: str = "", taken: Sequence[str] = (),
                  compact: bool = False) -> str:
    n = 3 if compact else 4
    size = 350 if compact else 600
    parts = [f"Passages written in one voice:"]
    for i, s in enumerate(list(samples)[:n], 1):
        parts.append(f"{i}. {_clip(s, size)}")
    if measures:
        parts.append(f"Measured: {measures}.")
    if taken:
        parts.append("Names already used (choose another): " + "; ".join(taken[:8]) + ".")
    parts.append("Name this voice in 2 to 4 words (for example: Wry first-person narrator). "
                 "Then describe it in one sentence of at most 20 words: how it is written, "
                 "not the story.\nAnswer exactly:\nNAME: …\nDESCRIPTION: …")
    return "\n\n".join(parts)


def same_voice_prompt(a: Sequence[str], b: Sequence[str], compact: bool = False) -> str:
    n = 2 if compact else 3
    size = 300 if compact else 500
    lines = ["Group A:"] + [f"- {_clip(s, size)}" for s in list(a)[:n]]
    lines += ["", "Group B:"] + [f"- {_clip(s, size)}" for s in list(b)[:n]]
    lines += ["", "Are A and B written in the same voice (narration, sentence style, person "
                  "and tense), even if the stories differ?\nAnswer exactly:\nSAME: yes or no\n"
                  "WHY: one short sentence"]
    return "\n".join(lines)


def most_alike_prompt(groups: Dict[str, Tuple[str, str]], pairs: Sequence[Tuple[str, str]],
                      compact: bool = False) -> str:
    """``groups``: id -> (name or description, one sample)."""
    size = 200 if compact else 350
    letters = {gid: chr(ord("A") + i) for i, gid in enumerate(groups)}
    lines = ["Voices:"]
    for gid, (name, sample) in groups.items():
        lines.append(f"{letters[gid]}. {name}: “{_clip(sample, size)}”")
    lines += ["", "Pairs:"]
    for i, (x, y) in enumerate(pairs, 1):
        lines.append(f"{i}. {letters[x]} and {letters[y]}")
    lines += ["", "Which pair reads most alike? Answer exactly:\nPAIR: number"]
    return "\n".join(lines)


def _clean_line(text: str) -> str:
    text = re.sub(r"[*_`#]+", "", text or "").strip()
    text = text.strip(" \"“”'‘’.:;-–—")
    return " ".join(text.split())


def _strip(reply: Any) -> str:
    if not isinstance(reply, str):
        return ""
    try:
        from src.ai.output_sanitizer import strip_meta_tokens
        return strip_meta_tokens(reply)
    except Exception:
        return reply


def parse_name(reply: Any) -> Optional[Tuple[str, str]]:
    """``(name, description)`` from a reply, or None when it is unreadable."""
    text = _strip(reply)
    m = re.search(r"^\W*NAME\s*[:：]\s*(.+)$", text, re.I | re.M)
    if not m:
        return None
    name = _clean_line(m.group(1))
    words = name.split()
    if (not name or not re.search(r"[A-Za-z]", name) or len(words) > NAME_MAX_WORDS
            or len(name) > NAME_MAX_CHARS or re.search(r"[{}<>\[\]|]", name)):
        return None
    name = name[:1].upper() + name[1:]
    d = re.search(r"^\W*DESCRIPTION\s*[:：]\s*(.+)$", text, re.I | re.M)
    desc = _clean_line(d.group(1)) if d else ""
    if desc:
        desc = desc[:1].upper() + desc[1:]
        if len(desc) > DESCRIPTION_MAX_CHARS or not re.search(r"[A-Za-z]", desc):
            desc = ""
        elif not desc.endswith((".", "!", "?")):
            desc += "."
    return name, desc


def parse_same(reply: Any) -> Optional[Tuple[bool, str]]:
    text = _strip(reply)
    m = re.search(r"^\W*SAME\s*[:：]\s*\W*(yes|no)\b", text, re.I | re.M)
    if not m:
        return None
    w = re.search(r"^\W*WHY\s*[:：]\s*(.+)$", text, re.I | re.M)
    why = _clean_line(w.group(1))[:DESCRIPTION_MAX_CHARS] if w else ""
    return m.group(1).lower() == "yes", why


def parse_pair(reply: Any, count: int) -> Optional[int]:
    """The chosen pair's index (0-based), or None."""
    m = re.search(r"^\W*PAIR\s*[:：]\s*\W*(\d+)", _strip(reply), re.I | re.M)
    if not m:
        return None
    i = int(m.group(1)) - 1
    return i if 0 <= i < count else None


# ── The model: the one Rephrase uses, never loaded for this ──────────

def _configured_local() -> Optional[str]:
    """The on-device model id the writing model would be, "" for a cloud
    or server model, None when nothing can be worked out (do not name)."""
    try:
        from src.config.creativeos_config import get_creativeos_config
        res = get_creativeos_config().resolve_task_model("rephrase") or {}
        spec = res.get("spec") or {}
        kind = spec.get("kind", "")
        if kind == "trained":
            return (res.get("trained_model") or {}).get("path", "") or None
        if kind in ("hf", "mlx", "local"):
            return spec.get("model_id", "") or None
        if kind == "cloud":
            return ""
        from src.config.ai_config import get_ai_config
        s = get_ai_config().get_settings()
        local_id = s.get("local_model_id", "")
        if s.get("prefer_local_model", False) and s.get("enable_local_models", False) and local_id:
            return local_id
        return ""
    except Exception:
        return None


def _resident(model_id: str) -> bool:
    """The on-device model is already in memory (no load needed)."""
    try:
        from src.ai import mlx_utils
        model, _tok = mlx_utils.get_mlx_cache().get_model(model_id)
        if model is not None:
            return True
        live = mlx_utils._live_models.get(model_id)
        return bool(live and live[0]() is not None)
    except Exception:
        return False


def model_if_ready():
    """The writing model if it can be used now without loading anything
    heavy, else None. Never raises."""
    try:
        from src.ai import word_suggest as ws
        with ws._LOCK:
            llm = ws._LLM.get("llm")
        if llm is not None:
            return llm
        local = _configured_local()
        if local is None:
            return None
        if local and not _resident(local):
            return None                 # an on-device model is never loaded just for names
        return ws.get_llm()
    except Exception as e:
        print(f"[voice naming] no model: {e}")
        return None


def _is_local(llm) -> bool:
    try:
        from src.ai.chapter_analysis_agent import is_local_llm
        return bool(is_local_llm(llm))
    except Exception:
        return False


def ask(llm, prompt: str, max_tokens: int = 80, wait: float = BUSY_WAIT) -> str:
    """One short call. An on-device model is used only while no other
    feature is generating with it (waits up to ``wait`` seconds, then
    raises :class:`Busy`)."""
    if not _is_local(llm):
        return llm.generate_text(prompt, SYSTEM, max_tokens=max_tokens, temperature=0.3)
    from src.ai.mlx_utils import MLX_GENERATE_LOCK
    deadline = time.monotonic() + max(0.0, wait)
    while not MLX_GENERATE_LOCK.acquire(blocking=False):
        if time.monotonic() >= deadline:
            raise Busy()
        time.sleep(1.0)
    try:
        return llm.generate_text(prompt, SYSTEM, max_tokens=max_tokens, temperature=0.3)
    finally:
        MLX_GENERATE_LOCK.release()


# ── Samples ──────────────────────────────────────────────────────────

def _sources(db, state):
    from src.data import voice_groups_store as vgs
    from src.data import voice_ratings as vr
    return vr.live_sources(vgs.read_rows(db), state)


def samples_for(db, state: Dict[str, Any], gid: str, srcs, n: int = 4) -> List[str]:
    """A few distinct rated passages of the group, taken in turn from each
    of its sources (newest first). Read only."""
    g = (state.get("groups") or {}).get(gid) or {}
    per: List[List[str]] = []
    conn = db._conn()
    for key in g.get("sources") or []:
        s = srcs.get(key)
        if s is None or not s.ids:
            continue
        ids = sorted(s.ids, reverse=True)[:60]
        q = ",".join("?" * len(ids))
        texts, seen = [], set()
        for r in conn.execute(f"SELECT source_text, surrounding_before FROM rephrases "
                              f"WHERE id IN ({q}) ORDER BY id DESC", ids).fetchall():
            t = " ".join((r[0] or "").split())
            if len(t) < 200 and r[1]:
                t = " ".join((r[1] or "").split())[-(400 - len(t)):] + " " + t
            t = t.strip()
            if len(t) >= 40 and t not in seen:
                seen.add(t)
                texts.append(t)
            if len(texts) >= n:
                break
        if texts:
            per.append(texts)
    out: List[str] = []
    while per and len(out) < n:
        for texts in list(per):
            if texts:
                out.append(texts.pop(0))
            if not texts:
                per.remove(texts)
            if len(out) >= n:
                break
    return out


def _signature(state: Dict[str, Any], gids: Sequence[str]) -> str:
    groups = state.get("groups") or {}
    return "|".join(sorted(k for g in gids for k in (groups.get(g) or {}).get("sources") or []))


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


# ── Applying the model's answers (under the store's lock) ────────────

def _commit(change: Callable[[Dict[str, Any]], Optional[Dict[str, Any]]]) -> bool:
    """Load the latest state, change it, save. The writer may have changed
    the groups while the model was thinking, so ``change`` checks again."""
    from src.data import voice_groups_store as vgs
    with vgs._lock:
        state = vgs.load_state()
        got = change(state)
        if got is None:
            return False
        return vgs.save_state(got)


def apply_name(gid: str, signature: str, name: str, description: str) -> bool:
    """Name the group if it is still the group the samples came from and
    the writer has not named it meanwhile."""
    def change(state):
        g = state["groups"].get(gid)
        if not g or g.get("named_by") == "writer" or _signature(state, [gid]) != signature:
            return None
        taken = {vg.display_name(o).lower() for k, o in state["groups"].items() if k != gid}
        if name.lower() in taken:
            return None
        state = vg.name_from_model(state, gid, name, description)
        if not description:
            state["groups"][gid].pop("model_description", None)
        return state
    return _commit(change)


def _advice(state: Dict[str, Any]) -> Dict[str, Any]:
    a = state.get("model_advice")
    if not isinstance(a, dict):
        a = {}
    if not isinstance(a.get("same_voice"), dict):
        a["same_voice"] = {}
    if not isinstance(a.get("most_alike"), dict):
        a["most_alike"] = {}
    return a


# ── What V.5 shows: V.2's proposals with the model's advice ──────────

def with_advice(state: Dict[str, Any]) -> List[Dict[str, Any]]:
    """The proposals to show: V.2's, the "more than 8" merge pointed at the
    pair the model reads as most alike, and a merge proposal for each
    borderline pair the model reads as one voice. Dismissed ones stay
    dismissed. Advice that no longer fits the groups is ignored."""
    props = [dict(p) for p in state.get("proposals") or [] if isinstance(p, dict)]
    try:
        advice = state.get("model_advice")
        if not isinstance(advice, dict):
            return props
        groups = state.get("groups") or {}
        dismissed = set(state.get("dismissed") or [])

        def valid(pair):
            return (isinstance(pair, list) and len(pair) == 2 and pair[0] != pair[1]
                    and all(g in groups for g in pair))

        ma = advice.get("most_alike") or {}
        pair = ma.get("pair")
        if valid(pair) and _signature(state, pair) == ma.get("pair_sources"):
            for i, p in enumerate(props):
                if (p.get("kind") == "merge" and (p.get("why") or "").startswith("more than")
                        and set(p.get("groups") or []) != set(pair)):
                    ss = list(p.get("sources") or [])
                    key = f"merge:{'+'.join(sorted(pair))}|{'+'.join(ss)}"
                    if key not in dismissed:
                        props[i] = dict(p, key=key, groups=sorted(pair), by_model=True)
        have = {frozenset(p.get("groups") or []) for p in props if p.get("kind") == "merge"}
        for pk, v in sorted((advice.get("same_voice") or {}).items()):
            gs = v.get("groups") if isinstance(v, dict) else None
            if not (v.get("same") and valid(gs)) or _signature(state, gs) != v.get("sources"):
                continue
            key = f"merge:{'+'.join(sorted(gs))}|model"
            if key in dismissed or frozenset(gs) in have:
                continue
            have.add(frozenset(gs))
            props.append({"key": key, "kind": "merge", "groups": sorted(gs), "sources": [],
                          "why": "the model reads them as one voice" +
                                 (f": {v['why']}" if v.get("why") else ""),
                          "by_model": True})
    except Exception as e:
        print(f"[voice naming] advice ignored: {e}")
    return props


# ── One run ──────────────────────────────────────────────────────────

def _pair_distances(state, srcs) -> List[Tuple[float, str, str]]:
    """Average source separation for every pair of groups, closest first."""
    groups = state.get("groups") or {}
    mats = {gid: [srcs[k].matrix() for k in g.get("sources") or []
                  if k in srcs and srcs[k].passages]
            for gid, g in groups.items()}
    out = []
    ids = sorted(gid for gid, m in mats.items() if m)
    for i, a in enumerate(ids):
        for b in ids[i + 1:]:
            seps = [vg.separation(x, y) for x in mats[a] for y in mats[b]]
            out.append((sum(seps) / len(seps), a, b))
    return sorted(out)


def name_groups(db=None, llm=None, *, wait: float = BUSY_WAIT) -> Dict[str, Any]:
    """Name the groups that need it and ask the borderline questions.
    Returns what happened: ``named`` (ids), ``failed`` (ids), ``asked``
    (questions put), ``busy`` (stopped because the on-device model was in
    use), ``model`` (False when there was none). Never raises."""
    from src.data import voice_groups_store as vgs
    done: Dict[str, Any] = {"named": [], "failed": [], "asked": 0, "busy": False, "model": True}
    try:
        db = vgs._db(db)
        state = vgs.load_state()
        todo = vg.needs_name(state)
        if not state.get("groups"):
            return done
        llm = llm if llm is not None else model_if_ready()
        if llm is None:
            done["model"] = False
            return done
        compact = _is_local(llm)
        srcs = _sources(db, state)
        samples: Dict[str, List[str]] = {}

        def sample(gid):
            if gid not in samples:
                samples[gid] = samples_for(db, state, gid, srcs, 3 if compact else 4)
            return samples[gid]

        # 1. Names.
        for gid in todo[:MAX_PER_RUN]:
            texts = sample(gid)
            if not texts:
                continue                       # example passages only: nothing to read
            g = state["groups"][gid]
            taken = sorted({vg.display_name(o) for k, o in state["groups"].items()
                            if k != gid and o.get("name")})
            try:
                reply = ask(llm, naming_prompt(texts, g.get("description") or "", taken, compact),
                            max_tokens=70, wait=wait)
            except Busy:
                done["busy"] = True
                return done
            except Exception as e:
                print(f"[voice naming] {gid}: no reply ({e})")
                done["failed"].append(gid)
                continue
            got = parse_name(reply)
            if got and apply_name(gid, _signature(state, [gid]), *got):
                done["named"].append(gid)
            else:
                done["failed"].append(gid)

        # 2. Borderline pairs: kept apart, but not clearly different.
        state = vgs.load_state()
        advice = _advice(state)
        pairs = _pair_distances(state, srcs)
        asked = 0
        for d, a, b in pairs:
            if asked >= BORDERLINE_PER_RUN:
                break
            if not (vg.SAME < d < vg.APART):
                continue
            pk, sig = f"{a}+{b}", _signature(state, [a, b])
            if (advice["same_voice"].get(pk) or {}).get("sources") == sig:
                continue                       # asked already about these groups
            ta, tb = sample(a), sample(b)
            if not ta or not tb:
                continue
            try:
                reply = ask(llm, same_voice_prompt(ta, tb, compact), max_tokens=60, wait=wait)
            except Busy:
                done["busy"] = True
                return done
            except Exception as e:
                print(f"[voice naming] {pk}: no reply ({e})")
                continue
            asked += 1
            got = parse_same(reply)
            if got is None:
                continue
            verdict = {"groups": [a, b], "sources": sig, "same": got[0], "why": got[1],
                       "separation": round(float(d), 3), "at": _now()}

            def put(st, pk=pk, verdict=verdict, sig=sig):
                if _signature(st, verdict["groups"]) != sig:
                    return None
                adv = _advice(st)
                adv["same_voice"][pk] = verdict
                st["model_advice"] = adv
                return st
            _commit(put)

        # 3. More than 8 groups: which of the closest pairs is most alike.
        over = [p for p in state.get("proposals") or []
                if p.get("kind") == "merge" and (p.get("why") or "").startswith("more than")]
        anchors = {gid for gid in state.get("groups") or {} if vg.is_anchor(state, gid)}
        cands = [(a, b) for _d, a, b in pairs if a not in anchors and b not in anchors]
        cands = cands[:MOST_ALIKE_CANDIDATES]
        if over and len(cands) >= 2:
            sig = "||".join(f"{a}+{b}:{_signature(state, [a, b])}" for a, b in cands)
            if advice["most_alike"].get("candidates") != sig:
                ids = list(dict.fromkeys(g for p in cands for g in p))
                shown = {}
                for gid in ids:
                    t = sample(gid)
                    shown[gid] = (vg.display_name(state["groups"][gid]), t[0] if t else "")
                try:
                    reply = ask(llm, most_alike_prompt(shown, cands, compact), max_tokens=12,
                                wait=wait)
                    asked += 1
                    i = parse_pair(reply, len(cands))
                except Busy:
                    done["busy"] = True
                    return done
                except Exception as e:
                    print(f"[voice naming] most alike: no reply ({e})")
                    i = None
                if i is not None:
                    pick = list(cands[i])

                    def put_pair(st, pick=pick, sig=sig):
                        if _signature(st, pick) != _signature(state, pick):
                            return None
                        adv = _advice(st)
                        adv["most_alike"] = {"candidates": sig, "pair": pick,
                                             "pair_sources": _signature(st, pick), "at": _now()}
                        st["model_advice"] = adv
                        return st
                    _commit(put_pair)
        done["asked"] = asked
    except Exception as e:
        print(f"[voice naming] stopped: {e}")
    return done


# ── In the background ────────────────────────────────────────────────

_job: Dict[str, Any] = {"thread": None, "at": 0.0}
AGAIN_AFTER = 120.0             # seconds before an unasked-for run repeats


def is_app_db(db) -> bool:
    """The groups file belongs to the app's own ratings database."""
    try:
        from src.data import rephrase_database as rd
        path = getattr(db, "db_path", None)
        return db is None or (path is not None and
                              path.resolve() == rd.DEFAULT_DB_PATH.resolve())
    except Exception:
        return False


def start_naming(db=None, on_done: Optional[Callable[[Dict[str, Any]], None]] = None,
                 llm=None, force: bool = False) -> Optional[threading.Thread]:
    """Run :func:`name_groups` on a daemon thread (one at a time). Only for
    the app's own ratings database. ``on_done(result)`` is called from that
    thread when something changed. Runs again only after ``AGAIN_AFTER``
    seconds unless ``force`` (a rebuild). Never blocks the caller."""
    if not is_app_db(db):
        return None
    t = _job.get("thread")
    if t is not None and t.is_alive():
        return t
    if not force and time.monotonic() - _job.get("at", 0.0) < AGAIN_AFTER and _job.get("at"):
        return None
    _job["at"] = time.monotonic()

    def run():
        from src.data import voice_groups_store as vgs
        nonlocal db
        try:
            db = vgs._db(db)
            got = name_groups(db, llm)
            if got.get("named"):
                print(f"[voice naming] named {len(got['named'])} group(s)")
            if on_done is not None and (got.get("named") or got.get("asked")):
                on_done(got)
        except Exception as e:
            print(f"[voice naming] stopped: {e}")
        finally:
            try:
                c = getattr(getattr(db, "_local", None), "conn", None)
                if c is not None:
                    c.close()
                    db._local.conn = None
            except Exception:
                pass

    t = threading.Thread(target=run, name="voice-naming", daemon=True)
    _job["thread"] = t
    t.start()
    return t
