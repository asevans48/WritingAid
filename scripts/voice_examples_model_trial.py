"""Piece V.4's real trial, with the model: do rewrites made with V.4's
examples (closest in voice within the passage's voice group) fit the
passage's voice better than rewrites made with today's examples?

The set-up is ``voice_examples_compare.py``'s: the writer's ratings
database is opened read only (``mode=ro``), the rated rewrites are copied
into a scratch database and fingerprinted and grouped there. Nothing is
written to the real database, to ``~/.creativeos`` or to
``~/.writer_platform``; results go to the scratch folder.

For each sampled passage (a distinct rated passage of a grouped source)
both arms build the examples block with the app's own
``rewrite_quality.examples_prompt`` (2 chosen, 1 rejected, as Rephrase
asks), with the passage's own ratings left out (leave-one-out), and then
call the app's own ``RephrasingAgent.rephrase`` with the same text,
surroundings, styles, tone, measured voice and seed. Only the examples
block differs. Each option is scored with ``WriterVoice.fit_score``
against the voice measured around the passage (as the comparison did).

    venv/bin/python scripts/voice_examples_model_trial.py --scratch DIR [--n 16]
        [--dry]            # choose and print the examples, no model
        [--seed 7]

The model is the ``local_model_id`` in ``~/.writer_platform/ai_config.json``
(read only), loaded inside this process through the app's local-model code.
Run it with the app closed and nothing else using the model.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import random
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from src.ai import voice_examples as ve  # noqa: E402
from src.ai import voice_fingerprint as vf  # noqa: E402
from src.ai import voice_groups as vg  # noqa: E402
from src.data import voice_groups_store as vgs  # noqa: E402
from voice_examples_compare import copy_ratings  # noqa: E402

REAL_CHOOSE = ve.choose
STYLE_FALLBACK = ("clearer", "concise")


def _norm(s: str) -> str:
    return " ".join((s or "").split())


def arm_choose(state, leave_out: str):
    """``voice_examples.choose`` for one arm, leaving out ``leave_out``'s
    own ratings (asks for extra, then trims back to what was asked)."""
    def choose(passage, project_path="", *, chosen=2, rejected=1, **kw):
        kw["state"] = state
        got = REAL_CHOOSE(passage, project_path, chosen=chosen + 6, rejected=rejected + 4, **kw)
        keep = lambda rows, n: [r for r in rows if _norm(r["source_text"]) != leave_out][:n]  # noqa: E731
        return dataclasses.replace(got, chosen=keep(got.chosen, chosen),
                                   rejected=keep(got.rejected, rejected))
    return choose


def examples_for(q, db, state):
    from src.ai.rewrite_quality import examples_prompt
    picked = {}

    def spy(*a, **k):
        res = arm_choose(state, _norm(q["source_text"]))(*a, **k)
        picked["choice"] = res
        return res
    ve.choose = spy
    try:
        text = examples_prompt(q["source_text"], q["project_path"] or "", db=db,
                               before=q["surrounding_before"] or "",
                               after=q["surrounding_after"] or "",
                               character_name=q["character_name"] or "")
    finally:
        ve.choose = REAL_CHOOSE
    return text, picked.get("choice")


def styles_for(q):
    from src.ai.rephrasing_agent import RephraseStyle
    names = [s.value for s in RephraseStyle]
    first = (q.get("style") or "").lower()
    out = [first] if first in names else []
    out += [s for s in STYLE_FALLBACK if s not in out]
    return [RephraseStyle(s) for s in out[:2]]


def others_running() -> str:
    found = []
    for pat in ("main.py", "mlx"):
        r = subprocess.run(["pgrep", "-fl", pat], capture_output=True, text=True)
        for line in r.stdout.splitlines():
            if str(Path(__file__).name) not in line and "pgrep" not in line:
                found.append(line)
    return "\n".join(found)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=str(Path.home() / ".creativeos" / "rephrase_history.db"))
    ap.add_argument("--scratch", required=True)
    ap.add_argument("--n", type=int, default=16)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--noise", action="store_true",
                    help="also run today's examples again with another seed (arm today2): "
                         "how much voice fit moves by chance alone")
    a = ap.parse_args()
    scratch = Path(a.scratch)
    scratch.mkdir(parents=True, exist_ok=True)
    for old in scratch.glob("ratings_copy.db*"):     # a fresh copy each run
        old.unlink()
    db = copy_ratings(Path(a.db), scratch)
    fp_rows = vgs.read_rows(db)
    state = vg.regroup(fp_rows)
    member = vg.membership(fp_rows, state)
    groups = state["groups"]
    print(f"{len(fp_rows)} fingerprinted ratings, {len(groups)} group(s)")
    every = {int(r["id"]): dict(r) for r in db._conn().execute("SELECT * FROM rephrases")}

    queries, seen = [], set()
    for i in sorted(member):
        g = member[i]
        if g == vg.UNSORTED:
            continue
        r = every[i]
        if len(r["source_text"] or "") > 900 or len(_norm(r["source_text"]).split()) < 8:
            continue
        key = (r["project_path"], _norm(r["source_text"]))
        if key not in seen:
            seen.add(key)
            queries.append(dict(r, group=g))

    # Both arms' examples for every passage; sample those where they differ
    # (where V.4 can make any difference), balanced across groups.
    today_state = vg.empty_state()
    plans = []
    for q in queries:
        t_text, t_pick = examples_for(q, db, today_state)
        v_text, v_pick = examples_for(q, db, state)
        ids = lambda p: [int(r["id"]) for r in (p.chosen + p.rejected)] if p else []  # noqa: E731
        plans.append(dict(q=q, arms={"today": (t_text, ids(t_pick)), "v4": (v_text, ids(v_pick))},
                          differ=ids(t_pick) != ids(v_pick)))
    differ = [p for p in plans if p["differ"]]
    print(f"{len(queries)} grouped passages; examples differ for {len(differ)}")
    rng = random.Random(a.seed)
    by_group = {}
    for p in differ:
        by_group.setdefault(p["q"]["group"], []).append(p)
    for v in by_group.values():
        rng.shuffle(v)
    sample = []
    while len(sample) < a.n and any(by_group.values()):
        for g in sorted(by_group):
            if by_group[g] and len(sample) < a.n:
                sample.append(by_group[g].pop())
    for p in sample:
        for arm, (_, ids) in p["arms"].items():
            p.setdefault("own", {})[arm] = sum(member.get(i) == p["q"]["group"] for i in ids)
            p.setdefault("count", {})[arm] = len(ids)
    print(f"sample: {len(sample)} passages "
          f"({', '.join(f'{g}: {sum(p['q']['group'] == g for p in sample)}' for g in sorted(groups))})")
    (scratch / "plan.json").write_text(json.dumps([
        dict(id=p["q"]["id"], group=p["q"]["group"], own=p["own"], count=p["count"],
             examples={k: v[0] for k, v in p["arms"].items()}) for p in sample], indent=1))
    if a.dry:
        for p in sample:
            print(p["q"]["id"], p["q"]["group"], p["own"], p["count"])
        return 0

    busy = others_running()
    if busy:
        print("Something else is using the app or the model; not loading it:\n" + busy)
        return 2

    import mlx.core as mx
    from src.ai.rephrasing_agent import RephraseTone, RephrasingAgent
    from src.ai.writer_voice import analyze_writer_voice
    cfg = json.loads((Path.home() / ".writer_platform" / "ai_config.json").read_text())
    agent = RephrasingAgent(project=None, use_local_model=True, local_model_id=cfg["local_model_id"])
    out_path = scratch / "results.jsonl"
    done = set()
    if out_path.exists():
        for line in out_path.read_text().splitlines():
            d = json.loads(line)
            done.add((d["id"], d["arm"]))
    for k, p in enumerate(sample, 1):
        q = p["q"]
        voice = analyze_writer_voice(vf.rating_text(q["surrounding_before"] or "", q["source_text"],
                                                    q["surrounding_after"] or ""))
        for arm in ("today", "v4") + (("today2",) if a.noise else ()):
            if (q["id"], arm) in done:
                continue
            mx.random.seed(a.seed + int(q["id"]) + (1000 if arm == "today2" else 0))
            t0 = time.time()
            try:
                res = agent.rephrase(text=q["source_text"], styles=styles_for(q),
                                     tones=[RephraseTone.NEUTRAL],
                                     surrounding_before=q["surrounding_before"] or "",
                                     surrounding_after=q["surrounding_after"] or "",
                                     writer_voice=voice, examples_note=p["arms"][arm.rstrip("2")][0])
                options = [o.text for o in res.options]
            except Exception as e:  # noqa: BLE001 — record and go on
                print(f"[trial] {q['id']} {arm} failed: {e}")
                options = []
            fits = [voice.fit_score(t) for t in options]
            rec = dict(id=q["id"], group=q["group"], arm=arm, seconds=round(time.time() - t0, 1),
                       own=p["own"][arm.rstrip("2")], count=p["count"][arm.rstrip("2")], source=q["source_text"],
                       options=options, fits=fits)
            with out_path.open("a") as f:
                f.write(json.dumps(rec) + "\n")
            print(f"[trial] {k}/{len(sample)} {q['id']} {arm}: {rec['seconds']}s fits={fits}")
    summarise(out_path)
    return 0


def summarise(out_path: Path) -> None:
    import numpy as np
    recs = [json.loads(x) for x in out_path.read_text().splitlines()]
    print("\n| arm | passages | rewrites | mean voice fit | examples from the passage's group |")
    print("|---|---|---|---|---|")
    for arm in ("today", "v4", "today2"):
        rs = [r for r in recs if r["arm"] == arm]
        fits = [f for r in rs for f in r["fits"][:2] if f is not None]
        own = sum(r["own"] for r in rs)
        cnt = sum(r["count"] for r in rs)
        print(f"| {arm} | {len(rs)} | {len(fits)} | {np.mean(fits) if fits else float('nan'):.3f} | "
              f"{own}/{cnt} ({own / max(cnt, 1):.0%}) |")
    pairs = {}
    for r in recs:
        f = [x for x in r["fits"][:2] if x is not None]
        if f:
            pairs.setdefault(r["id"], {})[r["arm"]] = float(np.mean(f))
    d = [v["v4"] - v["today"] for v in pairs.values() if "v4" in v and "today" in v]
    noise = [v["today2"] - v["today"] for v in pairs.values() if "today2" in v and "today" in v]
    if noise:
        print(f"chance alone (today run twice, another seed): mean |difference| "
              f"{np.mean(np.abs(noise)):.3f}, mean difference {np.mean(noise):+.3f}")
    if d:
        print(f"V.4 against today: mean |difference| {np.mean(np.abs(d)):.3f}")
        print(f"\npaired passages: {len(d)}; V.4 better {sum(x > 0.005 for x in d)}, "
              f"same {sum(abs(x) <= 0.005 for x in d)}, worse {sum(x < -0.005 for x in d)}; "
              f"mean difference {np.mean(d):+.3f}")


if __name__ == "__main__":
    raise SystemExit(main())
