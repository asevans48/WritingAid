"""Piece 7.2's proof: is the model's tension rating repeatable?

Rates every chapter's scenes twice with ``scene_tension.rate_chapter`` (the
app's own prompt and temperature), with a different seed each run, and
measures how often the two runs agree. Optionally (``--digest``) also
makes each chapter's reverse outline (``chapter_digest.read_chapter``) once,
to show the model's reading of the scenes.

**Copies only.** Point it at copies of the projects. By default it writes
only to ``--out``. ``--save`` also stores the outline (and, when the bar is
met, the first run's tension) in the copy's own readiness file, so the
outline can be looked at in the copy; it refuses to do that to a project
that is not under the scratch folder given by ``--out``'s parent.

    venv/bin/python scripts/tension_repeat_trial.py --out DIR PROJECT.writerproj [...]
        [--digest] [--save] [--max-chapters N]

The model is the app's default (``task_llm.build_default_llm``), or with
``--critique`` the Critique's (``build_critique_llm``), loaded in this process. Run it with the app closed and nothing else using the model.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# The bar (stated in the 7.2 brief's Outcome): tension is shown only if both hold.
BAR_WITHIN_ONE = 0.90      # scenes rated within one point of each other
BAR_KAPPA = 0.60           # quadratic-weighted kappa ("substantial" agreement)
BAR_READABLE = 0.90        # runs the app could read at all (a rating it can't read shows nothing)


def others_running() -> str:
    found = []
    for pat in ("main.py", "mlx"):
        r = subprocess.run(["pgrep", "-fl", pat], capture_output=True, text=True)
        found += [x for x in r.stdout.splitlines() if Path(__file__).name not in x]
    return "\n".join(found)


def manuscripts(project):
    out = []
    try:
        for scope, ms in project.iter_manuscripts():
            if getattr(ms, "chapters", None):
                out.append((scope, ms))
    except Exception:
        if getattr(project.manuscript, "chapters", None):
            out.append((None, project.manuscript))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("projects", nargs="+")
    ap.add_argument("--out", required=True)
    ap.add_argument("--digest", action="store_true")
    ap.add_argument("--save", action="store_true")
    ap.add_argument("--max-chapters", type=int, default=0)
    ap.add_argument("--critique", action="store_true",
                    help="load the Critique's model (task_llm.build_critique_llm, which falls "
                         "back to model_for_plot) instead of the app's default model")
    ap.add_argument("--temperature", type=float, default=None,
                    help="rate at this temperature instead of the app's (a stricter test); "
                         "results go to tension_runs_t<temperature>.jsonl")
    ap.add_argument("--joined", action="store_true",
                    help="also rate pairs of consecutive chapters joined by a scene break "
                         "(two-scene items), to test the prompt on more than one scene")
    a = ap.parse_args()
    out = Path(a.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    root = out.parent
    if a.save:
        for p in a.projects:
            if root not in Path(p).resolve().parents:
                print(f"--save refused: {p} is not under {root} (copies only)")
                return 2
    busy = others_running()
    if busy:
        print("Something else is using the app or the model; not loading it:\n" + busy)
        return 2

    import mlx.core as mx
    from src.ai import chapter_digest, scene_tension
    from src.ai.readiness import Book, text_hash
    from src.ai.task_llm import build_critique_llm, build_default_llm
    from src.models.project import WriterProject
    llm = (build_critique_llm() if a.critique else None) or build_default_llm()
    if llm is None:
        print("No model configured.")
        return 2
    print(f"model: {getattr(llm, 'model', '') or llm}")
    real_generate = llm.generate_text
    last = {"reply": ""}

    def recording(*args, **kw):                  # keep the raw reply, for the record
        last["reply"] = real_generate(*args, **kw) or ""
        return last["reply"]
    llm.generate_text = recording
    temp = scene_tension.TEMPERATURE if a.temperature is None else a.temperature
    results_path = out / ("tension_runs.jsonl" if a.temperature is None
                          else f"tension_runs_t{a.temperature:g}.jsonl")
    print(f"temperature: {temp}")
    done = {}
    if results_path.exists():
        for line in results_path.read_text().splitlines():
            d = json.loads(line)
            done[(d["project"], d["chapter_id"])] = d
    for path in a.projects:
        project = WriterProject.load_project(path)
        for scope, ms in manuscripts(project):
            book = Book(project, scope)
            chapters = book.chapters[:a.max_chapters] if a.max_chapters else book.chapters
            items = [(ch, book.texts.get(ch.id, ""), False) for ch in chapters]
            if a.joined:
                real = [(ch, t) for ch, t, _ in items if len(t.split()) >= 100]
                for (c1, t1), (c2, t2) in zip(real[0::2], real[1::2]):
                    joined = SimpleNamespace(id=f"{c1.id}+{c2.id}",
                                             title=f"{chapter_digest.title_of(c1)} + "
                                                   f"{chapter_digest.title_of(c2)}")
                    items.append((joined, t1.rstrip() + "\n\n* * *\n\n" + t2.lstrip(), True))
            for ch, text, is_joined in items:
                if len(text.split()) < 100:
                    continue
                key = (project.name, ch.id)
                rec = done.get(key)
                if rec is None:
                    rec = dict(project=project.name, scope=scope, chapter_id=ch.id,
                               title=chapter_digest.title_of(ch), words=len(text.split()),
                               text_hash=text_hash(text), joined=is_joined)
                    for run in (1, 2):
                        mx.random.seed(1000 * run + 17)
                        t0 = time.time()
                        try:
                            r = scene_tension.rate_chapter(llm, ch, text, temperature=temp)
                            rec[f"run{run}"] = r["values"]
                            rec[f"raw{run}"] = last["reply"][:2000]
                            rec[f"why{run}"] = r["why"]
                        except Exception as e:  # noqa: BLE001
                            rec[f"run{run}"] = None
                            rec[f"error{run}"] = str(e)
                            rec[f"raw{run}"] = last["reply"][:2000]
                        rec[f"seconds{run}"] = round(time.time() - t0, 1)
                    if a.digest and not is_joined:
                        mx.random.seed(17)
                        t0 = time.time()
                        try:
                            rec["digest"] = chapter_digest.read_chapter(llm, ch, text)
                            rec["digest_raw"] = last["reply"][:4000]
                        except Exception as e:  # noqa: BLE001
                            rec["digest_error"] = str(e)
                        rec["digest_seconds"] = round(time.time() - t0, 1)
                    with results_path.open("a") as f:
                        f.write(json.dumps(rec) + "\n")
                    done[key] = rec
                print(f"[tension] {project.name} / {rec['title']}: {rec.get('run1')} vs "
                      f"{rec.get('run2')} ({rec.get('seconds1')}s, {rec.get('seconds2')}s)")
                if a.save and rec.get("digest"):
                    entry = dict(rec["digest"], text_hash=rec["text_hash"], v=chapter_digest.VERSION)
                    chapter_digest.for_book(book)._save(ch.id, entry)
    passed = summarise(results_path)
    if a.save and passed and a.temperature is None:
        for path in a.projects:
            project = WriterProject.load_project(path)
            for scope, ms in manuscripts(project):
                book = Book(project, scope)
                for ch in book.chapters:
                    rec = done.get((project.name, ch.id))
                    if rec and rec.get("run1") and rec["text_hash"] == text_hash(book.texts[ch.id]):
                        scene_tension.save(project, scope, ch.id, dict(
                            values=rec["run1"], why=rec.get("why1", []), scenes=len(rec["run1"]),
                            model="trial", text_hash=rec["text_hash"], v=scene_tension.VERSION))
    return 0


def summarise(results_path: Path) -> bool:
    from src.ai.scene_tension import agreement
    recs = [json.loads(x) for x in results_path.read_text().splitlines()]
    a_all, b_all, rows = [], [], []
    for r in recs:
        if r.get("run1") and r.get("run2"):
            a_all += r["run1"]
            b_all += r["run2"]
            rows.append(r)
    print("\n| project | chapters | scenes | exact | within one | weighted kappa |")
    print("|---|---|---|---|---|---|")
    projects = sorted({r["project"] for r in rows})
    groups = [(p, lambda r, p=p: r["project"] == p and not r.get("joined")) for p in projects]
    groups += [("joined pairs (2 scenes each)", lambda r: bool(r.get("joined"))),
               ("all", lambda r: True)]
    for p, keep in groups:
        rs = [r for r in rows if keep(r)]
        a = [v for r in rs for v in r["run1"]]
        b = [v for r in rs for v in r["run2"]]
        g = agreement(a, b)
        print(f"| {p} | {len(rs)} | {g['n']} | {g['exact']:.0%} | {g['within_one']:.0%} | "
              f"{g['kappa']:.2f} |")
    g = agreement(a_all, b_all)
    spread = sorted({v for v in a_all + b_all if v is not None})
    failed = [r["title"] for r in recs if not (r.get("run1") and r.get("run2"))]
    readable = sum(bool(r.get(k)) for r in recs for k in ("run1", "run2")) / max(2 * len(recs), 1)
    passed = (readable >= BAR_READABLE and g["within_one"] >= BAR_WITHIN_ONE
              and g["kappa"] >= BAR_KAPPA)
    print(f"\nratings used: {spread}; chapters with a failed run: {failed or 'none'}")
    print(f"runs the app could read: {readable:.0%}")
    print(f"bar: readable ≥ {BAR_READABLE:.0%}, within one ≥ {BAR_WITHIN_ONE:.0%} and weighted "
          f"kappa ≥ {BAR_KAPPA}: {'MET' if passed else 'NOT MET'}")
    return passed


if __name__ == "__main__":
    raise SystemExit(main())
