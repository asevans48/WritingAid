# Plan: getting a manuscript to a publishable state

The app already has most of the detectors and rewriting tools a revision needs.
What it lacks is one place that answers two questions: **how close is this book,
and what should I do next?** It also lacks any measure of how good its own
checks are. This plan fixes both, and leaves the app with fewer screens and less
duplicated code than it has now.

It is 67 pieces (D.5 was added in 0.2). Each is one file in [pieces/](pieces/), sized for one
coding session, reviewed before it is coded, and leaves the app working when it
is finished.

| File | What it is | Who reads it |
|---|---|---|
| This file | How to work, the rules, the tracker, the decisions | Every session |
| [pieces/](pieces/) | One brief per piece | The session doing that piece |
| [inventory.md](inventory.md) | What the app already has | Every session |
| [look-and-feel.md](look-and-feel.md) | How screens should look and behave | Sessions that touch a screen |
| [background.md](background.md) | The critical review, what "publishable" means, sources | You, when reviewing |
| [cut.md](cut.md) | Pieces cut from the plan | Nobody, unless one is restored |

## How to work through this plan

For each piece, in tracker order:

1. **Review the piece.** Open its file. Change anything you disagree with and
   write your changes under *Review notes*. The file is the brief, so what is
   written there is what gets built.
2. **Start a fresh session** and say: *"Do the piece in
   docs/publishing/pieces/NN-….md. Read docs/publishing/README.md first."*
3. **The session ends with** the tests passing, screenshots for any piece with a
   screen, and the piece's *Outcome* section filled in: what was built, the
   names of new files and functions, and what was left out. Nothing is
   committed. **It also updates three things before it stops:**
   - the [tracker](#tracker) below (tick the piece, with a short note if it
     is on trial or part-built);
   - [checklist.md](checklist.md): tick the piece in its section 5, add what
     the writer should try to section 1 as tick boxes, add any decision it
     needs to section 3, and correct the test totals and counts at the top;
   - the *What has changed since this brief was written* section of every
     later brief whose assumptions this piece changed.
   A session that cannot finish says so in *Outcome* (what is done, what is
   not, and why) and leaves the tracker box as `[~]`.
4. **Try it, then commit** if you are happy. The tracker is ticked by the
   session; untick it if you reject the work.

### Keeping usage low

- **One piece per session.** A fresh session carries no earlier conversation.
  Clear the session between pieces.
- **A session reads five short files,** not the whole plan: this one, the
  piece (with its *What has changed* and *Build notes* sections),
  [checklist.md](checklist.md), the inventory, and (for screens) look and
  feel. It learns what earlier
  pieces built from their *Outcome* sections, not by searching the code.
- **The piece names the code to read first.**
- **Run only the piece's own tests while working,** and the full suite once at
  the end.
- **No sub-agents or multi-agent workflows.** No piece here needs them.
- **Sizes** are S or M. Nothing is larger: the three pieces that were large are
  each split into a design session and one or two build sessions. If a piece
  starts to sprawl, the session stops and says how to split it.

### Who does what

- **Opus implements.** The pieces are specified closely enough for it.
- **Three design sessions carry the most risk:** [1.2a](pieces/13-1.2a-readiness-engine-design.md) (the engine every
  later piece builds on), [D.2a](pieces/45-D.2a-one-improve-window-design.md) (one window replacing three) and
  [8.1a](pieces/63-8.1a-job-queue-design.md) (the job queue). They write a design and no code. Review each
  design before its build piece starts; use the stronger model for the design
  session if you can.

## Rules every piece follows

These are the specs agreed earlier. A piece is not done unless it meets all of them.

1. **Three tiers, always.** Every feature works with no AI, with a local model,
   and with a general model (cloud or your own server). Without a model the
   feature gives a plainer result; it never shows an empty screen or an error.
2. **No new configuration.** Models are resolved the way each tool already
   resolves them: `task_llm.build_critique_llm()` for critique-style work,
   `word_suggest.get_llm()` for rewriting, both falling back to the default
   model. Local models get compact prompts (`is_local_llm`). No new settings
   pages, model pickers or API keys.
3. **The writer's voice.** Any rewrite is written in the passage's voice
   (`writer_voice.project_voice`), checked with `rewrite_quality.check_rewrite`,
   and shown with its voice fit. Accepted and rejected changes are logged as
   ratings (`log_rated_rewrite`) when data collection is on.
4. **Clues, not proof.** Word scans and counts nominate candidates. With a model
   set up, the model decides which ones are real problems. Without one, the UI
   says the result is a scan.
5. **The writer accepts every prose change.** Nothing rewrites text on its own.
   Every change shows its reason and a diff, and can be undone.
6. **Intuitive UI.** One main action per screen. Sections open and close and
   remember their state. Panels can always be closed and reopened. Content
   scrolls instead of being squeezed. Everything shown relates to the chapter
   or book in front of the writer.
7. **Nothing crashes the app.** Model work runs in background threads that are
   kept alive until they finish; exceptions never escape a Qt slot.
8. **Tested.** Each piece adds tests (a fake model for the AI tier, none for the
   no-AI tier). Any screen is checked in offscreen renders at the three sizes
   in rule 12, with `HOME` set to a scratch folder. The full suite stays green.
9. **Server prompts wait.** Prompts tuned for the 120B server are written when
   the machine arrives (piece 8.3). Until then the server is treated as a
   general model.
10. **Stay inside the piece.** Do not start the next piece, refactor unrelated
    code, or commit.
