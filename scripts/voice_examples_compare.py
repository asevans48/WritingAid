"""Piece V.4's comparison, without a model: which rated rewrites each
passage would be shown, today and by voice group.

Reads the writer's ratings database read only (``mode=ro``), copies the
rated rewrites into a scratch database, fingerprints them (V.1) and
groups them (V.2) there, in memory and in the scratch folder. Nothing is
written to the real database or to ``~/.creativeos``.

For every distinct rated passage of a grouped source (leave-one-out: an
example of the same passage is never counted), the examples each choice
gives are measured by:

* how many come from the passage's own voice group,
* how many are in the passage's person (first / third),
* how far their voice fingerprint is from the passage's (in spreads),
* the voice fit (``WriterVoice.fit_score``, as every rewrite is shown) of
  the rewrite the writer chose, against the voice measured around the passage.

    venv/bin/python scripts/voice_examples_compare.py [--db PATH] [--scratch DIR]
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402

from src.ai import voice_examples as ve  # noqa: E402
from src.ai import voice_fingerprint as vf  # noqa: E402
from src.ai import voice_groups as vg  # noqa: E402
from src.ai.rewrite_quality import person_and_tense  # noqa: E402
from src.data import voice_groups_store as vgs  # noqa: E402


def copy_ratings(real: Path, scratch: Path):
    from src.data.rephrase_database import RephraseDatabase
    db = RephraseDatabase(scratch / "ratings_copy.db")
    src = sqlite3.connect(f"file:{real}?mode=ro", uri=True)
    cols = [r[1] for r in src.execute("PRAGMA table_info(rephrases)")]
    keep = [c for c in cols if c in {r[1] for r in db._conn().execute("PRAGMA table_info(rephrases)")}]
    rows = src.execute(f"SELECT {','.join(keep)} FROM rephrases WHERE source_type = 'rephrase'").fetchall()
    src.close()
    c = db._conn()
    c.executemany(f"INSERT INTO rephrases ({','.join(keep)}) VALUES ({','.join('?' * len(keep))})", rows)
    c.commit()
    from src.data import voice_fingerprint_store as vfs
    vfs.backfill(db)
    return db


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=str(Path.home() / ".creativeos" / "rephrase_history.db"))
    ap.add_argument("--scratch", default="")
    a = ap.parse_args()
    scratch = Path(a.scratch or tempfile.mkdtemp(prefix="v4-compare-"))
    scratch.mkdir(parents=True, exist_ok=True)
    db = copy_ratings(Path(a.db), scratch)
    fp_rows = vgs.read_rows(db)
    state = vg.regroup(fp_rows)
    member = vg.membership(fp_rows, state)
    vectors = {int(r["id"]): r["vector"] for r in fp_rows}
    scale = ve._scale(list(vectors.values()))
    groups = state["groups"]
    print(f"{len(fp_rows)} fingerprinted ratings, {len(groups)} group(s)")
    conn = db._conn()
    every = {int(r["id"]): dict(r) for r in conn.execute("SELECT * FROM rephrases")}

    # how many examples each group offers (chosen / rejected, usable length)
    for gid, g in groups.items():
        ids = [i for i, x in member.items() if x == gid]
        rated = ve._rated_rows(db, ids)
        usable = {k: ve._usable(v, 500) for k, v in rated.items()}
        dist = {k: len({" ".join(r["source_text"].split()) for r in v}) for k, v in usable.items()}
        print(f"group {gid} “{vg.display_name(g)}”: {len(ids)} ratings; examples offered: "
              f"{len(usable['chosen'])} chosen ({dist['chosen']} passages), "
              f"{len(usable['rejected'])} rejected")

    queries, seen = [], set()
    for i, g in member.items():
        if g == vg.UNSORTED:
            continue
        r = every[i]
        key = (r["project_path"], " ".join(r["source_text"].split()))
        if key not in seen:
            seen.add(key)
            queries.append(r)

    def measure(policy_state, as_new=False):
        same = person = n = 0
        dists, fits = [], []
        for q in queries:
            project = q["project_path"]
            if as_new:      # the same passage in a new book placed in the passage's group
                project = "/new/" + Path(project).name
                policy_state = dict(policy_state, sources=dict(policy_state.get("sources") or {}))
                if policy_state.get("groups"):
                    policy_state["sources"][vg.source_key(project, q["character_name"] or "")] = {
                        "group": member.get(int(q["id"]))}
            got = ve.choose(q["source_text"], project, db=db, chosen=6, rejected=0,
                            before=q["surrounding_before"] or "", after=q["surrounding_after"] or "",
                            character_name=q["character_name"] or "", state=policy_state)
            qs = " ".join(q["source_text"].split())
            ex = [r for r in got.chosen if " ".join(r["source_text"].split()) != qs][:2]
            want = member.get(int(q["id"]))
            qp, _ = person_and_tense(vf.rating_text(q["surrounding_before"] or "", q["source_text"],
                                                    q["surrounding_after"] or ""))
            from src.ai.writer_voice import analyze_writer_voice
            voice = analyze_writer_voice(vf.rating_text(q["surrounding_before"] or "", q["source_text"],
                                                        q["surrounding_after"] or ""))
            for r in ex:
                n += 1
                fit = voice.fit_score(r["output_text"])
                if fit is not None:
                    fits.append(fit)
                same += member.get(int(r["id"])) == want
                rp_, _ = person_and_tense(vf.rating_text(r["surrounding_before"] or "",
                                                         r["source_text"], r["surrounding_after"] or ""))
                person += bool(qp) and rp_ == qp
                d = ve._dist(vectors.get(int(q["id"])), vectors.get(int(r["id"])), scale)
                if np.isfinite(d):
                    dists.append(d)
                else:
                    dists.append(np.nan)
        return n, same, person, dists, fits

    print(f"\n{len(queries)} distinct grouped passages, 2 examples each (leave-one-out)\n")
    print("| choice | examples | from the passage's group | in the passage's person | "
          "voice fit of the chosen rewrite (mean) | voice distance median |")
    print("|---|---|---|---|---|---|")
    runs = [("today", vg.empty_state(), False, "today"),
            ("today, as a new book in that voice", vg.empty_state(), True, "today")]
    for order in ("tiers", "closest", "today"):
        runs += [(f"by voice group, order “{order}”", state, False, order),
                 (f"by voice group, order “{order}”, as a new book", state, True, order)]
    for name, st, new, order in runs:
        ve.WITHIN_GROUP = order
        n, same, person, d, fits = measure(st, new)
        d = np.asarray(d, dtype=float)
        ok = d[np.isfinite(d)]
        print(f"| {name} | {n} | {same} ({same / max(n, 1):.0%}) | {person} ({person / max(n, 1):.0%}) | "
              f"{np.mean(fits) if fits else float('nan'):.3f} ({len(fits)}) | "
              f"{np.median(ok) if len(ok) else float('nan'):.2f} |")
    ve.WITHIN_GROUP = "tiers"
    print(f"\nscratch copy: {scratch}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
