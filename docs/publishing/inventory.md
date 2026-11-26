# What already exists

Confirmed in piece 0.1 by reading each module and running every check that
needs no model on a generated 4,000-word chapter (74 paragraphs, three named
characters, dialogue). Times are from that run on the writer's Mac and are
rough guides, not promises. "One model call" means the time depends on the
model: seconds on a cloud model, longer on a local one.

Later pieces rely on this file. A function named here exists with the
signature shown.

## Checks and the functions to call

| Need | Call | Returns | Model? | Time on a chapter |
|---|---|---|---|---|
| **Style checks** (eleven kinds: `passive`, `adverb`, `intensifier`, `wordy`, `cliche`, `repeated_start`, `echo`, `preference`, `long_sentence`, `hard_sentence`, `sticky_sentence`) | `style_checks.analyze_document(text, kinds=None)` in `src/utils/style_checks.py`; `analyze_paragraph` for one paragraph | `List[StyleIssue]` (`kind`, `start`, `end`, `text`, `message`, `suggestions`, `sentence_level`) | No | 13 ms |
| Style counts | `style_checks.summarize(issues, words)` | `{"total", "words", "by_kind", "per_1000"}` | No | < 1 ms |
| Style sheet breaks | `style_sheet.preference_issues(project, paragraph)` in `src/ai/style_sheet.py` | `StyleIssue`s, kind `"preference"` | No | < 1 ms for all paragraphs |
| Built-in grammar rules | `proofing.builtin_grammar(text)` in `src/utils/proofing.py` | `List[GrammarIssue]` | No | 8 ms |
| LanguageTool grammar | `LanguageToolEngine.get()`, then `.ensure_started()` (blocking: call it from a worker; needs Java), then `.check(text)` | `List[GrammarIssue]`, `[]` when not running | No (Java server) | the server starts once; not timed here |
| Merge the two grammar sources | `proofing.merge_issues(*groups)` | `List[GrammarIssue]` | No | — |
| Readability | `proofing.readability(text)` | `Readability` (Flesch-Kincaid grade and reading ease) or `None` | No | 4 ms |
| Overused words and repeated phrases | `OveruseDetector()` in `src/utils/overuse.py`: `.update_cache(text)`, then `.analyze_text(text)` / `.analyze_phrases(text)` | `{word: count}` / `{phrase: count}` | No | 7 ms |
| Which light repeats weaken the writing | `repetition_judge.judge(llm, items, context)` in `src/ai/repetition_judge.py`; items from `OveruseDetector.review_items()` | `{key: (weakens, reason)}`, cached | **Yes** | one model call |
| Writing statistics: sentence lengths and variety, sticky sentences, echoes, passive, adverbs, clichés, dialogue share and tags, readability | `ProWritingAnalyzer().analyze(text)` in `src/utils/writing_stats.py` (since R.4, passive, adverbs, clichés, sticky sentences and echoes come from `style_checks`) | `WritingStats` (e.g. `sentence_length_score`, `dialogue_percentage`, `dialogue_tags`) | No | 7 ms |
| Model judging of style, grammar and spelling flags | `flag_judge.judge(llm, category, items, context)` in `src/ai/flag_judge.py`; items from `flag_judge.collect(highlighter, document)`; quick no-model rules `quick_style_ok`, `quick_grammar_ok`, `quick_word_intended` | `{key: (keep, reason)}`, cached; `dropped(...)` reads the cache | Judge: **yes**. Quick rules: no | one model call per batch |
| Names, spellings, hyphenation, capitals, numbers, punctuation across the manuscript | `ConsistencyChecker(chapters, canon_names, is_known_word=None, ignored=()).run()` in `src/utils/consistency_checks.py`; `chapters` is `[(chapter_id, title, text)]`. Canon names as `MainWindow._canon_names` builds them: characters, `canon_index.collect_world_entities(project.worldbuilding)`, the project dictionary | `List[ConsistencyGroup]` | No | 53 ms for one chapter; 440 ms for 20 |
| Overly descriptive statements | `overdescription.scan(text)` (candidates) or `overdescription.review_chapter(text, llm=None, voice=None)` in `src/ai/overdescription.py` | `List[Flag]` / `Review` (strongest first, at most 25) | Scan: no. With `llm`: the model confirms and suggests expansions | 8 ms scan; 15 ms review without a model |
| Who says each line of dialogue | `dialogue_speakers.attribute_lines(text, names)` in `src/ai/dialogue_speakers.py` | `List[Line]` | No | 1 ms |
| Dialogue problems | `dialogue_craft.dialogue_issues(text, names)` in `src/ai/dialogue_craft.py` | `List[DialogueIssue]` | No | 1 ms |
| Does a line fit its speaker | `dialogue_craft.speech_profiles(project, text)` then `dialogue_craft.line_fit(line, speaker, profiles)` | `{name: SpeechProfile}`; `line_fit` returns a note, or `""` | No | < 1 ms |
| Pacing against published books by genre: **built-in ranges** | the Critique's `PacingAnalyzer` in `src/ai/chapter_analysis_agent.py`, with `resolve_genre_profile(project.prose_profile.genre)` → `GenreProfile` (11 genres plus a default: sentence length, variety, dialogue share, passive, long sentences and adverbs) | `ReportSection` | No for the numbers; the narrative needs a model | — |
| Pacing against CONLIT data | `pacing_analyzer.analyze_text(text)`, then `compare_to_genre(stats, genre_key, conlit_stats)` with `conlit_loader.get_genre_stats_cached()` | stats `dict`; comparison `dict` | No, but **needs the CONLIT download** configured in the Training Studio (`None` in a fresh install) | 1 ms |
| Every measure beside published books in the genre (P.3) | `genre_baseline.usable(genre, measure)` → `GenreRange` (p10, median, p90, books), `genre_baseline.threshold(name, genre, fixed)` (what `CheckContext.threshold` asks), `genre_baseline.line(genre, measure, value)` for the message, in `src/ai/genre_baseline.py`; built once by `scripts/genre_baseline.py` from the downloaded Gutenberg books into `~/.creativeos/genre_baseline.json` | `GenreRange` / `Threshold` / `str` | No, but **needs the baseline built** (none in a fresh install: the fixed figures stay) | < 1 ms to read; about a second a chapter to build |
| Continuity **across novellas** | `ContinuityAnalyzer(project, llm=None).run()` in `src/ai/continuity_analysis.py`; `has_cross_manuscript_content(project)` says whether there is anything to check | `ReportSection` (`ReportType.CONTINUITY`) | No for the presence map, possible resurrections and unrecorded names; yes for conflicts | 2 ms |
| Order of actions **in a rewrite** | `event_order.events(text)`; `event_order.order_problems(original, rewrite)` in `src/ai/event_order.py` | `List[Event]`; `List[str]` | No | 3 ms |
| Story promises and character consistency in a chapter | `PromiseChecker(llm).check_chapter(...)` in `src/ai/chapter_analysis_agent.py`; inputs from `chat_actions.promise_check_inputs(project)` | `PromiseCheckResult` | **Yes** | one model call |
| Chapter critique: 11 reports (Pacing, Voice, Tension, Plot, Dialog, Style, Canon, Grammar, Characters, Worldbuilding, Continuity) | each analyser's `.run(text, chapter_title, chapter_index, genre, manuscript_context, rag_context, critique_context, llm)` in `src/ai/chapter_analysis_agent.py`; the screen is `src/ui/grader_widget.py` | `ReportSection` | No for the numbers (`_compute`); yes for the narrative | numbers: fast; narrative: one or more model calls per report |
| Critique history over time | `critique_history.record(project, report)`, `.load(project)`, `.compare(prev, cur)`, `.trend(runs)` in `src/data/critique_history.py` | comparison `dict`; stored in `critique_history.json` beside the project | No | — |
| Settled story decisions | `story_memory.entries(project)`, `.relevant(project, text)`, `.prompt_block(project, text)` in `src/ai/story_memory.py` | lists; prompt text | No (extracting new ones from chat: yes) | — |
| Personal style rules | `style_sheet.rules(project)`, `.allowed_words`, `.kept_kinds`, `.preferences`, `.record` | lists and sets | No | — |
| Where you left off, margin notes, reader's eye | `companion.left_off(...)`, `companion.paragraph_notes(project, chapter, paragraphs, indices)`, `companion.reader_pass_quick(project, chapter, text)` in `src/ai/companion.py` | `LeftOff`; `List[Note]`; `ReaderReport` | No (`judge_notes`, `reader_pass`: yes) | 1 ms each |
| Fixes to suggest | `companion.fix_candidates(highlighter, document, notes, overdescribed, text)`, then `three_fixes_quick(candidates)` or `three_fixes(llm, ...)`; rewrites via `suggest_fix_options(llm, ...)` | `List[dict]`; `List[Fix]`; `List[FixOption]` | Candidates and quick fixes: no. Choosing and rewriting: yes | — |