11. **Backwards compatible.** Nothing a writer already has may break.
    - **Projects.** Every existing project opens and saves exactly as before.
      New data goes in its own per-project file (as `companion_state.py` does)
      or in optional fields with defaults. The project format version is raised
      only when unavoidable, and then through the existing backup-and-migrate
      path.
    - **Missing or damaged state.** A missing, empty or unreadable state file
      means defaults, never an error.
    - **Older versions of the app.** A project saved by the new version still
      opens in the old one. Do not rename or repurpose an existing field.
    - **Where new data goes.** Unknown fields are preserved only at the top
      level of the project file. A field added inside a chapter, a character,
      the prose profile or any other nested part would be dropped if an older
      version saved the project. So new data goes in a per-project file beside
      the project, or at the top level of the project file, never inside a
      nested part (unless piece 0.4 has made those parts keep unknown fields).
    - **Settings.** Existing settings keep their names and meanings. With no
      changes made by the writer, every existing tool behaves as it does today.
    - **Screens and shortcuts.** Existing menus, buttons, right-click items and
      shortcuts keep working, and tabs that can be detached into their own
      window can still be detached. Anything retired under 0.2 leaves a pointer to
      where it went for at least one release.
    - **Updating the app.** A piece that simplifies a screen changes what is
      shown, never what is stored. After an update, every project, settings
      file and saved window layout from the version before opens with
      nothing missing; settings no longer used are left in place and
      ignored, never deleted, so the older version still finds them. Each
      declutter piece proves it with a test that opens a project and settings
      saved before the piece and checks the chapter text is unchanged after
      open, save and reopen.
    - **Code.** Functions used elsewhere keep their signatures; new parameters
      are optional. Existing tests pass unchanged, or the piece explains why
      one had to change.
    - **Stored learning.** Ratings, style sheet rules, story memory, flag
      verdicts and critique history written before the change are still read.
    - **Test for it.** Each piece that touches stored data adds a test that
      loads a project saved before the change, saves it, and loads it again.
    - **Features stay.** Every feature in the app was added because it helped.
      No piece removes something a writer can do today. A piece that merges
      or moves a screen includes a **capability checklist**: each thing the
      old screen could do, and where it is now. The piece is not done until
      every line is ticked.
    - **Trial, then retire.** A replacement is built alongside what it replaces.
      The old screen or section stays, unchanged, until you have used the new
      one on both projects and agree to retire it. Retiring is then its own
      small step. This is the one exception to rule 13's "replace, do not
      stack", and it is temporary.
    - **Defaults do not flip under you.** A changed default applies to new
      projects. An existing project keeps its behaviour and is offered the
      change.
    - **Novellas stay.** A project can hold a main manuscript and novellas.
      Readiness, the scorecard, stages, the queue and the editorial letter all
      work per manuscript, and a chapter in a novella is treated exactly like
      one in the main manuscript. No piece may assume a single manuscript.
    - **Two live projects.** Two projects are in daily use. Anything learned or
      stored by a new feature is kept per project. Nothing a piece does in one
      project may change what the other shows. Before a piece that touches
      stored data is tried on a real project, the safety check from 0.3 is run
      and a checkpoint is taken.
12. **Fits any screen.** From a small laptop to several large monitors.
    - **Small.** The smallest supported screen is 1024 × 600 (confirmed). Every
      new or changed window is usable at that size. It opens
      no larger than the screen it is on, and its main buttons are always
      reachable without scrolling.
    - **Scrollbars.** Anything that can outgrow its space scrolls: long lists,
      long text, side panels, and any dialog taller than the screen. Nothing is
      squeezed below a readable height, and nothing is cut off.
    - **Large.** On a wide screen the layout uses the room (more columns, side
      panels open by default) and reading text keeps a comfortable line length
      and does not stretch edge to edge.
    - **Enlarged.** Layouts hold up at 150% and 200% text scaling. No fixed
      pixel heights on anything that contains text.
    - **Several screens.** Windows remember their size and which screen they
      were on, and reopen on a visible screen if that monitor is gone. Panels
      that can be popped out can be moved to another screen.
    - **Check it.** Render at 1024 × 600, 1440 × 900 and 2560 × 1440, and once
      at 150% scaling, using the harness from U.2.
13. **Declutter. Never add without taking away.**
    - **No new top-level tabs and no new dialogs** where an existing screen can
      show the same thing. The scorecard lives inside the existing Critique
      tab. Fixes appear in the existing Companion.
    - **Replace, do not stack.** A piece that adds a visible button, tab, menu
      item or section names the one it replaces or folds in. If it replaces
      nothing, the piece says why the addition is worth the space. Replacing
      means the ability moves, never that it is lost (rule 11).
    - **Show less by default.** One primary action is visible. Secondary
      actions sit behind a single "More" control. Rarely used options stay in
      menus.
    - **Count it.** Piece 0.2 records how many tabs, panel sections, right-click
      items and visible buttons each main screen has today. No piece may raise
      a count, and the declutter pieces must lower them. The harness (U.2)
      reports the counts.
14. **Leave the code smaller.**
    - **New code goes in new, small modules.** Nothing is added to a file that is
      already over 3,000 lines beyond the few lines needed to call the new
      module. Six files are over that today; `main_window.py` is over 15,000.
    - **Use the shared parts.** No new copy of the provider list, the
      background-thread pattern, the screen-fit code or a colour value.
    - **Refactors change no behaviour.** A refactor piece moves or merges code,
      keeps the old import paths working, and passes the existing tests
      unchanged. It is never mixed with a feature in the same piece.
    - **Measured first where quality could shift.** A refactor that touches a
      check runs the benchmark (Q.2) before and after and shows the same
      numbers.

