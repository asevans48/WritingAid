# Cut pieces

These were cut to keep the app uncluttered. They are kept so any can be
restored. Do not build them unless the tracker says so.

## U.4 Issue strip beside the text

- **Status:** cut. Kept for reference; do not build.
- **The writer gets:** a thin strip beside the editor's scrollbar showing where
  problems sit in the chapter, in each kind's colour. Clicking jumps there.
  It follows the same on and off choices as the highlighting.
- **Read first:** `WritingHighlighter` in `src/ui/enhanced_text_editor.py`.
- **Risk:** this touches the largest file in the app. The strip is a separate
  widget that reads the highlighter's results and changes nothing in it.
- **Done when:** the strip matches the highlights and stays in step while typing.
- **Review notes:**

## U.5 Panels on a second screen

- **Status:** cut. Kept for reference; do not build.
- **The writer gets:** the scorecard and the Companion can each be popped out
  into their own window, moved to another monitor, and docked back. The app
  remembers the arrangement.
- **Read first:** `src/ui/window_manager.py`, `src/ui/secondary_window.py`.
- **Done when:** a popped-out panel survives a restart and returns to the main
  window if its monitor is gone.
- **Review notes:**

## 5.1 Changes shown in the text

- **Status:** cut. Kept for reference; do not build.
- **The writer gets:** a mechanical fix appears in the manuscript as a tracked
  change: the old text struck through, the new text beside it, and accept and
  reject controls next to it.
- **Design first:** how the pending change is drawn without altering the saved
  text, and how it survives typing nearby. Review this before coding.
- **Read first:** `_replace_span` and the highlighter in
  `src/ui/manuscript_editor.py`, `src/ui/enhanced_text_editor.py`.
- **Limits in this piece:** spelling and grammar fixes only.
- **Tests:** accept applies the change; reject leaves the text exactly as it
  was; a pending change is never saved into the chapter.
- **Done when:** a spelling fix can be accepted or rejected without a dialog.
- **Review notes:**

## 5.2 One-sentence rewrites in the text

- **Status:** cut. Kept for reference; do not build.
- **The writer gets:** the same treatment for a one-sentence rewrite from the
  fix queue, with **More options…** opening Suggestions as it does now.
- **Done when:** a queue fix can be accepted in the text, and its rating is
  logged as before.
- **Review notes:**

## 9.4 Beta readers

- **Status:** cut. Kept for reference; do not build.
- **The writer gets:** export chapters with a short feedback form; bring the
  answers back in as chapter feedback and as notes in the fix queue.
- **Read first:** `ChapterFeedback` in `src/models/project.py`,
  `src/ui/feedback_widget.py`.
- **Done when:** a reader's comment returns as a note on the right chapter.
- **Review notes:**

## 10.1 Personal revision checklist

- **Status:** cut. Kept for reference; do not build.
- **The writer gets:** when several fixes of one kind have been accepted, the
  Companion says so ("You've cut 'she felt' 14 times") and adds the pattern to
  a personal checklist the writer can read before drafting.
- **Uses:** the counts from 4.3, so the checklist belongs to one project.
- **Done when:** the checklist exists, updates as fixes are accepted, and each
  entry can be removed.
- **Review notes:**

## 4.2 Voice drift

- **Status:** dropped at its gate, 26 November 2026. Kept for reference; do
  not build. The brief is [pieces/53-4.2-voice-drift.md](pieces/53-4.2-voice-drift.md).
- **Why:** the brief said to prove the measure first and drop the piece if
  it could not tell an untouched chapter, one the writer revised and one a
  model rewrote apart. The voice measure (`writer_voice`, as V.1's
  fingerprint, compared as V.2 does) catches 74% of chapters by another
  author, but none of 14 chapter-sized sets of a model's rewrites of the
  writer's passages: the rewrites move it about 0.25, while the writer's
  own chapters differ by up to 0.6. The app's rewrites are written to
  match these very measures, so the measure cannot see them.
- **To reopen:** rerun `scripts/voice_drift_gate.py --writer` when there
  are a few hundred plain model rewrites rated; reopen only if section 4 a)
  separates them (see the brief's *Outcome* and checklist section 3).
- **Review notes:**

---

