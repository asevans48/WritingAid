"""Managing ratings by voice (piece V.5). No Qt.

What the writer sees and does in Training Studio ▸ Browse rows… with
Source set to "Rated rewrites, by voice" (``src/ui/voice_groups_view.py``):
the voice groups (V.2), the voice sources inside each (a project, or a
project's narrator), the ratings inside each source, and the sources not
sorted yet.

Every change to the groups goes through :func:`voice_groups_store.apply`
(which saves and hands back the state before, for undo); every change to
a rating goes through the ratings database (``update_rating``,
``delete_one``). The groups file is the only thing written here apart
from those two calls and the "keep to itself" switch
(:mod:`src.data.ratings_privacy`, shared with V.4).

Counts come from the ratings as they are now, not from the last check, so
a removed rating disappears at once.
"""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple

from src.ai import voice_groups as vg
from src.data import ratings_privacy
from src.data import voice_groups_store as vgs

# A source the writer asked to leave its group starts on its own at the
# next regroup (any id that is not a group).
_ALONE = "-"

WHY_COUNT = (f"As many groups as there are strong, distinct voices in your ratings; "
             f"the app makes at most {vg.MAX_AUTO_GROUPS}. A project or narrator counts "
             f"once {vg.MIN_SOURCE_RATINGS} different passages of it are rated.")
LOOSE_WARNING = "These voices differ; rewrites will learn less precisely from the merged group."


# ── Reading ──────────────────────────────────────────────────────────

def parse_key(key: str) -> Tuple[str, str, str]:
    """(project_path, character_name, part) from a source key."""
    base, _, part = key.partition("#")
    pp, _, ch = base.partition("::")
    return pp, ch, part


def label_of(state: Dict[str, Any], key: str) -> str:
    s = (state.get("sources") or {}).get(key) or {}
    return s.get("label") or vg.source_label(*parse_key(key))


def live_sources(rows: Iterable[Dict[str, Any]], state: Dict[str, Any]) -> Dict[str, vg.Source]:
    """The sources as the ratings are now, split where the groups split them."""
    out: Dict[str, vg.Source] = {}
    for key, src in vg.collect_sources(rows).items():
        split = (state.get("splits") or {}).get(key)
        if split:
            for part in vg._split_by_centres(src, split):
                if part.ids:
                    out[part.key] = part
        else:
            out[key] = src
    return out


def strength_words(group: Dict[str, Any], members: Sequence[Dict[str, Any]]) -> str:
    """How alike a group's sources are, in words. One source: "one project"
    or "one narrator" (there is nothing to compare)."""
    if len(members) == 1:
        return "one narrator" if members[0].get("character_name") else "one project"
    if not members:
        return "example passages" if group.get("seed_passages") else "empty"
    return group.get("strength") or vg.strength_label(float(group.get("widest") or 0.0))