## Story and project data

| Need | Where |
|---|---|
| Promises made to the reader | `project.story_planning.promises`: `List[StoryPromise]` (`promise_type`, `title`, `description`, `related_characters`). **Nothing links a promise to a chapter**; only `PromiseChecker` (model) relates them. |
| Subplots | `project.story_planning.subplots`: `List[Subplot]`. A chapter says which subplots it advances in `chapter.planning.subplot_notes[].subplot_id` (optional, `status` active / resolved / dormant). |
| Themes, tensions | `story_planning.themes` (`List[str]`), `story_planning.theme_details` (`List[Theme]`), `story_planning.tensions` |
| Plot events | `story_planning.freytag_pyramid.events` (`PlotEvent`: `stage`, `act`, `sort_order`, `related_subplots`); chapter events in `chapter.planning.events` (`StoryEvent`: `completed`, `stage`, `order`) |
| Genre, tone and voice targets | `project.prose_profile`: `ProseProfile` (`tone`, `style`, `voice`, `genre`, `notes`) |
| Genre taxonomy and comp titles | `src/data/genres.py`: `match_genres(text)`, `info_for(key)`, `comps_for(keys)`, `authors_for(keys)` |
| Reader and editor feedback | `chapter.planning.feedback`: `ChapterFeedback` with `entries: List[FeedbackEntry]` (`title`, `content`, `source`) |
| Per-chapter revisions | `chapter.revisions`: `List[ChapterRevision]`; screen `src/ui/revision_dialog.py` |
| Whole-project snapshots | `project_checkpoint.create_checkpoint(project_dir, name)`, `list_checkpoints`, `restore_checkpoint` in `src/services/project_checkpoint.py` |
| Export (Word, Kindle, Barnes & Noble, publisher-ready, outline) | `ManuscriptExporter` in `src/export/manuscript_exporter.py`: `export_to_docx`, `export_for_kindle`, `export_for_barnes_noble`, `export_publisher_ready`, `export_outline_to_docx`, `export_document` |
| Literary agent contacts | `project.agent_contacts`; screen `src/ui/agent_manager_widget.py`. Its email and publish buttons are placeholders (see [screens.md](screens.md)). |
| Detachable tabs | `src/ui/window_manager.py`, `src/ui/secondary_window.py` (see [screens.md](screens.md)) |
| The assistant's modes and actions | `src/ui/chat_widget.py`; `src/ai/chat_actions.py` (`detect_intent`, `extract_actions`, `format_critique_for_chat`); described in `docs/AI_AGENTS_GUIDE.md` |
| Read aloud | `get_tts_service()` in `src/services/tts_service.py` |

