"""Safety check for a real project: does it open, save and reopen with
nothing lost?

    venv/bin/python scripts/check_project_safety.py "/path/to/Book.writerproj"

The project is never written to. Its text and data files (not audio, video
or images) are copied to a temporary folder and everything runs on the copy.
The original is hashed before and after to prove it was not touched.

Only names, counts and checksums are printed — never the writing itself,
and nothing is sent to a model.

To watch the app's own stores (settings, ratings, trained-model lists) across
a change, record them before and compare after:

    venv/bin/python scripts/check_project_safety.py --stores-record before.json
    ...make the change, run the app...
    venv/bin/python scripts/check_project_safety.py --stores-compare before.json

The comparison fails if a store disappears, a setting is removed, or a
database table has fewer rows. Values are never printed.

Exit code 0 = safe, 1 = something would be lost or changed.
"""

from __future__ import annotations

import contextlib
import hashlib
import io
import json
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Tuple

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Large media the project model never reads; left out of the copy.
SKIP_SUFFIXES = {".wav", ".mp3", ".mp4", ".mov", ".m4a", ".png", ".jpg", ".jpeg", ".gif",
                 ".webp", ".docx", ".pdf", ".epub", ".zip", ".tmp", ".safetensors", ".bin"}
SKIP_DIRS = {"_checkpoints", "images", "generated_images", "__pycache__"}


def _wanted(path: Path, root: Path) -> bool:
    rel = path.relative_to(root)
    if any(part in SKIP_DIRS or part.startswith("_SNAPSHOT") or part.endswith("_video_studio")
           for part in rel.parts[:-1]):
        return False
    return path.suffix.lower() not in SKIP_SUFFIXES and not path.name.startswith("~")


def snapshot(root: Path) -> Dict[str, Tuple[int, str]]:
    """relative path → (size, sha1) for every text/data file under root."""
    out = {}
    for p in sorted(root.rglob("*")):
        if p.is_file() and _wanted(p, root):
            data = p.read_bytes()
            out[str(p.relative_to(root))] = (len(data), hashlib.sha1(data).hexdigest())
    return out


def copy_project(src_dir: Path, dest_dir: Path) -> int:
    n = 0
    for p in src_dir.rglob("*"):
        if p.is_file() and _wanted(p, src_dir):
            target = dest_dir / p.relative_to(src_dir)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(p, target)
            n += 1
    return n