15. **Nothing is overwritten and nothing is lost.** This applies to every piece
    and most of all to refactors and format changes.
    - **One way to change the manuscript.** Text reaches a chapter only through
      the editor's existing path (`_replace_span` in the editor, then the
      normal save). No new code writes chapter files or the project file
      directly, and no piece changes `save_project`, `load_project` or the
      chapter save and load functions unless that is the piece's stated job.
    - **A refactor changes no stored name.** It may move and merge code. It may
      not change the name, place or layout of anything saved: the project
      file and its fields, chapter folders and their `revision_NNN.md`,
      `plan.md` and `backup_*.md` files, novella folders, the files beside a
      project (`companion_state.json`, `critique_history.json`), the settings
      files and their setting names, the ratings database and its columns, or
      the words stored inside them (provider names, the names of style checks,
      Companion section names, rating values).
    - **A format change is its own piece, never part of a refactor,** and
      follows five steps: it only adds; it stamps a version; it keeps reading
      the old format for good; before the first write in the new format it
      copies the old file aside, as the project file already does; and it is
      tried on a copy of each real project with the safety check before it is
      used on the real one.
    - **Unreadable is not empty.** If a stored file exists but cannot be read,
      the app must not treat it as empty and save over it. It keeps the file,
      sets it aside under a new name, and tells the writer. (Built in 0.4.)
    - **Safe writes.** Every stored file is written to a temporary file and
      swapped in, so an interrupted save leaves the old file whole. (Built in
      0.4; every new store uses it.)
    - **Late results are checked before they land.** Work that finishes in the
      background is applied only if the chapter is the one it was made for and
      the text it would replace is still there, unchanged. Otherwise it is
      offered to the writer or dropped. It never overwrites blind.
    - **Tests never touch real work.** Tests use temporary projects and
      temporary stores. A piece that adds a store adds it to the test set-up
      that redirects stores to a temporary folder.
    - **Checked before and after.** For any piece marked as touching stored
      data, the writer takes a checkpoint, then runs the safety check on both
      projects and records the app's stores before the session, and runs both
      again after:

          venv/bin/python scripts/check_project_safety.py "<project file>"
          venv/bin/python scripts/check_project_safety.py --stores-record before.json
          venv/bin/python scripts/check_project_safety.py --stores-compare before.json

      A writing-only checkpoint (untick "Include Video Studio" when creating
      it) is enough for this. It takes seconds instead of minutes, and
      restoring it leaves the Video Studio as it is.

## Refactors

There is no separate refactor document. Refactoring is part of this plan in two
ways:

- **Rule 14** above applies to every piece: new code goes in small new modules,
  shared parts are reused, and nothing is added to the six files that are
  already over 3,000 lines.
- **Rule 15** governs what a refactor may not touch: no stored name, place or
  layout changes, and no change to how projects are saved or loaded.
- **Six refactor pieces** change no behaviour and are placed where they make
  the next features smaller. Each has a *Data safety* line saying what it
  must leave alone and how that is checked:
  - [R.1](pieces/06-R.1-one-list-of-model-providers.md) One list of model providers (today copied in 26 places)
  - [R.2](pieces/07-R.2-one-way-to-run-background-work.md) One way to run background work (today eight copies)
  - [R.3](pieces/08-R.3-move-the-checkers-out-of-the-editor-file.md) Move the checkers out of the 5,700-line editor file
  - [R.4](pieces/11-R.4-one-style-analyser-not-two.md) One style analyser, not two
  - [R.5](pieces/22-R.5-take-the-revision-wiring-out-of-the-main-window.md) Take the revision wiring out of the 15,000-line main window
  - [R.6](pieces/13b-R.6-one-function-for-the-editors-flags.md) One function for the editor's flags (added by 1.2a)
- **One more, which does change where state is stored,** and so needs your
  decision first: [R.7](pieces/22b-R.7-one-state-file-per-project.md) One
  state file per project, not per folder (found in 3.3).