## A project's manuscripts and chapters

Readiness works per manuscript, so these are the calls to use:

- **Every manuscript:** `project.iter_manuscripts()` → `[(scope, Manuscript)]`,
  main first. `scope` is `None` for the main manuscript and the novella's
  (`Subproject`) id otherwise. `project.scope_label(scope)` gives its name.
- **One manuscript:** `project.get_manuscript_for(scope)`;
  `project.get_main_manuscript()`.
- **Watch out:** `project.manuscript` is the **active** manuscript, which is a
  novella when the writer has one open, not always the main one. Use the
  calls above, never `project.manuscript`, to mean "the main manuscript".
- **Chapters:** `manuscript.chapters` (`List[Chapter]`, in order;
  `chapter.id`, `.number`, `.title`, `.planning`).
- **Chapter text:** `chapter.content`, loaded for every chapter of every
  manuscript when the project opens (`WriterProject.load_project`). The open
  chapter's live text can be newer than `chapter.content` until it is saved;
  `MainWindow._chapters_for_links()` returns `[(id, title, text)]` with the
  live text swapped in.
- **Find a chapter anywhere:** `project.find_chapter_with_scope(chapter_id)` →
  `(scope, chapter)`.

## Editor flags for a chapter that is not open

The editor's flags (spelling, grammar, overuse, repeated phrases and style)
live only inside `WritingHighlighter._errors`, keyed by block (paragraph). They
are filled in as Qt paints each paragraph (`highlightBlock`). No plain
function returns them for a chapter.

