"""Project checkpoints run without freezing the app, report progress, can be
cancelled while being created, and still create and restore the same files."""

import os
import time
import zipfile

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from src.services import project_checkpoint as pc


@pytest.fixture
def project_dir(tmp_path):
    d = tmp_path / "Book"
    (d / "chapters" / "chapter_001").mkdir(parents=True)
    (d / "chapters" / "chapter_001" / "revision_001.md").write_text("Chapter text. " * 200)
    (d / "Book.writerproj").write_text('{"name": "Book"}')
    media = d / "Book_video_studio"
    media.mkdir()
    (media / "take.wav").write_bytes(os.urandom(200_000))
    (media / "frame.png").write_bytes(os.urandom(50_000))
    return d


def _files(d):
    return {str(p.relative_to(d)): p.read_bytes() for p in sorted(d.rglob("*"))
            if p.is_file() and pc.CHECKPOINTS_DIRNAME not in p.parts}


def test_progress_reaches_the_total(project_dir):
    seen = []
    pc.create_checkpoint(project_dir, "one", progress=lambda d, t, label: seen.append((d, t)))
    assert seen[0][0] == 0 and seen[-1][0] == seen[-1][1]
    assert [d for d, _ in seen] == sorted(d for d, _ in seen)


def test_media_is_stored_and_text_is_compressed(project_dir):
    cp = pc.create_checkpoint(project_dir, "one")
    with zipfile.ZipFile(cp.zip_path) as zf:
        kinds = {i.filename: i.compress_type for i in zf.infolist()}
    assert kinds["Book_video_studio/take.wav"] == zipfile.ZIP_STORED
    assert kinds["Book_video_studio/frame.png"] == zipfile.ZIP_STORED
    assert kinds["chapters/chapter_001/revision_001.md"] == zipfile.ZIP_DEFLATED


def test_restore_brings_back_every_file(project_dir):
    before = _files(project_dir)
    cp = pc.create_checkpoint(project_dir, "one")
    (project_dir / "chapters" / "chapter_001" / "revision_001.md").write_text("changed")
    (project_dir / "Book_video_studio" / "take.wav").unlink()
    seen = []
    auto = pc.restore_checkpoint(project_dir, cp, progress=lambda d, t, label: seen.append(label))
    after = _files(project_dir)
    after.pop(pc.META_FILENAME_IN_ZIP, None)
    assert after == before
    assert auto is not None and any(label.startswith("Restoring") for label in seen)


def test_cancel_leaves_no_checkpoint(project_dir):
    with pytest.raises(pc.CheckpointCancelled):
        pc.create_checkpoint(project_dir, "one", cancelled=lambda: True)
    cp_dir = project_dir / pc.CHECKPOINTS_DIRNAME
    assert [p.name for p in cp_dir.iterdir()] == []
    assert pc.list_checkpoints(project_dir) == []


def test_old_signature_still_works(project_dir):
    cp = pc.create_checkpoint(project_dir, "plain", description="no hooks")
    assert pc.list_checkpoints(project_dir)[0].name == cp.name


# ── The progress window ────────────────────────────────────────────────

@pytest.fixture
def app():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def test_app_stays_responsive_and_autosave_pauses(app):
    from PyQt6.QtCore import QTimer
    from PyQt6.QtWidgets import QWidget
    from src.ui.checkpoint_progress import run_with_progress

    window = QWidget()
    window._loading_project = False          # stands in for the main window
    child = QWidget(window)
    ticks = []
    timer = QTimer()
    timer.timeout.connect(lambda: ticks.append(window._loading_project))
    timer.start(10)

    def work(progress, cancelled):
        for i in range(10):
            progress(i, 10, f"file {i}")
            time.sleep(0.03)
        return "done"

    result, error = run_with_progress(child, "Working", "Please wait", work)
    timer.stop()
    assert (result, error) == ("done", None)
    assert ticks and all(ticks)               # events ran, with auto-save paused
    assert window._loading_project is False   # and it is back on afterwards


def test_errors_and_cancel_come_back_to_the_caller(app):
    from src.ui.checkpoint_progress import run_with_progress

    def boom(progress, cancelled):
        raise OSError("drive pulled")
    result, error = run_with_progress(None, "Working", "", boom)
    assert result is None and isinstance(error, OSError)


# ── Writing-only checkpoints ───────────────────────────────────────────

def test_writing_only_checkpoint_leaves_out_the_video_studio(project_dir):
    cp = pc.create_checkpoint(project_dir, "words", include_video_studio=False)
    with zipfile.ZipFile(cp.zip_path) as zf:
        names = zf.namelist()
    assert not any(n.startswith("Book_video_studio/") for n in names)
    assert "chapters/chapter_001/revision_001.md" in names
    assert pc.contains_video_studio(cp) is False
    assert pc.list_checkpoints(project_dir)[0].raw["includes_video_studio"] is False


def test_full_checkpoint_is_the_default(project_dir):
    cp = pc.create_checkpoint(project_dir, "all")
    assert pc.contains_video_studio(cp) is True
    assert cp.raw["includes_video_studio"] is True


def test_restoring_writing_only_keeps_current_video_and_restores_the_rest(project_dir):
    cp = pc.create_checkpoint(project_dir, "words", include_video_studio=False)
    rev = project_dir / "chapters" / "chapter_001" / "revision_001.md"
    original_text = rev.read_text()
    rev.write_text("changed after the checkpoint")
    (project_dir / "notes_added_later.md").write_text("later")
    new_take = project_dir / "Book_video_studio" / "new_take.wav"
    new_take.write_bytes(b"recorded after the checkpoint")

    auto = pc.restore_checkpoint(project_dir, cp)

    assert rev.read_text() == original_text                       # writing: exact copy
    assert not (project_dir / "notes_added_later.md").exists()    # exact: later files gone
    assert new_take.read_bytes() == b"recorded after the checkpoint"   # video kept
    assert (project_dir / "Book_video_studio" / "take.wav").exists()
    assert pc.contains_video_studio(auto) is False                # safety copy was quick too


def test_restoring_a_full_checkpoint_is_an_exact_copy(project_dir):
    cp = pc.create_checkpoint(project_dir, "all")
    new_take = project_dir / "Book_video_studio" / "new_take.wav"
    new_take.write_bytes(b"recorded after the checkpoint")
    (project_dir / "Book_video_studio" / "take.wav").unlink()

    auto = pc.restore_checkpoint(project_dir, cp)

    assert not new_take.exists()                                  # exact copy
    assert (project_dir / "Book_video_studio" / "take.wav").exists()
    assert pc.contains_video_studio(auto) is True                 # safety copy kept the video
    assert len(pc.list_checkpoints(project_dir)) == 2


def test_no_video_studio_means_no_question(app, tmp_path):
    from src.ui.checkpoint_progress import ask_include_video_studio
    (tmp_path / "Book.writerproj").write_text("{}")
    assert ask_include_video_studio(None, tmp_path, "Create checkpoint") is True
