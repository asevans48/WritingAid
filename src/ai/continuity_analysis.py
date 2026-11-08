"""Continuity across a project's manuscripts (main + novellas).

Novellas share the project's characters and world, so the same Mara,
the same Ash Wardens, the same Greywater turn up in several books. This
report checks they stay consistent from book to book.

Deterministic findings (no model needed):
  * presence map — which characters and world elements appear in which
    manuscripts (and from which chapter);
  * possible resurrections — a character described as dead in an
    earlier book who appears in a later one (tab order = story order);
  * names shared by several books that have no character / world record.

Model findings (small focused prompts, so local models cope): for each
element shared by two or more books, its record + its passages from each
book → consistent / conflict / explained change; then one story-level
pass over per-book digests → timeline problems, dropped threads,
contradictions, recommendations.

Produces a ``ReportSection`` (``ReportType.CONTINUITY``) so the Critique
tab renders, rates and saves it like any other report.
"""

from __future__ import annotations

import re
from typing import Any, Callable, Dict, List, Optional, Tuple

from src.ai.canon_index import (
    _name_variants, character_name_variants, collect_world_entities, find_mentions,
    find_unknown_proper_nouns, format_character_profile, parse_tagged_lines,
    passages_mentioning,
)

_LIFE_DEATH_RX = re.compile(
    r"\b(?:dead|death|died|dies|die|drown\w*|killed|alive|lives|living|survive\w*|"
    r"vitality|resurrect\w*|returns?|presence|appears)\b", re.I)
_DEATH_RX = (r"\b(?:died|dies|dead|killed|slain|murdered|drowned|executed|was buried|"
             r"funeral|grave|corpse|body was found|passed away|never woke)\b")


def manuscripts_with_text(project: Any) -> List[Dict[str, Any]]:
    """[{scope, label, chapters: [(chapter_id, title, text)], text}] in tab
    order (main first), skipping manuscripts with no prose."""
    out = []
    for scope, ms in project.iter_manuscripts():
        chapters = [(ch.id, ch.title or f"Chapter {ch.number}", ch.content or "")
                    for ch in ms.chapters if (ch.content or "").strip()]
        if not chapters:
            continue
        out.append({"scope": scope, "label": project.scope_label(scope),
                    "chapters": chapters,
                    "text": "\n\n".join(t for _, _, t in chapters)})
    return out


def has_cross_manuscript_content(project: Any) -> bool:
    return bool(getattr(project, "subprojects", None)) and len(manuscripts_with_text(project)) >= 2


_STOPWORDS = set("""a an the and or but of to in on at by for with from as is was were be been
are it its he she they him her his their them this that these those vs versus book books
while which who whom into than then there here not no so""".split())


def _content_words(text: str, ignore: set = frozenset()) -> set:
    return {w for w in re.findall(r"[a-z']+", (text or "").lower())
            if len(w) > 2 and w not in _STOPWORDS and w not in ignore}


def _dedupe(items: List[str], existing: List[str], overlap: float = 0.45,
            ignore: set = frozenset()) -> List[str]:
    """Drop items that mostly repeat one already kept (the per-element
    check, the story-level pass and the deterministic scan often report
    the same break in different words). ``ignore`` — words every finding
    shares (book titles, names) — don't count as overlap."""
    kept: List[str] = []
    seen = [_content_words(e, ignore) for e in existing]
    for item in items:
        words = _content_words(item, ignore)
        if words and any(len(words & s) / max(1, min(len(words), len(s))) >= overlap
                         for s in seen if s):
            continue
        kept.append(item)
        seen.append(words)
    return kept