**Confirmed workable without a window:** build a `QTextDocument`, set the
chapter's text, attach `WritingHighlighter(document, SpellChecker())`, call
`update_full_text(text)` and `do_full_recheck()`, then read `_errors` or pass
the highlighter and document to `companion.fix_candidates`. That takes 0.36 s
for a 4,000-word chapter. It needs a `QApplication`, and LanguageTool's flags
arrive later, from its own worker (`request_grammar_check`). With them left
out, it gives spelling, overuse, repeated phrases and style.

A simpler route covers most of it without Qt (since R.3):
`style_checks` for style, `OveruseDetector` (`src/utils/overuse.py`) for
overuse and phrases, `GrammarChecker` (`src/utils/grammar_checker.py`, or
`proofing` directly) for grammar, and `SpellChecker`
(`src/utils/spell_checker.py`; teach it the project's words with
`set_project_words`, as `EnhancedTextEditor.set_project_vocabulary` does)
for spelling. The readiness engine (1.2a) should choose one route, and
record whether its counts must match the editor's exactly.

**Since R.3** the checkers live in `src/utils/`, with no Qt:
`spell_checker.py` (`SpellChecker`), `overuse.py` (`OveruseDetector`),
`writing_stats.py` (`ProWritingAnalyzer`, `WritingStats`) and
`grammar_checker.py` (`GrammarChecker`). The old import from
`src/ui/enhanced_text_editor.py` still works, but new code imports from
`src/utils/`.

## Gaps

These were looked for and are not in the app:

- **Order of events across a chapter or the book.** `event_order` only checks
  that a rewrite keeps its original's order. Nothing compares a chapter's
  events with the plan or with earlier chapters.
- **Continuity within one manuscript.** `continuity_analysis` only compares
  novellas with each other; a project with no novellas gets nothing from it.
  Inside one book, character and world fidelity is the Canon, Characters and
  Worldbuilding reports, which need a model to say anything beyond counts.
- **Promises touched per chapter.** There is no link from a chapter to a
  promise; only the model-based `PromiseChecker` relates them.
- **Scene purpose** and **point of view:** no check.
- **Whole-book voice drift:** no check. Tried in 4.2 and dropped at its
  gate: the voice measures cannot tell a model's rewrites from the
  writer's prose (`scripts/voice_drift_gate.py`, the 4.2 brief's *Outcome*).
- **Sentence variety in `style_checks`:** only `ProWritingAnalyzer` measures
  it.
- **Homonyms, sensory detail:** no scan. Scenes with no sensory grounding
  are named only in the Critique's model prompts. (Transitions, pronouns,
  alliteration and acronyms became style checks in P.2a,
  `src/utils/style_reports.py`, off until ticked.)
- **Pacing against genre with no download:** only the Critique's built-in
  `GENRE_PROFILES` (rules of thumb, not measured). CONLIT figures need the
  Training Studio download. Figures from published books in the genre
  (P.3) need the downloaded books and `scripts/genre_baseline.py`; a
  genre needs five books before they are used.