def overview(db, state: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Everything the view shows: ``groups`` (largest first), ``unsorted``
    sources, ``proposals`` (plain words), ``ratings`` in all."""
    state = vg.normalise_state(state if state is not None else vgs.load_state())
    rows = vgs.read_rows(db)
    srcs = live_sources(rows, state)
    pins = state["pins"]
    private: Dict[str, bool] = {}
    entries: Dict[str, Dict[str, Any]] = {}
    for key, s in sorted(srcs.items()):
        st = state["sources"].get(key) or {}
        gid = st.get("group") if st.get("group") in state["groups"] else None
        gid = gid or (pins.get(key) if pins.get(key) in state["groups"] else None)
        pp = s.project_path
        if pp not in private:
            private[pp] = ratings_privacy.is_private(pp)
        entries[key] = {
            "key": key, "label": s.label, "project_path": pp,
            "character_name": s.character_name, "part": s.part,
            "ratings": len(s.ids), "passages": s.passages, "ids": list(s.ids),
            "group": gid, "pinned": key in pins, "private": private[pp],
            "waiting": st.get("status") == "waiting" and not gid,
            "needs": 0 if key in pins else max(0, vg.MIN_SOURCE_RATINGS - s.passages),
        }
    groups = []
    for gid, g in state["groups"].items():
        members = [e for e in entries.values() if e["group"] == gid]
        groups.append({
            "id": gid, "name": vg.display_name(g), "named": bool(g.get("name")),
            "writer_named": g.get("named_by") == "writer",
            "description": g.get("model_description") or g.get("description") or "",
            "measures": g.get("description") or "",
            "strength": strength_words(g, members),
            "loose": len(members) > 1 and (g.get("strength") == "loose"),
            "ratings": sum(e["ratings"] for e in members),
            "passages": sum(e["passages"] for e in members),
            "projects": sorted({Path(e["project_path"]).stem for e in members}),
            "sources": members, "anchor": vg.is_anchor(state, gid),
            "examples": len(g.get("seed_passages") or []),
        })
    groups.sort(key=lambda g: (-g["ratings"], g["name"].lower(), g["id"]))
    unsorted = sorted((e for e in entries.values() if not e["group"]),
                      key=lambda e: (e["needs"], -e["passages"], e["label"].lower()))
    return {"groups": groups, "unsorted": unsorted, "sources": entries,
            "proposals": proposals(db, state, rows),
            "ratings": sum(e["ratings"] for e in entries.values()),
            "checked_at": state.get("checked_at") or "", "state": state}


def merged_widest(db, state: Dict[str, Any], gids: Sequence[str], rows=None) -> float:
    """The widest separation between any two sources of these groups taken
    together (as V.2 measures a group's strength; example passages aside)."""
    rows = vgs.read_rows(db) if rows is None else rows
    srcs = live_sources(rows, state)
    keys = sorted({k for gid in gids for k in (state["groups"].get(gid) or {}).get("sources") or []
                   if k in srcs and srcs[k].passages})
    worst = 0.0
    for i, a in enumerate(keys):
        for b in keys[i + 1:]:
            worst = max(worst, vg.separation(srcs[a].matrix(), srcs[b].matrix()))
    return worst


def merge_is_loose(db, state: Dict[str, Any], gids: Sequence[str], rows=None) -> bool:
    return merged_widest(db, state, gids, rows) > vg.SAME


def proposals(db, state: Dict[str, Any], rows=None) -> List[Dict[str, Any]]:
    """The proposals waiting for the writer, each with a line of plain words.
    The "more than 8 voices" merge is shown only if the merged group would
    stay strong."""
    out = []
    names = {gid: vg.display_name(g) for gid, g in state["groups"].items()}

    def gname(gid):
        return f"“{names.get(gid, gid)}”"

    def sname(keys):
        return " and ".join(f"“{label_of(state, k)}”" for k in keys)

    from src.ai import voice_naming                 # V.3: the model's advice, proposals only
    for p in voice_naming.with_advice(state):
        kind, gs, ss = p.get("kind"), list(p.get("groups") or []), list(p.get("sources") or [])
        if kind == "join" and gs:
            text = f"{sname(ss)} reads in the same voice as {gname(gs[0])}. Add it there?"
        elif kind == "merge" and len(gs) >= 2:
            if (p.get("why") or "").startswith("more than"):
                if merge_is_loose(db, state, gs, rows):
                    continue
                text = (f"More than {vg.MAX_AUTO_GROUPS} voices: merging the closest two, "
                        f"{gname(gs[0])} and {gname(gs[1])}, would make room for the ones waiting.")
            elif p.get("by_model"):
                text = (f"The model reads {gname(gs[0])} and {gname(gs[1])} as one voice. "
                        f"Merge them?")
            else:
                text = f"{gname(gs[0])} and {gname(gs[1])} read in the same voice. Merge them?"
        elif kind == "leave" and ss:
            text = f"{sname(ss)} now reads clearly unlike the rest of {gname(gs[0]) if gs else 'its group'}. Let it leave?"
        elif kind == "split" and ss:
            text = f"{sname(ss)} holds two different voices. Treat it as two?"
        elif kind == "unsplit" and ss:
            text = f"The two voices of {sname(ss)} have grown alike. Treat it as one again?"
        else:
            continue
        out.append({"key": p.get("key"), "kind": kind, "text": text, "proposal": p})
    return out


def ratings_for(db, ids: Sequence[int]) -> List[Dict[str, Any]]:
    """The ratings with these ids, newest first (read only)."""
    out: List[Dict[str, Any]] = []
    ids = [int(i) for i in ids]
    conn = db._conn()
    for i in range(0, len(ids), 500):
        chunk = ids[i:i + 500]
        q = ",".join("?" * len(chunk))
        out += [dict(r) for r in conn.execute(
            f"SELECT id, created_at, rating, accepted, source_text, output_text "
            f"FROM rephrases WHERE id IN ({q})", chunk).fetchall()]
    out.sort(key=lambda r: -int(r["id"]))
    return out


def find(db, query: str, ids: Sequence[int]) -> set:
    """Which of these ratings mention ``query`` (the passage or the rewrite)."""
    query = (query or "").strip()
    if not query:
        return set(int(i) for i in ids)
    like = f"%{query}%"
    hit = set()
    conn = db._conn()
    ids = [int(i) for i in ids]
    for i in range(0, len(ids), 500):
        chunk = ids[i:i + 500]
        q = ",".join("?" * len(chunk))
        hit |= {int(r[0]) for r in conn.execute(
            f"SELECT id FROM rephrases WHERE id IN ({q}) AND "
            f"(source_text LIKE ? OR output_text LIKE ? OR surrounding_before LIKE ?)",
            chunk + [like, like, like]).fetchall()}
    return hit


# ── The writer's changes to the groups (each returns (after, before)) ──

def _chain(*ops: Callable[[Dict[str, Any]], Any]) -> Callable[[Dict[str, Any]], Dict[str, Any]]:
    def run(state):
        for op in ops:
            got = op(state)
            state = got[0] if isinstance(got, tuple) else got
        return state
    return run


def rename(db, gid: str, name: str):
    return vgs.apply(vg.rename_group, gid, name, db=db)


def move(db, keys: Sequence[str], gid: str):
    """Put sources in a group: pinned there, so a rebuild leaves them."""
    return vgs.apply(_chain(*[(lambda st, k=k: vg.place_source(st, k, gid)) for k in keys]), db=db)


def let_app_sort(db, keys: Sequence[str]):
    return vgs.apply(_chain(*[(lambda st, k=k: vg.unpin_source(st, k)) for k in keys]), db=db)


def merge(db, gids: Sequence[str]):
    return vgs.apply(vg.merge_groups, list(gids), db=db)


def remove_group(db, gid: str):
    return vgs.apply(vg.remove_group, gid, db=db)


def new_group(db, name: str = "", sources: Sequence[str] = (), passages: Sequence[str] = ()):
    """A group the writer starts. Returns (after, before, new group id)."""
    after, before = vgs.apply(vg.create_group, name, sources=list(sources),
                              passages=list(passages), db=db)
    new = sorted(set(after["groups"]) - set(before["groups"]))
    return after, before, (new[0] if new else None)


def rebuild(db):
    """Regroup now (the writer's places and groups stay)."""
    before = vgs.load_state()
    after = vgs.run_check(db, force=True)
    return after, before


def undo(before: Dict[str, Any]) -> bool:
    return vgs.restore(before)


def leave_group(state: Dict[str, Any], key: str) -> Dict[str, Any]:
    """A source leaves its group and starts on its own at the regroup."""
    state = vg.normalise_state(state)
    state["pins"].pop(key, None)
    entry = state["sources"].setdefault(key, {})
    entry["group"] = _ALONE
    return state


def split_source(state: Dict[str, Any], key: str, record: Dict[str, Any]) -> Dict[str, Any]:
    """Treat a source as two voices: voice A stays where the source was,
    voice B starts on its own."""
    state = vg.normalise_state(state)
    state["splits"][key] = copy.deepcopy(record)
    gid = state["pins"].pop(key, None) or (state["sources"].get(key) or {}).get("group")
    if gid in state["groups"]:
        state["pins"][key + "#A"] = gid
    state["sources"][key + "#B"] = {"group": _ALONE}
    return state


def join_source(state: Dict[str, Any], key: str) -> Dict[str, Any]:
    """Treat a two-voice source as one again (where voice A was)."""
    state = vg.normalise_state(state)
    state["splits"].pop(key, None)
    gid = state["pins"].pop(key + "#A", None)
    other = state["pins"].pop(key + "#B", None)
    if gid or other:
        state["pins"][key] = gid or other
    return state


def accept(db, proposal: Dict[str, Any]):
    """Do what a proposal suggests. Returns (after, before) or None if it
    no longer applies."""
    kind = proposal.get("kind")
    gs, ss = list(proposal.get("groups") or []), list(proposal.get("sources") or [])
    if kind == "join" and gs:
        return move(db, ss, gs[0])
    if kind == "merge" and len(gs) >= 2:
        return merge(db, gs[:2])
    if kind == "leave" and ss:
        return vgs.apply(_chain(*[(lambda st, k=k: leave_group(st, k)) for k in ss]), db=db)
    if kind == "split" and ss:
        src = vg.collect_sources(vgs.read_rows(db)).get(ss[0])
        res = vg._split_source(src, vg.SPLIT_KEEP) if src is not None else None
        if not res:
            return None
        record = vg._split_record(src, *res)
        return vgs.apply(split_source, ss[0], record, db=db)
    if kind == "unsplit" and ss:
        return vgs.apply(join_source, ss[0], db=db)
    return None


def decline(db, proposal: Dict[str, Any]):
    """Say no: the same proposal is not made again."""
    return vgs.apply(vg.dismiss_proposal, proposal.get("key") or "", db=db)


# ── The writer's changes to single ratings ───────────────────────────

def change_rating(db, row_id: int, rating: str) -> Optional[str]:
    """Re-rate one rating. Returns the rating it had (for undo), or None."""
    row = db._conn().execute("SELECT rating FROM rephrases WHERE id = ?", (int(row_id),)).fetchone()
    if row is None:
        return None
    old = row[0] or "neutral"
    return old if db.update_rating(int(row_id), rating) else None


def remove_rating(db, row_id: int) -> bool:
    """Remove one rating (the view asks first; this cannot be undone)."""
    return bool(db.delete_one(int(row_id)))


# ── Keep this project's ratings to itself (V.4's switch) ─────────────

def is_private(project_path: str) -> bool:
    return ratings_privacy.is_private(project_path)


def set_private(project_path: str, value: bool) -> bool:
    return ratings_privacy.set_private(project_path, value)


def split_passages(text: str) -> List[str]:
    """Example passages pasted by the writer: separated by a line of
    ``---`` (or ``***``)."""
    parts, cur = [], []
    for line in (text or "").splitlines():
        if line.strip() in ("---", "***"):
            parts.append("\n".join(cur))
            cur = []
        else:
            cur.append(line)
    parts.append("\n".join(cur))
    return [p.strip() for p in parts if p.strip()]
