"""Social-platform upload dialog.

Opens from the video editor's "📤 Publish…" button. Lets the
writer pick a platform, fill in metadata (title, description,
tags, privacy, category, thumbnail, schedule), wire credentials,
and kick the upload. Each platform implements its own
``SocialPlatform`` adapter — this dialog walks the registry and
asks each adapter only for the fields it actually exposes.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QGuiApplication
from PyQt6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox,
    QDoubleSpinBox, QFileDialog, QFormLayout, QGroupBox,
    QHBoxLayout, QInputDialog, QLabel, QLineEdit, QMessageBox,
    QPlainTextEdit, QProgressBar, QPushButton, QScrollArea,
    QVBoxLayout, QWidget,
)

from src.video_studio.social_upload.base import (
    Privacy, SocialPlatform, UploadMetadata, UploadRequest,
)
from src.video_studio.social_upload.registry import (
    all_platforms, default_platform,
)


class _UploadWorker(QThread):
    """Runs the upload off the UI thread so the dialog stays
    responsive (and the writer can cancel by closing it)."""
    finished_result = pyqtSignal(object)  # UploadResult

    def __init__(
        self,
        platform: SocialPlatform,
        request: UploadRequest,
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self._platform = platform
        self._request = request

    def run(self) -> None:
        result = self._platform.upload(self._request)
        self.finished_result.emit(result)


class SocialUploadDialog(QDialog):
    """Per-video upload dialog."""

    def __init__(
        self,
        video_path: Path,
        suggested_title: str = "",
        suggested_description: str = "",
        parent: Optional[QWidget] = None,
    ):
        super().__init__(None)
        self.setWindowTitle("📤 Publish to social")
        self.setModal(False)
        # ``Qt.Tool`` instead of ``Qt.Window`` — see ChapterProse
        # Window for the long explanation. On macOS, opening
        # ``Qt.Window`` instances from another window triggers
        # the focus-stealing path that minimizes peers and can
        # blank a secondary display. Tool windows accept clicks,
        # stay above the editor that spawned them, but coexist
        # with the rest of the app cleanly. Flags are set ONCE
        # here; we never call ``setWindowFlag(s)`` again after
        # show() to avoid the hide → re-show cycle that re-runs
        # the same heuristic.
        flags = (
            Qt.WindowType.Tool
            | Qt.WindowType.WindowSystemMenuHint
            | Qt.WindowType.WindowCloseButtonHint
            | Qt.WindowType.WindowMinimizeButtonHint)
        self.setWindowFlags(flags)
        screen = QGuiApplication.primaryScreen()
        avail = screen.availableGeometry() if screen else None
        target_w = 720
        target_h = 720
        if avail is not None:
            target_w = max(600, min(target_w, int(avail.width() * 0.6)))
            target_h = max(540, min(target_h, int(avail.height() * 0.9)))
        self.resize(target_w, target_h)
        self.setMinimumSize(560, 480)
        self._video_path = video_path
        self._platforms = all_platforms()
        self._suggested_title = suggested_title
        self._suggested_description = suggested_description
        self._worker: Optional[_UploadWorker] = None
        self._build_ui()
        # Default to a real platform if any are installed.
        try:
            dft = default_platform()
            for i, p in enumerate(self._platforms):
                if p.name == dft.name:
                    self._platform_combo.setCurrentIndex(i)
                    break
        except Exception:
            pass
        self._refresh_for_platform()

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(10, 10, 10, 10)

        # ── Top: video preview info + platform picker ────────────
        info_box = QGroupBox("Source video")
        info_v = QVBoxLayout(info_box)
        self._source_label = QLabel(
            f"<b>{self._video_path.name}</b>"
            f"<br><span style='color:#6b7280;font-size:11px;'>"
            f"{self._video_path}</span>")
        self._source_label.setWordWrap(True)
        info_v.addWidget(self._source_label)
        outer.addWidget(info_box)

        platform_box = QGroupBox("Platform")
        platform_v = QVBoxLayout(platform_box)
        plat_row = QHBoxLayout()
        plat_row.addWidget(QLabel("Send to:"))
        self._platform_combo = QComboBox()
        for p in self._platforms:
            installed_mark = "✓" if p.is_installed() else "(needs install)"
            self._platform_combo.addItem(
                f"{p.label}  {installed_mark}", p.name)
        self._platform_combo.currentIndexChanged.connect(
            lambda _: self._refresh_for_platform())
        plat_row.addWidget(self._platform_combo, stretch=1)
        self._creds_btn = QPushButton("🔑 Credentials…")
        self._creds_btn.setToolTip(
            "Paste API keys / OAuth client ID + secret for the "
            "selected platform. Stored securely in your system "
            "keychain.")
        self._creds_btn.clicked.connect(self._open_credentials_dialog)
        plat_row.addWidget(self._creds_btn)
        self._signin_btn = QPushButton("🌐 Sign in")
        self._signin_btn.setToolTip(
            "Run the platform's OAuth grant in a browser. "
            "Needed once per platform; the refresh token is "
            "stored after the first grant.")
        self._signin_btn.clicked.connect(self._on_signin_clicked)
        plat_row.addWidget(self._signin_btn)
        platform_v.addLayout(plat_row)
        self._platform_status_label = QLabel("")
        self._platform_status_label.setStyleSheet(
            "color: #6b7280; font-size: 11px;")
        self._platform_status_label.setWordWrap(True)
        platform_v.addWidget(self._platform_status_label)
        outer.addWidget(platform_box)

        # ── Metadata form ────────────────────────────────────────
        meta_scroll = QScrollArea()
        meta_scroll.setWidgetResizable(True)
        meta_scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        meta_inner = QWidget()
        form = QFormLayout(meta_inner)
        self._title_edit = QLineEdit()
        self._title_edit.setPlaceholderText(
            "Video title (required)")
        self._title_edit.setText(self._suggested_title)
        form.addRow("Title", self._title_edit)
        self._description_edit = QPlainTextEdit()
        self._description_edit.setPlaceholderText(
            "Description / show notes…")
        self._description_edit.setFixedHeight(140)
        self._description_edit.setPlainText(
            self._suggested_description)
        form.addRow("Description", self._description_edit)
        self._tags_edit = QLineEdit()
        self._tags_edit.setPlaceholderText(
            "Comma-separated tags (e.g. writing, video, fantasy)")
        form.addRow("Tags", self._tags_edit)
        self._privacy_combo = QComboBox()
        self._privacy_combo.addItem("🌍 Public", Privacy.PUBLIC.value)
        self._privacy_combo.addItem(
            "🔗 Unlisted", Privacy.UNLISTED.value)
        self._privacy_combo.addItem(
            "🔒 Private", Privacy.PRIVATE.value)
        self._privacy_combo.setCurrentIndex(2)  # private default
        form.addRow("Privacy", self._privacy_combo)
        self._category_combo = QComboBox()
        form.addRow("Category", self._category_combo)
        self._language_edit = QLineEdit()
        self._language_edit.setPlaceholderText(
            "BCP-47 language code (en, es, fr, ja) — optional")
        form.addRow("Language", self._language_edit)
        thumb_row = QHBoxLayout()
        self._thumbnail_edit = QLineEdit()
        self._thumbnail_edit.setPlaceholderText(
            "Optional .png / .jpg thumbnail")
        self._thumbnail_edit.setReadOnly(True)
        thumb_row.addWidget(self._thumbnail_edit, stretch=1)
        self._pick_thumb_btn = QPushButton("Pick…")
        self._pick_thumb_btn.clicked.connect(self._pick_thumbnail)
        thumb_row.addWidget(self._pick_thumb_btn)
        self._clear_thumb_btn = QPushButton("Clear")
        self._clear_thumb_btn.clicked.connect(
            lambda: self._thumbnail_edit.setText(""))
        thumb_row.addWidget(self._clear_thumb_btn)
        wrap = QWidget(); wrap.setLayout(thumb_row)
        form.addRow("Thumbnail", wrap)
        self._schedule_edit = QLineEdit()
        self._schedule_edit.setPlaceholderText(
            "ISO 8601 publish time, e.g. 2026-07-01T18:00:00Z "
            "(optional)")
        form.addRow("Schedule", self._schedule_edit)
        meta_scroll.setWidget(meta_inner)
        outer.addWidget(meta_scroll, stretch=1)

        # ── Bottom: progress + action buttons ────────────────────
        self._progress = QProgressBar()
        self._progress.setRange(0, 0)
        self._progress.setVisible(False)
        outer.addWidget(self._progress)
        self._status_label = QLabel("")
        self._status_label.setStyleSheet(
            "color: #6b7280; font-size: 11px;")
        self._status_label.setWordWrap(True)
        outer.addWidget(self._status_label)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Close)
        self._upload_btn = QPushButton("📤 Upload")
        self._upload_btn.clicked.connect(self._on_upload_clicked)
        buttons.addButton(
            self._upload_btn,
            QDialogButtonBox.ButtonRole.AcceptRole)
        buttons.rejected.connect(self.close)
        outer.addWidget(buttons)

    # ------------------------------------------------------------------
    # Platform-driven refresh
    # ------------------------------------------------------------------
    def _current_platform(self) -> Optional[SocialPlatform]:
        name = self._platform_combo.currentData()
        for p in self._platforms:
            if p.name == name:
                return p
        return None

    def _refresh_for_platform(self) -> None:
        p = self._current_platform()
        if p is None:
            return
        # Categories.
        self._category_combo.blockSignals(True)
        self._category_combo.clear()
        if p.categories:
            for c in p.categories:
                self._category_combo.addItem(c, c)
            self._category_combo.setEnabled(True)
        else:
            self._category_combo.addItem("(not used)", "")
            self._category_combo.setEnabled(False)
        self._category_combo.blockSignals(False)
        # Sign-in button is meaningful only when an OAuth code-
        # exchange entry point exists (TikTok) — YouTube grants
        # land via the upload call itself, so we hide the button
        # there. Detect by attribute name.
        self._signin_btn.setVisible(hasattr(p, "exchange_code"))
        # Hint about install / aspect / duration / credential
        # readiness.
        bits = []
        if not p.is_installed():
            bits.append("⚠ Needs install — see ☎️ help.")
            bits.append(p.install_instructions().splitlines()[0]
                        if p.install_instructions() else "")
        if p.aspect_hint:
            bits.append(f"Aspect: {p.aspect_hint}")
        if p.max_duration_seconds:
            mins = int(p.max_duration_seconds // 60)
            bits.append(f"Max length: {mins} min")
        bits.append(
            "✓ Credentials present"
            if p.has_credentials()
            else "🔑 No credentials yet — open Credentials…")
        self._platform_status_label.setText("  ·  ".join(bits))
        # Disable Upload while a worker is running OR when
        # credentials missing.
        self._upload_btn.setEnabled(
            p.is_installed() and p.has_credentials())

    def _pick_thumbnail(self) -> None:
        picked, _ = QFileDialog.getOpenFileName(
            self, "Pick a thumbnail", "",
            "Images (*.png *.jpg *.jpeg *.webp)")
        if picked:
            self._thumbnail_edit.setText(picked)

    # ------------------------------------------------------------------
    # Credentials dialog
    # ------------------------------------------------------------------
    def _open_credentials_dialog(self) -> None:
        p = self._current_platform()
        if p is None:
            return
        dlg = QDialog(self)
        dlg.setWindowTitle(f"{p.label} credentials")
        dlg.setModal(True)
        dlg.resize(540, 360)
        v = QVBoxLayout(dlg)
        v.addWidget(QLabel(
            f"<b>{p.label}</b> credentials. "
            "Stored in your system keychain — never written to "
            "disk."))
        if p.install_instructions():
            help_label = QLabel(p.install_instructions())
            help_label.setWordWrap(True)
            help_label.setStyleSheet(
                "color: #6b7280; font-size: 11px; "
                "background: #f3f4f6; padding: 6px; "
                "border-radius: 4px;")
            v.addWidget(help_label)
        form = QFormLayout()
        edits = {}
        for field in p.credential_fields:
            edit = QLineEdit()
            if field.secret:
                edit.setEchoMode(QLineEdit.EchoMode.Password)
            existing = p.get_credential(field.key) or ""
            edit.setText(existing)
            if field.help:
                edit.setToolTip(field.help)
            form.addRow(field.label, edit)
            edits[field.key] = edit
        v.addLayout(form)
        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel)
        v.addWidget(btns)

        def _save():
            ok_all = True
            for k, e in edits.items():
                if not p.store_credential(k, e.text().strip()):
                    ok_all = False
            if not ok_all:
                QMessageBox.warning(
                    dlg, "Some credentials didn't save",
                    "Check the keychain permissions and try "
                    "again. The dialog stays open so you don't "
                    "lose what you pasted.")
                return
            dlg.accept()
            self._refresh_for_platform()
            QMessageBox.information(
                self, "Credentials saved",
                f"Saved {p.label} credentials.")

        btns.accepted.connect(_save)
        btns.rejected.connect(dlg.reject)
        dlg.exec()

    # ------------------------------------------------------------------
    # Sign-in (OAuth code-exchange platforms like TikTok)
    # ------------------------------------------------------------------
    def _on_signin_clicked(self) -> None:
        p = self._current_platform()
        if p is None or not hasattr(p, "exchange_code"):
            return
        if not p.has_credentials():
            QMessageBox.information(
                self, "Add credentials first",
                "Open 🔑 Credentials… and paste the client key "
                "and secret before signing in.")
            return
        # Ask the writer for a redirect URI — TikTok requires
        # HTTPS so the writer needs to register one on the
        # developer console. We default to a localhost callback
        # they can override.
        redirect_uri, ok = QInputDialog.getText(
            self, "OAuth redirect URI",
            "Paste your registered redirect URI:",
            text="https://localhost/")
        if not ok or not redirect_uri:
            return
        url = p.auth_url(redirect_uri)
        from PyQt6.QtGui import QDesktopServices
        from PyQt6.QtCore import QUrl
        QDesktopServices.openUrl(QUrl(url))
        QMessageBox.information(
            self, "Grant access in your browser",
            "Your browser opened to the platform's grant page. "
            "After approving, the platform will redirect you to "
            "the redirect URI. Copy the FULL URL from your "
            "browser's address bar and paste it on the next step.")
        full_url, ok = QInputDialog.getText(
            self, "Paste the redirected URL",
            "Paste the URL the platform redirected you to:")
        if not ok or not full_url:
            return
        from urllib.parse import urlparse, parse_qs
        try:
            qs = parse_qs(urlparse(full_url).query)
        except Exception:
            qs = {}
        code = (qs.get("code") or [""])[0]
        if not code:
            QMessageBox.warning(
                self, "No code in URL",
                "Couldn't find a 'code' query parameter in that "
                "URL. Try again — the URL must be the one the "
                "platform redirected you to immediately after "
                "the grant.")
            return
        if p.exchange_code(code, redirect_uri):
            QMessageBox.information(
                self, "Signed in",
                f"Saved {p.label} access + refresh tokens.")
        else:
            QMessageBox.warning(
                self, "Token exchange failed",
                "The platform refused the code. Double-check "
                "the redirect URI matches exactly what you "
                "registered, then try again.")
        self._refresh_for_platform()

    # ------------------------------------------------------------------
    # Upload
    # ------------------------------------------------------------------
    def _on_upload_clicked(self) -> None:
        p = self._current_platform()
        if p is None:
            return
        title = self._title_edit.text().strip()
        if not title:
            QMessageBox.information(
                self, "Title required",
                "Set a title before uploading.")
            return
        tags = [
            t.strip()
            for t in self._tags_edit.text().split(",")
            if t.strip()]
        thumb = self._thumbnail_edit.text().strip()
        privacy_val = (
            self._privacy_combo.currentData() or "private")
        try:
            privacy = Privacy(privacy_val)
        except ValueError:
            privacy = Privacy.PRIVATE
        metadata = UploadMetadata(
            title=title,
            description=(
                self._description_edit.toPlainText().strip()),
            tags=tags,
            privacy=privacy,
            category=(
                self._category_combo.currentData() or ""),
            language=self._language_edit.text().strip(),
            thumbnail_path=(Path(thumb) if thumb else None),
            schedule_time_iso=(
                self._schedule_edit.text().strip()))
        request = UploadRequest(
            video_path=self._video_path, metadata=metadata)
        self._upload_btn.setEnabled(False)
        self._progress.setVisible(True)
        self._status_label.setText(
            f"Uploading to {p.label}… (this can take a while)")
        worker = _UploadWorker(p, request, self)
        worker.finished_result.connect(self._on_upload_done)
        worker.finished.connect(worker.deleteLater)
        self._worker = worker
        worker.start()

    def _on_upload_done(self, result) -> None:
        self._progress.setVisible(False)
        self._upload_btn.setEnabled(True)
        if not result.success:
            self._status_label.setText(
                f"⚠ Upload failed: {result.error}")
            QMessageBox.warning(
                self, "Upload failed", result.error)
            return
        self._status_label.setText(
            f"✓ Uploaded. {result.remote_url or result.remote_id}")
        if result.remote_url:
            QMessageBox.information(
                self, "Uploaded",
                f"{result.platform} accepted the upload:\n\n"
                f"{result.remote_url}")
        else:
            QMessageBox.information(
                self, "Uploaded",
                f"{result.platform} accepted the upload. "
                f"Reference id: {result.remote_id}")