class ContinuityAnalyzer:
    MAX_ENTITIES = 10
    LOCAL_MAX_ENTITIES = 6
    PASSAGE_WORDS = 160

    _SYSTEM = ("You are a series continuity editor. Several books share one fictional "
               "world. Compare how the same character or element is presented in each "
               "book against its record and each other. Be specific and brief; quote the "
               "passages. Follow the answer format exactly.")

    def __init__(self, project: Any, llm: Any = None,
                 progress_cb: Optional[Callable[[str], None]] = None):
        self.project = project
        self.llm = llm
        self.progress = progress_cb or (lambda m: None)
        try:
            from src.ai.chapter_analysis_agent import is_local_llm
            self.compact = bool(llm) and is_local_llm(llm)
        except Exception:
            self.compact = False

    # ── public ──────────────────────────────────────────────────────

    def run(self):
        from src.ai.chapter_analysis_agent import ReportSection, ReportType
        section = ReportSection(report_type=ReportType.CONTINUITY,
                                chapter_title="Across novellas", chapter_index=-1)
        books = manuscripts_with_text(self.project)
        self._books = books
        section.metrics = {"manuscripts_compared": len(books)}
        if len(books) < 2:
            section.minor_issues.append(
                "Fewer than two manuscripts have text, so there's nothing to compare yet.")
            section.summary = "Continuity: needs text in at least two manuscripts."
            section.findings = list(section.minor_issues)
            return section
        self._deterministic(section)
        if self.llm is not None:
            self._narrate(section)
        section.findings = section.strengths + section.major_issues + section.minor_issues
        n_conf = sum(1 for i in section.major_issues)
        section.summary = (
            f"Continuity across {len(books)} manuscripts "
            f"({', '.join(b['label'] for b in books)}): "
            f"{section.metrics.get('shared_elements', 0)} shared character(s)/element(s), "
            f"{n_conf} possible conflict(s).")
        return section

    # ── deterministic ───────────────────────────────────────────────

    def _deterministic(self, section) -> None:
        books = self._books
        characters = list(getattr(self.project, "characters", None) or [])
        entities = collect_world_entities(getattr(self.project, "worldbuilding", None))
        names: Dict[str, List[str]] = dict(character_name_variants(characters))
        kind: Dict[str, Any] = {c.name: c for c in characters}
        for e in entities:
            if e.name not in names:
                names[e.name] = [e.name]
                kind[e.name] = e

        presence: Dict[str, List[Tuple[int, int, str]]] = {}   # name → [(book, count, first ch)]
        for bi, book in enumerate(books):
            found = find_mentions(book["text"], names)
            for name, info in found.items():
                first = next((title for _, title, t in book["chapters"]
                              if find_mentions(t, {name: names[name]})), "")
                presence.setdefault(name, []).append((bi, info["count"], first))
        shared = {n: p for n, p in presence.items() if len(p) >= 2}
        self._shared = sorted(shared, key=lambda n: (-len(shared[n]), -sum(c for _, c, _ in shared[n])))
        self._names, self._kind = names, kind
        section.metrics.update({
            "shared_elements": len(shared),
            "characters_shared": sum(1 for n in shared if n in {c.name for c in characters}),
        })
        if shared:
            section.extra_lists["Shared across manuscripts"] = [
                f"{n} — " + ", ".join(f"{books[bi]['label']} ({c}×, from {first})"
                                      for bi, c, first in shared[n])
                for n in self._shared[:25]]
        else:
            section.minor_issues.append(
                "No recorded character or world element appears in more than one manuscript.")

        # Possible resurrections: dead in an earlier book, present later.
        self._resurrected = set()
        for c in characters:
            p = presence.get(c.name) or []
            if len(p) < 2:
                continue
            for bi, _, _ in p:
                hit = self._death_mention(books[bi], c.name)
                if not hit:
                    continue
                later = [(bj, cnt) for bj, cnt, _ in p if bj > bi and cnt >= 2]
                if later:
                    bj = later[0][0]
                    self._resurrected.add(c.name)
                    section.major_issues.append(
                        f"{c.name} — described as dead in {books[bi]['label']} ({hit[0]}: "
                        f"\"{hit[1]}\") but appears in {books[bj]['label']}. Intended "
                        f"(flashback, earlier timeline)? Otherwise a continuity break.")
                break

        # Names several books share that have no record.
        known = list(names) + [c.name for c in characters]
        per_book = [{n for n, _, _ in find_unknown_proper_nouns(b["text"], known, limit=40)}
                    for b in books]
        counts: Dict[str, int] = {}
        for s in per_book:
            for n in s:
                counts[n] = counts.get(n, 0) + 1
        unrecorded = sorted((n for n, k in counts.items() if k >= 2), key=lambda n: -counts[n])
        if unrecorded:
            section.extra_lists["Shared names with no record"] = [
                f"{n} — in " + ", ".join(b["label"] for b, s in zip(books, per_book) if n in s)
                for n in unrecorded[:15]]
            section.suggestions.append(
                "Add recurring unrecorded names to Characters / Worldbuilding so every "
                "book draws on the same record: " + ", ".join(unrecorded[:6]) + ".")

    @staticmethod
    def _death_mention(book, name) -> Optional[Tuple[str, str]]:
        variants = [re.escape(v) for v in _name_variants(name)]
        rx = re.compile(r"[^.!?\n]*\b(?:" + "|".join(variants) + r")\b[^.!?\n]{0,80}?" + _DEATH_RX
                        + r"[^.!?\n]*[.!?]?", re.I)
        for _cid, title, text in book["chapters"]:
            m = rx.search(text)
            if m:
                return title, m.group(0).strip()[:160]
        return None

    # ── model ───────────────────────────────────────────────────────

    def _ask(self, section, label: str, prompt: str, max_tokens: int) -> str:
        from src.ai.chapter_analysis_agent import _first_answer
        try:
            try:
                out = self.llm.generate_text(prompt, self._SYSTEM, max_tokens=max_tokens,
                                             temperature=0.3 if self.compact else 0.4)
            except TypeError:
                out = self.llm.generate_text(prompt, self._SYSTEM)
        except Exception as e:
            section.minor_issues.append(f"(model call failed — {label}: {e})")
            return ""
        out = (out or "").strip()
        if out.startswith("Error generating text:"):
            section.minor_issues.append(f"(model call failed — {label}: "
                                        f"{out[len('Error generating text:'):].strip()[:120]})")
            return ""
        out = _first_answer(out)
        section.calls.append({"id": f"c{len(section.calls) + 1}", "label": label,
                              "kind": "focused" if self.compact else "report",
                              "system": self._SYSTEM, "prompt": prompt, "output": out})
        return out

    def _narrate(self, section) -> None:
        from src.ai.chapter_analysis_agent import _clean_items, _keep_named
        books = self._books
        limit = self.LOCAL_MAX_ENTITIES if self.compact else self.MAX_ENTITIES
        consistent, conflicts, evolves, blocks = [], [], [], []
        for name in self._shared[:limit]:
            self.progress(f"  continuity: {name}…")
            record = self._kind.get(name)
            if hasattr(record, "character_type"):
                record_text = format_character_profile(record, max_field=160)
            else:
                record_text = f"{getattr(record, 'label', name)}: {getattr(record, 'summary', '') or '(no description)'}"
            parts = []
            for b in books:
                ev = passages_mentioning(b["text"], self._names[name], self.PASSAGE_WORDS)
                if ev:
                    parts.append(f"[BOOK: {b['label']}]\n{ev}")
            prompt = (
                f"RECORD (the author's canon):\n{record_text}\n\n"
                f"HOW {name.upper()} APPEARS IN EACH BOOK (books in story order):\n\n"
                + "\n\n".join(parts) +
                "\n\nDoes the presentation stay consistent from book to book (facts, "
                "status, relationships, abilities, appearance, allegiance)? Reply with ONLY "
                "lines in this format:\n"
                f"[CONSISTENT] {name} — <what stays consistent, with a short quote>\n"
                f"[CONFLICT] {name} — <book A> vs <book B>: <the contradiction, quoting both>\n"
                f"[EVOLVES] {name} — <a change between books that the text explains>\n"
                "Write [CONFLICT] none if there is no contradiction.\n\n"
                "FORMAT EXAMPLE (made-up, not from these books):\n"
                "[CONSISTENT] Pell Quorry — still fears heights in both books (\"he kept "
                "from the parapet\")\n"
                "[CONFLICT] Pell Quorry — Book One vs Book Two: \"his left hand was lost at "
                "Varn\" vs \"he drew with his left hand\"\n\n"
                f"Answer for {name} only:")
            # parse_tagged_lines normalises synonyms: CONSISTENT → ON TRACK,
            # CONFLICT / CONTRADICTION → DIFFERS.
            tags = parse_tagged_lines(self._ask(section, name, prompt, 450))
            consistent += _keep_named(_clean_items(tags.get("ON TRACK", [])), [name])
            conflicts += _keep_named(_clean_items(tags.get("DIFFERS", [])), [name])
            evolves += _keep_named(_clean_items(tags.get("EVOLVES", [])), [name])

        # Story-level pass over book digests.
        self.progress("  continuity: timeline & threads across books…")
        digests = []
        for b in books:
            sp = self.project.get_subproject(b["scope"]) if b["scope"] else None
            desc = (getattr(sp, "description", "") or "") if sp else ""
            ms = self.project.get_manuscript_for(b["scope"])
            plan = []
            for ch in ms.chapters:
                d = (getattr(getattr(ch, "planning", None), "description", "") or "").strip()
                plan.append(f"  - {ch.title}" + (f": {d[:160]}" if d else ""))
            words = b["text"].split()
            digests.append(
                f"[BOOK: {b['label']}]" + (f"\nAbout: {desc[:300]}" if desc else "")
                + "\nChapters:\n" + "\n".join(plan[:30])
                + f"\nOpening: {' '.join(words[:120])}\nEnding: {' '.join(words[-150:])}")
        prompt = (
            "These books are set in the same world, in story order:\n\n"
            + "\n\n".join(digests) +
            "\n\nCheck continuity ACROSS the books. Reply with ONLY lines in this format:\n"
            "[TIMELINE] <an order / timing problem between books>\n"
            "[THREAD] <a thread opened in one book and dropped or unresolved later>\n"
            "[CONTRADICTION] <a fact one book states that another contradicts>\n"
            "[RECOMMEND] <one concrete fix, naming the book and chapter>\n"
            "Write a tag followed by none if there's nothing for it.")
        tags = parse_tagged_lines(self._ask(section, "timeline & threads", prompt,
                                            500 if self.compact else 800))
        timeline = _clean_items(tags.get("TIMELINE", []))
        threads = _clean_items(tags.get("THREAD", []))
        contradictions = _clean_items(tags.get("DIFFERS", []))
        recommend = _clean_items(tags.get("RECOMMEND", []))

        section.strengths.extend(consistent)
        ignore = set()
        for text in [b["label"] for b in books] + list(self._names):
            ignore |= _content_words(text)
        # The deterministic scan already reported "dead in book A, alive in
        # book B" for these characters; the model restates it in its own words.
        model_issues = [i for i in conflicts + contradictions + timeline
                        if not any(re.search(rf"\b{re.escape(n)}\b", i) for n in self._resurrected)
                        or not _LIFE_DEATH_RX.search(i)]
        section.major_issues.extend(
            _dedupe(model_issues, section.major_issues, ignore=ignore))
        section.minor_issues.extend(threads)
        section.suggestions.extend(recommend)
        if evolves:
            section.extra_lists["Changes between books (explained)"] = evolves
        if threads:
            section.extra_lists["Open threads across books"] = threads
        for label, items in (("Consistent", consistent), ("Conflicts", conflicts + contradictions),
                             ("Timeline", timeline), ("Open threads", threads),
                             ("Explained changes", evolves), ("Recommendations", recommend)):
            if items:
                blocks.append(f"**{label}:**\n" + "\n".join(f"- {i}" for i in items))
        skipped = self._shared[limit:]
        if skipped:
            section.minor_issues.append(
                f"Checked the {limit} most-shared elements; not checked: "
                + ", ".join(skipped[:8]) + ("…" if len(skipped) > 8 else "") + ".")
        section.narrative = "\n\n".join(blocks)