- **The declutter pieces** (D.1 to D.9) are the equivalent for screens. That
  group, with the interface sweep (U.3a, U.3b), is where the interface gets
  simpler: see [Where the interface gets simpler](#where-the-interface-gets-simpler).

A general split of the main window and the settings dialog is not in the plan
(open decision 4).

## Other documents

**What to do next:** [checklist.md](checklist.md) has the order of work from
here: what to try, what to decide, and the remaining pieces in sequence.

This plan governs new work on the revision features. The other documents
describe the app as it is:

- [DESIGN.md](../../DESIGN.md): architecture, the configuration model and the
  product principles. The plan's rules build on its principles and are
  stricter where they differ.
- [README.md](../../README.md): what the app does and how to install it.
- [AI_AGENTS_GUIDE.md](../AI_AGENTS_GUIDE.md): the assistant's modes. Piece 3.1
  adds one action to the assistant and updates that guide.
- [multi_window_architecture.md](../multi_window_architecture.md): detachable
  tabs. D.4 must keep them working.
- [MAP_BUILDER_IMPROVEMENTS.md](../MAP_BUILDER_IMPROVEMENTS.md): a separate
  backlog for the map builder, outside this plan.

A piece that changes what one of these documents describes updates that
document in the same session.

## Shortest useful route

If usage is tight, these 22 pieces give a measured, decluttered app with a
working path. Everything else can wait or be dropped.

0.1, 0.2, 0.3 · U.1, U.2 · R.3 · Q.1, Q.2 · P.5 · 1.1, 1.2a, 1.2b, 2.1, 1.3,
1.4 · R.5 · 2.2 · 3.1, 3.2, 3.3 · D.1, D.3

If the two books' voices are bleeding into each other's suggestions now, add
V.1, V.2 and V.4.

## Tracker

Work top to bottom within a group. A piece's file lists what it depends on.

**Foundations, in order**
- [x] [0.1](pieces/01-0.1-confirm-the-inventory.md) Confirm the inventory (S, no code)
- [x] [0.2](pieces/02-0.2-map-the-screens-count-the-clutter-decide-what-me.md) Map the screens, count the clutter, decide what merges (S, no code)
- [x] [0.3](pieces/03-0.3-safety-net-for-your-two-projects.md) Safety net for your two projects (S) — check built, both projects pass; screen check built 25 Nov (your run on both projects to follow)
- [x] [0.4](pieces/03b-0.4-harden-saving.md) Harden saving (M, before any piece that stores data)
- [~] [0.5](pieces/03c-0.5-crash-log-and-safe-clicks.md) Crash log and safe clicks (S, added 24 Nov) — built; waiting to hear the scorecard crash is gone
- [x] [U.1](pieces/04-U.1-shared-interface-parts.md) Shared interface parts (M)
- [x] [U.2](pieces/05-U.2-screenshot-and-clutter-count-harness.md) Screenshot and clutter-count harness (S)
- [x] [R.1](pieces/06-R.1-one-list-of-model-providers.md) One list of model providers (S)
- [x] [R.2](pieces/07-R.2-one-way-to-run-background-work.md) One way to run background work (M)
- [x] [R.3](pieces/08-R.3-move-the-checkers-out-of-the-editor-file.md) Move the checkers out of the editor file (M)
- [x] [Q.1](pieces/09-Q.1-benchmark-set.md) Benchmark set (M)
- [x] [Q.2](pieces/10-Q.2-scoring-the-checks.md) Scoring the checks (M)
- [x] [R.4](pieces/11-R.4-one-style-analyser-not-two.md) One style analyser, not two (M)

**The path, in order**
- [x] [1.1](pieces/12-1.1-publishing-goal.md) Publishing goal (S)
- [x] [1.2a](pieces/13-1.2a-readiness-engine-design.md) Readiness engine: design (S, design, no code)
- [x] [R.6](pieces/13b-R.6-one-function-for-the-editors-flags.md) One function for the editor's flags (S, added in 1.2a)
- [x] [1.2b](pieces/14-1.2b-readiness-engine-build-with-its-first-two-checks.md) Readiness engine: build, with its first two checks (M)
- [x] [2.1](pieces/15-2.1-scorecard-screen.md) Scorecard screen (M)
- [x] [1.3](pieces/16-1.3-line-checks.md) Line checks (S)
- [x] [1.4](pieces/17-1.4-copyedit-checks.md) Copyedit checks (S)
- [x] [1.5](pieces/18-1.5-structure-checks.md) Structure checks (M)
- [x] [1.6](pieces/19-1.6-scene-checks.md) Scene checks (M)
- [x] [1.7](pieces/20-1.7-model-judging-for-the-checks.md) Model judging for the checks (M)
- [x] [1.8](pieces/21-1.8-opening-pages.md) Opening pages (S)
- [x] [R.5](pieces/22-R.5-take-the-revision-wiring-out-of-the-main-window.md) Take the revision wiring out of the main window (M)
- [x] [R.7](pieces/22b-R.7-one-state-file-per-project.md) One state file per project, not per folder (S, added 24 Nov) — built, for review
- [x] [2.2](pieces/23-2.2-from-a-cell-to-the-fix.md) From a cell to the fix (S)
- [x] [2.3](pieces/24-2.3-check-the-book-in-the-background.md) Check the book in the background (M)
- [x] [2.4](pieces/25-2.4-progress-over-time.md) Progress over time (S)
- [x] [2.5](pieces/25b-2.5-critique-beside-write.md) Critique beside Write: links and its own window (S, added 24 Nov) — built, for review
- [x] [3.1](pieces/26-3.1-chapter-stages.md) Chapter stages (S) — built, for review
- [x] [3.2](pieces/27-3.2-the-next-fix-queue.md) The next-fix queue (M) — built, on trial
- [x] [3.3](pieces/28-3.3-skip-and-not-a-problem.md) Skip and Not a problem (M) — built, for review
- [x] [3.4](pieces/29-3.4-accept-all-like-this.md) Accept all like this (S) — changed after review: a "Fix all N" tick box, for every kind of flag

**Parity with ProWritingAid (after the foundations; alongside the path)**
- [ ] [P.5](pieces/30-P.5-fix-or-hide-the-worst-checks.md) Fix or hide the worst checks (M, repeatable)
- [x] [P.2a](pieces/31-P.2a-missing-reports-transitions-pronouns-alliteratio.md) Missing reports: transitions, pronouns, alliteration, acronyms (M) — built, for review; all four off until ticked
- [x] [P.2b](pieces/32-P.2b-missing-reports-homonyms-sensory-detail-sentence.md) Missing reports: homonyms, sensory detail, sentence structure, diction (M) — built, for review; off in existing projects, Homonyms ticked for new ones
- [x] [P.3](pieces/33-P.3-every-measure-compared-with-the-genre.md) Every measure compared with the genre (M) — built, for review; figures need `scripts/genre_baseline.py` run once, and a genre needs five downloaded books
- [x] [P.4](pieces/34-P.4-deeper-proofreading-with-a-model.md) Deeper proofreading with a model (M)
- [x] [P.6](pieces/35-P.6-languagetool-in-full-with-its-larger-data-as-a-d.md) LanguageTool in full, with its larger data as a download (S)
- [x] [P.8](pieces/36-P.8-character-analysis.md) Character analysis (M)
- [ ] [P.7](pieces/37-P.7-reader-s-eye-for-the-whole-book.md) Reader's eye for the whole book (M, best after 8.1)
- ~~[P.1](pieces/38-P.1-side-by-side-comparison.md) Side-by-side comparison~~ Dropped 24 Nov 2026 (decision 6: the writer said it can go)

**Ratings grouped by voice (after 0.3; in order)**
- [x] [V.1](pieces/39-V.1-a-voice-fingerprint-on-every-rating.md) A voice fingerprint on every rating (S)
- [x] [V.2](pieces/40-V.2-voice-groups-without-a-model.md) Voice groups without a model (M)
- [x] [V.3](pieces/41-V.3-a-model-names-and-refines-the-groups.md) A model names and refines the groups (S)
- [x] [V.4](pieces/42-V.4-suggestions-learn-from-the-same-voice.md) Suggestions learn from the same voice (M)
- [x] [V.5](pieces/43-V.5-manage-ratings-by-voice.md) Manage ratings by voice (M)

**The writing habit (added 24 Nov 2026, open decision 2)**
- [x] [H.1](pieces/67-H.1-the-writing-habit.md) The writing habit: daily and weekly goals, a shared streak, a gentle nudge to move on (M; brief reviewed with the writer, no model needed) — built, for review; nothing changes until you set a goal, apart from one "Set a daily goal…" link

**Declutter**
- [x] [D.1](pieces/44-D.1-tidy-the-right-click-menu.md) Tidy the right-click menu (S) — built, for review
- [x] [D.2a](pieces/45-D.2a-one-improve-window-design.md) One Improve window: design (S, design, no code) — written and reviewed 25 Nov; the seven questions are answered (open decision 16)
- [x] [D.2b](pieces/46-D.2b-one-improve-window-build-with-suggestions-and-ex.md) One Improve window: build, with Suggestions and Expand (M) — built 25 Nov, for review: one window with 💡 Suggestions · 📝 Critique · 🔍 Expand (Rephrase's place kept for D.2c); the old windows one tick away (Settings ▸ Features ▸ Improve window); right-click 7 / 11
- [x] [D.2c](pieces/47-D.2c-one-improve-window-rephrase-joins.md) One Improve window: Rephrase joins (M) — built 26 Nov, for review: ✨ Rephrase is the third tab (Ctrl+3); Ctrl+R, ✨, the right-click, a style flag's ✨ Rewrite with AI and the draft window's Rephrase open the window on it; its 25 options behind ▸ Change options; no "Discard your edit?"; rating rows the same as the old window's (tested); the old window one tick away
- [x] [D.3](pieces/48-D.3-one-issues-list-in-the-side-panel.md) One issues list in the side panel (M, after 3.2) — built; the Style tab retired in D.6
- [x] [D.6](pieces/48b-D.6-retire-the-trial-screens.md) Retire the trial screens, and bring the counts back down (S, added 24 Nov; after you have used 3.2, D.3 and 2.5) — built, for review: the Style tab and Today's three fixes are gone (their actions are on the Companion card and in ✓ Checks ▾); menus counted by decision 11; every count at or under the baseline
- [x] [D.7](pieces/48c-D.7-show-less-at-once.md) Show less at once: toolbar, hover card, Companion sections, Drafts into File (M, added 24 Nov) — built, for review
- [~] [D.8](pieces/48d-D.8-one-look.md) One look: the same buttons, colours and spacing everywhere (M, repeatable, added 24 Nov) — first session done (24 Nov): Write and its side panel, the Companion, the Critique and Settings take their colours and button styles from `ui_kit`; second session (25 Nov): Plot, Characters, World, Visuals, Video Studio, Publishing, Drafts, Print; left: Training Studio, the assistant, Video Studio's editors
- [~] [D.9](pieces/48e-D.9-fewer-interruptions.md) Fewer interruptions: messages that do not need a click (M, repeatable, added 24 Nov) — first session done (24 Nov): 49 of the 68 boxes in Write, the Companion, the Critique and the main window are quiet; second session (25 Nov): 67 more on the other screens in the main window; boxes in separate windows stay (a decision for the writer)
- [x] [D.4](pieces/49-D.4-fewer-top-level-tabs.md) Fewer top-level tabs (M, after 0.2) — built, for review: five groups (Write · Story · Revise · Publish · Studio); right-click any tab to open it in its own window (one mover, the Critique menu and Multi-Window Mode included; "⧉ Own window" retired); the old ten tabs one switch away in Settings during the trial
- [x] [D.5](pieces/49b-D.5-analyses-run-as-critique-reports.md) Analyses run as Critique reports (M, after 2.1; added in 0.2) — built, for review: the six Analyze ▾ entries run in Revise ▸ Critique (rated, saved, in history); Writing hints is a real report; the old windows one link away ("Show in a window (old)") during the trial

**Interface sweep (after U.2)**
- [ ] [U.3a](pieces/50-U.3a-fit-and-scroll-sweep-the-screens-used-most.md) Fit-and-scroll sweep: the screens used most (M)
- [ ] [U.3b](pieces/51-U.3b-fit-and-scroll-sweep-the-remaining-screens.md) Fit-and-scroll sweep: the remaining screens (M, repeatable)

**After the path, in any order**
- [x] [4.1](pieces/52-4.1-mark-as-intentional.md) Mark as intentional (S)
- ~~[4.2](pieces/53-4.2-voice-drift.md) Voice drift (M, experimental)~~ Dropped 26 Nov 2026 at its gate: the voice measure cannot tell a model's rewrites from the writer's own prose (a model's rewrites move it about 0.25, the writer's own chapters differ by up to 0.6; 0 of 14 model sets caught). Proof in `scripts/voice_drift_gate.py`; nothing built
- [x] [4.3](pieces/54-4.3-checks-earn-their-place.md) Checks earn their place (S) — built, for review: accepts, skips and dismissals counted per check in the readiness file; a check mostly turned down is toned down (lower, fainter), never switched off without your click
- [x] [6.1](pieces/55-6.1-listen-and-mark.md) Listen and mark (M)
- [x] [6.2](pieces/56-6.2-marks-become-notes.md) Marks become notes (S)
- [x] [7.1](pieces/57-7.1-reverse-outline-without-a-model.md) Reverse outline without a model (M) — built, for review
- [ ] [7.2](pieces/58-7.2-reverse-outline-with-a-model.md) Reverse outline with a model (M, experimental)
- [x] [7.3](pieces/59-7.3-draft-beside-plan-and-the-tension-curve.md) Draft beside plan, and the tension curve (M) — built, for review: no-model tier; tension waits for 7.2
- [ ] [9.1](pieces/60-9.1-final-sweep.md) Final sweep (M)
- [x] [9.2](pieces/61-9.2-export-and-import-check.md) Export and import check (M) — built, for review
- [x] [9.3](pieces/62-9.3-submission-package-and-marketability.md) Submission package and marketability (M) — built, for review (model tier untried)

**When the server is connected**
- [x] [8.1a](pieces/63-8.1a-job-queue-design.md) Job queue: design (S, design, no code) — written and reviewed 26 Nov; the eight questions answered as recommended (decision 17). 8.1b can start once the server is connected
- [ ] [8.1b](pieces/64-8.1b-job-queue-build.md) Job queue: build (M)
- [x] [8.2](pieces/65-8.2-editorial-letter.md) Editorial letter (M) — built; not yet tried with a real model
- [ ] [8.3](pieces/66-8.3-server-prompts.md) Server prompts (M)

**Cut** (see [cut.md](cut.md)): 5.1, 5.2, U.4, U.5, 9.4, 10.1

**Briefs brought up to date.** On 24 November 2026 every remaining brief that
phase 3, D.3 or 2.5 affects gained a section, *What has changed since this
brief was written*, above its *Review notes*. A session reads it with the
brief. When a later piece changes what a remaining brief assumes, add to that
section in the same session.

### Where the interface gets simpler

Simplifying the interface is not one piece. It is rule 13 on every piece,
plus these:

| Piece | What it simplifies | State |
|---|---|---|
| [0.2](pieces/02-0.2-map-the-screens-count-the-clutter-decide-what-me.md) | Counted every screen's clutter and agreed what merges ([screens.md](screens.md)) | Done |
| [U.1](pieces/04-U.1-shared-interface-parts.md), [U.2](pieces/05-U.2-screenshot-and-clutter-count-harness.md) | Shared parts, and the harness that counts buttons, menu items and sections | Done |
| [D.3](pieces/48-D.3-one-issues-list-in-the-side-panel.md) | One issues list in the side panel | Built; old Style tab retired in D.6 |
| [D.6](pieces/48b-D.6-retire-the-trial-screens.md) | Removes the old screens kept on trial; brings the counts under the baseline | Built, for review: every count at or under the baseline |
| [D.1](pieces/44-D.1-tidy-the-right-click-menu.md) | A short right-click menu (11 → 9 with a selection); flag fixes back in the Write tab | Built, for review |
| [D.7](pieces/48c-D.7-show-less-at-once.md) | Write screen 24 buttons to 19, grouped by row; a shorter hover card; the Companion opens what fits the stage; Drafts into File | Built, for review |
| [D.8](pieces/48d-D.8-one-look.md) | One main button a screen, one set of colours, one spacing (1,014 inline styles today) | First session done: 10 files clean |
| [D.9](pieces/48e-D.9-fewer-interruptions.md) | Messages that need no answer stop opening a box (329 today) | First session done: 49 quiet |
| [D.2a–c](pieces/45-D.2a-one-improve-window-design.md) | Three help windows become one | Built, for review (D.2b, D.2c): Rephrase, Suggestions and Overly descriptive? open one Improve window (tabs Suggestions · Critique · Rephrase · Expand), from every place that opened them, the draft window too; right-click counted 7 / 11 (was 9 / 13); the old three windows behind one switch until you retire them |
| [D.4](pieces/49-D.4-fewer-top-level-tabs.md) | Ten top-level tabs become five; one way to detach a screen, and the "⧉ Own window" button goes | Built, for review: 5 top-level tabs (baseline 10); the old ten one switch away in Settings |
| [D.5](pieces/49b-D.5-analyses-run-as-critique-reports.md) | Six analysis windows become Critique reports | Built, for review: no count rises (Analyze ▾ keeps its eight entries; the links are inside the report); old windows retired after the trial |
| [U.3a](pieces/50-U.3a-fit-and-scroll-sweep-the-screens-used-most.md), [U.3b](pieces/51-U.3b-fit-and-scroll-sweep-the-remaining-screens.md) | Every screen fits and scrolls | Not started |

**Suggested order:** D.6, D.1, D.7, D.9, D.8, D.4, D.2, D.5, then U.3. The
first five change only what is shown. D.4 also reads saved window layouts and
D.5 adds kinds to critique history; their briefs say how older files and
older versions of the app stay safe.

**No piece here removes a feature.** Each starts with a capability checklist
and is not done until every action has a home (rule 11, decision 10). Each
follows rule 11's *Updating the app*.

**Where the counts stand** (the harness, against `screens_baseline.json`,
after D.6, menus counted by decision 11): every count is at or under the
baseline. Companion 15 buttons (baseline 18) and 7 sections (7); the Style
tab's 15 buttons are gone (side panel 3 tabs, was 4); Write 19 buttons (24)
and 29 menu items (29; 53 counting every item); right-click 9 entries
without a selection (12) and 13 with one (22); Critique 6 buttons (11).
After D.4: 5 top-level tabs (baseline 10), now counted by the harness.
After D.2b: right-click 7 and 11 (✨ Improve this ▸ counted as one group,
decision 16; the baseline was lowered to match). The Improve window is
counted (Suggestions tab 10 buttons, 1 section, 3 tabs) but not yet in the
baseline. After D.2c: 4 tabs; the Rephrase tab 12 buttons and 2 sections
(▸ Change options and Talk it through), its 25 options out of view until
opened (the old Rephrase window had 9 buttons and the 25 options in view).
New baselines wait for the writer's agreement.

## Decisions

### Settled

0. **Cuts.** Six pieces are cut to keep the app uncluttered: 5.1, 5.2, U.4,
   U.5, 9.4 and 10.1.

1. **Publishing goal.** The goal is a publishable manuscript. The writer sets
   the route (agent submission or self-publishing). Length is information,
   never a target. (1.1)
2. **Where the scorecard lives.** The front page of the existing Critique tab.
   (2.1)
3. **Who moves a chapter's stage.** The writer, by hand or by telling the
   assistant, and can always move it again by hand. The app only suggests.
   Novellas are kept and treated like the main manuscript. (3.1)
4. **Smallest screen.** 1024 × 600 and up, using whatever room the screen has,
   with scrollbars and nothing squeezed. (Rule 12)
5. **What merges.** Merges are fine: one Improve window, the Style tab into the
   Companion, fewer top-level tabs. Each is still built alongside the old
   screen and retired after you have used it. (D.2, D.3, D.4)
6. **LanguageTool.** Used whenever available, with its larger data offered among
   the downloads in configuration. (P.6)
7. **ProWritingAid.** Feature parity is the aim for writing reports and story
   analysis, and the writing habit. Out of scope: plagiarism checking.
   After the first working product: integrations (YouTube, KDP, Barnes &
   Noble) and community (on its own web page). (Open decision 2.) (Phase P, 7.3, 8.2, 9.3)
8. **Ratings.** Shared across projects and grouped by voice. (Phase V)
9. **What publishable means.** The professional editing stages, in order, as
   defined by the Editorial Freelancers Association and Editors Canada.
10. **The simplest interface, nothing cut.** Agreed in 0.2: the simplest
    interface that is still intuitive and easy to understand, **without
    cutting any feature**, and backwards compatible (rule 11). Menu entries
    that open a merged screen stay as shortcuts.
11. **Tab grouping.** Ten top-level tabs become five: Write · Story (Plot,
    Characters, World) · Revise (Critique, Prose Profile, Attributions) ·
    Publish (Publishing) · Studio (Visuals, Video Studio). Every screen can
    still be detached on its own. (D.4)
12. **Side panel and Improve window.** The Style tab folds into the Companion,
    and its switches for each check go into the ✓ Checks ▾ menu (D.3). Feedback
    stays its own tab. Rephrase, Suggestions and Overly descriptive? become one
    Improve window, while AI Thesaurus and Ask stay separate (D.2). The six
    Analyze ▾ analyses run as Critique reports (D.5).
13. **Look and feel.** The points in [look-and-feel.md](look-and-feel.md)
    stand as written, with the changes agreed in 0.2. Settled when the writer
    asked for U.1 to be built.

### Open

1. ~~**Look and feel.**~~ Settled: see settled decision 13.
2. **Parity scope.** Confirm the three things left out of parity in settled
   decision 7.
   *24 Nov 2026, the writer: "we want parity to place our app on par with
   others." Parity stays the aim, measured against other writing apps as
   well as ProWritingAid.*
   *Settled 24 Nov 2026 for two of the three: plagiarism checking stays
   out. Integrations come in and will be a major part of the app (publish
   videos to YouTube, push to KDP and Barnes & Noble), but **later: after
   the first working product**, so no piece in this plan builds them yet.
   **The writing habit is in scope and important** (goals, streaks and
   the like, as ProWritingAid offers); it needs a brief of its own.
   **Community** comes after the first working product, on a web page of
   its own rather than in the app.*
3. ~~**Quality target.**~~ Settled 24 November 2026 by the writer: **style
   checks must meet four in five** to be on by default; **spelling and
   overused words stay on.** Built: a new project ticks only the style
   checks that meet it (`check_switches.MEETS_TARGET`: weak intensifiers,
   wordy phrases, hard-to-read sentences, pronouns, acronyms, and the
   writer's own style sheet); P.2b added homonyms (5 of 5 right on its
   marked passages). Existing projects keep their ticks. Was: A
   check is on by default only if four in five of its
   flags are right. Confirm or change after the first numbers from Q.2.
   **The first numbers are in** ([check_scores.md](check_scores.md)); see
   the Q.2 *Outcome* for a suggestion.
   **How much the checks miss** is measured separately
   ([miss_rates.md](miss_rates.md), `scripts/measure_misses.py`): known
   mistakes and contradictions inserted, counted as caught or missed, with
   the rules alone and with a model.
4. **How far to refactor.** R.1 to R.5 are limited to what the plan needs. A
   general split of the 15,000-line main window and the 4,000-line settings
   dialog is left out. Say so if you want it added.
5. ~~**Voice groups.**~~ Settled 25 November 2026:
   - **Broad** means shared across projects; **manageable** means the writer
     can manage the groups (see, rename, move, merge, remove). The reading at
     the top of phase V stands.
   - **How many groups: never chosen; it is how many strong, distinct
     voices there is evidence for** (25 Nov; the writer asked for a way
     that is dynamic, strong and manageable and left the method to the
     session; "square root of n" was an example only). The unit is the
     **voice source**: one project with one narrator (`project_path` +
     `character_name`; no narrator: the project alone), with its ratings
     averaged into one fingerprint. Every source starts alone; the two most
     alike merge, again and again, while the merged group stays strong; it
     stops when the next merge would be loose. What is left is the groups.
     Two books in a similar voice: one group. Three in three different
     voices: three. Twelve projects in four real voices: four. The full
     method is in V.2's *Review notes*.
   - **A project can keep its ratings to itself:** a per-project switch,
     off by default. Its ratings teach only that project and are never used
     for another; the store and its groups still hold them.
   - **Groups grow and shrink with the data** (25 Nov, agreed): a source
     counts once it has enough ratings (about 30, set from the writer's
     data); until then it is **Unsorted** and its ratings are used as
     today. At a check (start-up, when a source became ready or the ratings
     grew by about a fifth; or on request) a newly ready source joins the
     group it is alike or starts its own, groups that have drifted together
     merge, and a source that has drifted away leaves. "Alike" and
     "different" are two thresholds with a gap between them, so nothing
     flips back and forth. Groups the app made change by themselves; a
     change touching a group the writer made, named or placed a source in
     is proposed and waits for them.
   - **The writer can set starting groups** (agreed): name a group and
     define it by a project, a narrator or example passages. Their groups
     anchor the sorting, are never merged or removed by the app (a split is
     only suggested), and ratings placed by hand stay put.
   - **Names** (25 Nov): when a group is created (split, new, the writer's
     own without a name) or two are merged, the model gives it a short name
     and a one-line description (V.3); without a model, the plain-words
     description from the measures stands until one is set up. A name the
     writer gave is never changed.
   - **The writer can combine groups:** select two or more and merge them
     (V.5); the result keeps the writer's name if one had it, else is named
     afresh. Undo restores them.
   - **A manageable number** (25 Nov): the writer manages projects and
     narrators inside groups, not single ratings. The app makes at most
     **8** groups (about the most a person can keep apart at a glance);
     beyond that the smallest wait in Unsorted and V.5 suggests merging the
     closest pair; nothing merges without the writer. The 8 is one
     constant, easy to change.
   - **Groups stay strong** (25 Nov: "we still want the groups to be fairly
     strong when grouped together"). No two sources in a group may be
     clearly different voices, measured against how much each source varies
     within itself, so the bar scales with the data. Strength comes before
     the count:
     - the app never makes a loose group to reach a number;
     - a source that fits no group is its own group, or Unsorted while it
       has too few ratings;
     - a source that clearly holds two voices is treated as two;
     - the writer may still merge any groups; if the result would be loose,
       the app says so first ("these voices differ; rewrites will learn
       less precisely from the merged group") and lets them go ahead;
     - rewrites (V.4) learn first from the closest ratings within the
       group.
   Was: my reading of "broad, manageable", a fixed cap of about eight groups,
   and whether a project's ratings could be kept to itself.
6. ~~**Side-by-side comparison.**~~ Settled 24 November 2026: P.1 is
   dropped. (It was optional and needed access to ProWritingAid.)
7. ~~**Readiness engine design (1.2a).**~~ Settled 23 November 2026 with the
   suggestions in its §10: R.6 first; "needs work" counts as half; overly
   descriptive is shown but left out of the figure until a model judges it.
   Built in R.6, 1.2b and 2.1.
8. ~~**Shared state files.**~~ Settled 24 November 2026: each project gets
   its own state files; the old shared file is read once and never changed.
   ([R.7](pieces/22b-R.7-one-state-file-per-project.md))
9. ~~**Fix all, for every kind of flag.**~~ Settled 24 November 2026:
   every kind with a short fix, **except confused words** (their/there,
   its/it's, then/than, a/an and the like), whose right form depends on the
   sentence: "focus on things that produce value". Built: `fix_all.is_confusable`.
   Was: 3.4's brief said mechanical fixes
   only. At your request the "Fix all N like this" box now covers every flag
   with a short fix, including words that are right in one sentence and
   wrong in the next (their/there). Confirm, or name the kinds to leave out.
10. ~~**Two ways to detach the Critique.**~~ Settled 24 November 2026:
    merge them in D.4: "⧉ Own window" (2.5) and Multi-Window Mode become
    one mechanism, and both entries keep working. Built in D.4
    (`screen_groups`): right-click any tab, the Critique menu and
    Multi-Window Mode use one mover; the ⧉ button went.
11. ~~**What to retire, and the counts.**~~ Settled 24 November 2026: the
    old three-fixes list and the Style tab may go (D.6). A submenu counts
    as one entry when its items are one closely related group (a list of
    synonyms, Novellas ▾, Drafts ▾); items that are different actions count
    separately even inside one submenu (Rephrase, Suggestions and Critique
    under Improve). Was: Which trial screens may go, and
    whether a submenu counts as one menu entry.
    ([D.6](pieces/48b-D.6-retire-the-trial-screens.md))
12. ~~**The on-device model cannot be shared.**~~ Settled 24 November 2026:
    accepted. A model job started while the
    app was using the on-device model crashed the app. Until 8.1 gives jobs
    and the app one queue, model measurements are run with the app closed.
13. ~~**How far to group the Write screen's buttons.**~~ Settled 24 November
    2026: by row, 24 to 18, nothing hidden more than one click away. (D.7)
14. ~~**How a book-wide fix is made safe.**~~ Settled 24 November 2026:
    chapter by chapter through the editor, each chapter with its own undo.
    No one-click change to chapters that are not open. (9.1)
15. ~~**Where the reverse outline shows.**~~ Settled 24 November 2026: in
    the Critique, so it moves with the Critique into its own window. (7.1,
    7.3)
16. ~~**The One Improve window's details.**~~ Settled 25 November 2026:
    - Tabs: Suggestions · Critique · Rephrase · Expand, with Critique
      second.
    - The right-click ✨ Improve this ▸ counts as one group.
    - The tab is named "Expand".
    - The trial switch starts on.
    - An Expand version can be rated.
    - There is no "Discard your edit?" question: selecting the rephrased
      text replaces the highlighted text.
    - The draft window's Rephrase opens the whole window.

    (D.2a, D.2b, D.2c)
17. ~~**How the book check runs as a job.**~~ Settled 26 November 2026:
    - The job carries on by itself two minutes after the project opens.
    - If the server is gone, it retries every 5 minutes for up to 12 hours.
    - The Mac is kept awake while a check runs.
    - Jobs may run on the on-device model, taking turns with the writer.
    - Stop becomes Pause / Resume.
    - A status-bar line shows on every screen while a job exists.
    - Measurement scripts refuse to start while the app holds the model (a
      later small piece).
    - Switching project pauses the job.

    (8.1a, 8.1b)