def _h(value: Any) -> str:
    return hashlib.sha1(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()[:12]


def describe(project) -> Dict[str, Any]:
    """Everything a writer created, as counts and checksums."""
    dump = project.model_dump(mode="json")
    out: Dict[str, Any] = {"manuscripts": {}}
    for scope, ms in project.iter_manuscripts():
        chapters = {}
        for ch in ms.chapters:
            chapters[ch.id] = {
                "number": ch.number, "title": ch.title,
                "text": hashlib.sha1((ch.content or "").encode()).hexdigest()[:12],
                "words": len((ch.content or "").split()),
                "revisions": [r.revision_number for r in ch.revisions],
                "active_revision": ch.active_revision_number,
                "annotations": len(ch.annotations),
                "planning": _h(ch.planning.model_dump(mode="json")),
            }
        out["manuscripts"][scope or "main"] = chapters
    skip = {"manuscript", "subprojects", "updated_at", "project_path", "schema_version"}
    out["sections"] = {k: _h(v) for k, v in dump.items() if k not in skip}
    out["subprojects"] = [sp.get("name") for sp in dump.get("subprojects", [])]
    return out


def _keys(obj: Any, prefix: str = "", depth: int = 0) -> set:
    """Field names in a project file (structure only, to spot dropped fields)."""
    found = set()
    if isinstance(obj, dict) and depth < 4:
        for k, v in obj.items():
            found.add(f"{prefix}{k}")
            found |= _keys(v, f"{prefix}{k}.", depth + 1)
    elif isinstance(obj, list) and obj and depth < 4:
        found |= _keys(obj[0], f"{prefix}[].", depth + 1)
    return found


def diff_snapshots(before, after) -> Dict[str, List[str]]:
    return {
        "deleted": sorted(set(before) - set(after)),
        "added": sorted(set(after) - set(before)),
        "changed": sorted(k for k in before if k in after and before[k][1] != after[k][1]),
        "shrunk": sorted(k for k in before if k in after and after[k][0] < before[k][0]),
    }


def check(project_file: Path) -> bool:
    from src.models.project import WriterProject

    src_dir = project_file.parent
    problems: List[str] = []
    notes: List[str] = []

    print(f"Project: {project_file.name}")
    original_before = snapshot(src_dir)
    print(f"  {len(original_before)} text and data files in the original (media not counted)")

    with tempfile.TemporaryDirectory(prefix="project_safety_") as tmp:
        work = Path(tmp) / "copy"
        copy_project(src_dir, work)
        copy_file = work / project_file.name
        raw_before = json.loads(copy_file.read_text(encoding="utf-8"))
        at_copy = snapshot(work)

        # 1. Open.
        log = io.StringIO()
        with contextlib.redirect_stdout(log):
            project = WriterProject.load_project(str(copy_file))
        after_open = snapshot(work)
        d = diff_snapshots(at_copy, after_open)
        if d["deleted"]:
            problems.append(f"opening deleted {len(d['deleted'])} file(s): {d['deleted'][:5]}")
        if d["changed"] or d["added"]:
            notes.append(f"opening repaired or migrated the project "
                         f"({len(d['changed'])} file(s) rewritten, {len(d['added'])} added)")
        first = describe(project)
        total_ch = sum(len(c) for c in first["manuscripts"].values())
        total_words = sum(ch["words"] for c in first["manuscripts"].values() for ch in c.values())
        print(f"  opened: {len(first['manuscripts'])} manuscript(s), {total_ch} chapters, "
              f"{total_words:,} words, {len(project.characters)} characters")
        empty = [f"{scope}/{ch['number']}" for scope, c in first["manuscripts"].items()
                 for ch in c.values() if ch["words"] == 0]
        if empty:
            notes.append(f"{len(empty)} chapter(s) have no text: {empty[:8]}")

        # 2. Save with no changes.
        with contextlib.redirect_stdout(log):
            project.save_project(str(copy_file))
        after_save = snapshot(work)
        d = diff_snapshots(after_open, after_save)
        if d["deleted"]:
            problems.append(f"saving deleted {len(d['deleted'])} file(s): {d['deleted'][:5]}")
        prose_changed = [k for k in d["changed"] if "revision_" in k]
        if prose_changed:
            problems.append(f"saving without edits changed {len(prose_changed)} chapter file(s): "
                            f"{prose_changed[:5]}")
        shrunk = [k for k in d["shrunk"] if k.endswith(".md")]
        if shrunk:
            problems.append(f"saving made {len(shrunk)} text file(s) smaller: {shrunk[:5]}")

        # 3. Field names kept.
        raw_after = json.loads(copy_file.read_text(encoding="utf-8"))
        lost = sorted(_keys(raw_before) - _keys(raw_after))
        if lost:
            problems.append(f"saving dropped {len(lost)} field(s) from the project file: {lost[:8]}")

        # 4. Open again and compare.
        with contextlib.redirect_stdout(log):
            again = WriterProject.load_project(str(copy_file))
        second = describe(again)
        for scope, chapters in first["manuscripts"].items():
            other = second["manuscripts"].get(scope)
            if other is None:
                problems.append(f"manuscript '{scope}' is missing after save and reopen")
                continue
            for cid, ch in chapters.items():
                if cid not in other:
                    problems.append(f"chapter {ch['number']} of '{scope}' is missing after reopen")
                elif other[cid] != ch:
                    what = [k for k in ch if other[cid].get(k) != ch[k]]
                    problems.append(f"chapter {ch['number']} of '{scope}' differs after reopen: {what}")
        for name, digest in first["sections"].items():
            if second["sections"].get(name) != digest:
                problems.append(f"section '{name}' differs after save and reopen")
        if first["subprojects"] != second["subprojects"]:
            problems.append("the list of novellas differs after save and reopen")

        # 5. Every revision file is still there with its text.
        for scope, ms in again.iter_manuscripts():
            for ch in ms.chapters:
                for rev in ch.revisions:
                    if rev.file_path and rev.file_path in at_copy:
                        now = after_save.get(rev.file_path)
                        if now is None:
                            problems.append(f"revision file gone: {rev.file_path}")
                        elif now[1] != at_copy[rev.file_path][1] and rev.file_path not in prose_changed:
                            problems.append(f"revision file changed: {rev.file_path}")

        # 6. Files kept beside the project still load.
        again.project_path = str(copy_file)
        for label, loader in (("Companion state", _load_companion),
                              ("critique history", _load_critique_history)):
            try:
                loader(again)
            except Exception as e:
                problems.append(f"{label} did not load: {e}")

        out = log.getvalue().strip()
        if out:
            notes.append("messages while loading and saving: "
                         + " | ".join(line.strip() for line in out.splitlines()[:6]))

    # 7. The original was not touched.
    if snapshot(src_dir) != original_before:
        problems.append("THE ORIGINAL PROJECT CHANGED DURING THE CHECK")
    else:
        print("  original untouched")

    for n in notes:
        print(f"  note: {n}")
    for p in problems:
        print(f"  PROBLEM: {p}")
    print("  RESULT: " + ("safe — opens, saves and reopens with nothing lost"
                          if not problems else f"{len(problems)} problem(s)"))
    return not problems


def _load_companion(project):
    from src.data import companion_state
    companion_state.load(project)


def _load_critique_history(project):
    from src.data import critique_history
    critique_history.load(project)


STORE_DIRS = (Path.home() / ".creativeos", Path.home() / ".writer_platform")


def stores() -> Dict[str, Any]:
    """Shape of every settings file and database the app keeps for the user:
    setting names and row counts only."""
    import sqlite3
    out: Dict[str, Any] = {}
    for base in STORE_DIRS:
        if not base.is_dir():
            continue
        for p in sorted(base.glob("*")) + sorted((base / "companion").glob("*.json")):
            if not p.is_file():
                continue
            name = str(p).replace(str(Path.home()), "~")
            if p.suffix == ".json":
                try:
                    data = json.loads(p.read_text(encoding="utf-8"))
                    out[name] = {"kind": "json", "keys": sorted(_keys(data)),
                                 "items": len(data) if isinstance(data, (list, dict)) else 1}
                except Exception as e:
                    out[name] = {"kind": "unreadable", "error": str(e)[:80]}
            elif p.suffix == ".db":
                try:
                    con = sqlite3.connect(f"file:{p}?mode=ro", uri=True)
                    tables = [r[0] for r in con.execute(
                        "select name from sqlite_master where type='table'")]
                    out[name] = {"kind": "db", "rows": {
                        t: con.execute(f'select count(*) from "{t}"').fetchone()[0]
                        for t in tables if not t.startswith("sqlite_")}}
                    con.close()
                except Exception as e:
                    out[name] = {"kind": "unreadable", "error": str(e)[:80]}
    return out


def compare_stores(before: Dict[str, Any], after: Dict[str, Any]) -> List[str]:
    problems = []
    for name, was in before.items():
        now = after.get(name)
        if now is None:
            problems.append(f"{name} is gone")
        elif now["kind"] == "unreadable" and was["kind"] != "unreadable":
            problems.append(f"{name} can no longer be read")
        elif was["kind"] == "json" and now["kind"] == "json":
            lost = sorted(set(was["keys"]) - set(now["keys"]))
            if lost:
                problems.append(f"{name} lost {len(lost)} setting(s): {lost[:6]}")
            if now["items"] < was["items"]:
                problems.append(f"{name} has fewer entries ({was['items']} → {now['items']})")
        elif was["kind"] == "db" and now["kind"] == "db":
            for table, n in was["rows"].items():
                m = now["rows"].get(table)
                if m is None:
                    problems.append(f"{name}: table {table} is gone")
                elif m < n:
                    problems.append(f"{name}: table {table} has fewer rows ({n} → {m})")
    return problems


def main(argv: List[str]) -> int:
    if not argv:
        print(__doc__)
        return 1
    if argv[0] == "--stores-record" and len(argv) == 2:
        data = stores()
        Path(argv[1]).write_text(json.dumps(data, indent=1), encoding="utf-8")
        print(f"Recorded {len(data)} store(s) to {argv[1]}")
        return 0
    if argv[0] == "--stores-compare" and len(argv) == 2:
        problems = compare_stores(json.loads(Path(argv[1]).read_text(encoding="utf-8")), stores())
        for p in problems:
            print(f"  PROBLEM: {p}")
        print("RESULT: " + ("stores intact" if not problems else f"{len(problems)} problem(s)"))
        return 1 if problems else 0
    ok = True
    for arg in argv:
        path = Path(arg).expanduser()
        if not path.is_file():
            print(f"Not found: {path}")
            ok = False
            continue
        ok = check(path) and ok
        print()
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
