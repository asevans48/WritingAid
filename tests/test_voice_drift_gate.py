"""Piece 4.2, voice drift: the proof script (the piece was dropped at its
gate; see the brief's Outcome). The measure behaves as described, and the
script only reads the ratings database and the projects."""

import hashlib
import importlib.util
import random
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _gate():
    spec = importlib.util.spec_from_file_location("voice_drift_gate",
                                                  ROOT / "scripts" / "voice_drift_gate.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_NAMES = ["Mara", "Tobin", "Elsie", "Rook"]
_NOUNS = ["door", "river", "lantern", "field", "road", "window", "wall", "bridge"]


def _long_voice(rng, paragraphs=40):
    """Third person, past, long sentences with dashes and semicolons."""
    out = []
    for _ in range(paragraphs):
        sents = []
        for _ in range(rng.randint(3, 5)):
            n, a, b = rng.choice(_NAMES), rng.choice(_NOUNS), rng.choice(_NOUNS)
            sents.append(f"{n} walked slowly along the {a} toward the old {b}, thinking of the "
                         f"years that had passed since the {a} was built — and of the people who "
                         f"had crossed it; she remembered every one of them, though most had "
                         f"long since gone beyond the {b}.")
        out.append(" ".join(sents))
    return "\n\n".join(out)


def _short_voice(rng, paragraphs=40):
    """First person, present, short sentences, contractions, exclamations."""
    out = []
    for _ in range(paragraphs):
        sents = []
        for _ in range(rng.randint(6, 9)):
            a = rng.choice(_NOUNS)
            sents.append(rng.choice([f"I can't see the {a}.", f"It's cold!", f"I run.",
                                     f"Where's the {a}?", f"I don't stop.", f"I'm late!"]))
        out.append(" ".join(sents))
    return "\n\n".join(out)


def test_passages_are_about_two_hundred_words_at_paragraph_ends():
    g = _gate()
    text = _long_voice(random.Random(1))
    ps = g.passages(text)
    assert ps and all(len(p.split()) >= g.PASSAGE_WORDS // 2 for p in ps)
    assert all(p.split("\n\n")[0] in text for p in ps)


def test_a_chapter_in_another_style_scores_as_drifted_an_untouched_one_does_not():
    g = _gate()
    rng = random.Random(2)
    book = {f"c{i}": g.vectors(_long_voice(rng)) for i in range(5)}
    untouched = g.drift(book["c0"], [v for k, vs in book.items() if k != "c0" for v in vs])
    rewritten = g.drift(g.vectors(_short_voice(rng)),
                        [v for k, vs in book.items() if k != "c0" for v in vs])
    assert untouched is not None and not untouched.flagged
    assert rewritten is not None and rewritten.flagged
    assert rewritten.moves                                  # says what moved, in words


def test_too_little_text_is_not_judged():
    g = _gate()
    assert g.drift(g.vectors("A few words only."), g.vectors(_long_voice(random.Random(3)))) is None


def test_a_change_of_a_few_words_is_never_marked():
    g = _gate()
    rng = random.Random(4)
    text = _long_voice(rng)
    book = g.vectors(text)
    at = text.find("walked slowly")
    assert g.rewrite_drift(text, at, at + len("walked slowly"), "strolled", book) is None


def _bytes(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_the_script_only_reads_the_ratings_and_the_projects(tmp_path, capsys):
    g = _gate()
    rng = random.Random(5)
    project = tmp_path / "Book"
    for i in range(1, 5):
        d = project / "chapters" / f"chapter_{i:03d}"
        d.mkdir(parents=True)
        (d / "revision_001.md").write_text(_long_voice(rng), encoding="utf-8")
    proj_file = project / "Book.writerproj"
    proj_file.write_text("{}", encoding="utf-8")
    db = tmp_path / "rephrase_history.db"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE rephrases (id INTEGER PRIMARY KEY, source_text TEXT, "
                "output_text TEXT, source_type TEXT, style TEXT, notes TEXT, project_path TEXT, "
                "accepted INTEGER, surrounding_before TEXT, surrounding_after TEXT)")
    for _ in range(30):
        con.execute("INSERT INTO rephrases (source_text, output_text, source_type, style, notes, "
                    "project_path, accepted, surrounding_before, surrounding_after) "
                    "VALUES (?, ?, 'rephrase', 'concise/dark', '', ?, 1, ?, ?)",
                    (_long_voice(rng, 1), _short_voice(rng, 1), str(proj_file),
                     _long_voice(rng, 1), _long_voice(rng, 1)))
    con.commit()
    con.close()
    before = {p: _bytes(p) for p in tmp_path.rglob("*") if p.is_file()}
    g.run_writer(str(db), None, random.Random(7))
    after = {p: _bytes(p) for p in tmp_path.rglob("*") if p.is_file()}
    assert after == before                       # nothing written, nothing added
    assert "The writer, untouched" in capsys.readouterr().out
