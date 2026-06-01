"""Pre-apply preview dialog for LLM-package imports.

Owns an LLMPackageImporter, rebuilds the ImportPlan whenever the user
toggles between Update and Overwrite mode, and shows the resulting
adds / updates / deletes / warnings / errors before the user confirms.

The dialog never applies the plan itself — that responsibility stays
with the caller so the orchestration around UI refresh / undo / etc.
lives in main_window where it belongs.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import (
    QApplication, QButtonGroup, QDialog, QDialogButtonBox, QGroupBox,
    QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QPushButton,
    QRadioButton, QTextEdit, QVBoxLayout, QWidget,
)

from src.export.llm_package import (
    ImportMode, ImportPlan, LLMPackageImporter,
)
from src.models.project import WriterProject


class LLMPackageImportDialog(QDialog):
    """Modal preview before applying an LLM-edited package.

    Usage:
        dlg = LLMPackageImportDialog(pkg_dir, project, parent)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            plan = dlg.get_plan()
            result = apply_import_plan(project, plan)
    """

    def __init__(
        self,
        source_dir: Path,
        project: WriterProject,
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self.setWindowTitle("Import LLM Package")
        self.setModal(True)
        self.resize(720, 620)

        self._source_dir = Path(source_dir)
        self._project = project
        self._importer = LLMPackageImporter(self._source_dir)
        self._plan: Optional[ImportPlan] = None
        self._build_ui()
        self._rebuild_plan()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def get_plan(self) -> Optional[ImportPlan]:
        """The plan reflecting the user's currently-selected mode.

        Returns the same plan after ``exec()`` returns Accepted — the
        caller passes this to ``apply_import_plan``. ``None`` only
        when the source directory was bad from the start.
        """
        return self._plan

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)

        # Path header — reminds the user which folder they're importing
        layout.addWidget(QLabel(
            f"<b>Package:</b> {self._source_dir}"))

        # Mode selector. Two radio buttons with descriptions inline so
        # the user understands the consequence before picking.
        mode_box = QGroupBox("Import mode")
        mode_layout = QVBoxLayout(mode_box)

        self._mode_group = QButtonGroup(self)
        self._update_radio = QRadioButton(
            "Update — additive (safe). New entities in the package "
            "are created, existing entities are updated by id, "
            "entities not in the package are left untouched.")
        self._overwrite_radio = QRadioButton(
            "Overwrite — replace non-chapter element sets. New "
            "entities are still created and existing ones updated; "
            "any entity missing from the package is deleted "
            "(except chapters — chapter prose is always preserved).")
        self._update_radio.setChecked(True)
        self._mode_group.addButton(self._update_radio)
        self._mode_group.addButton(self._overwrite_radio)
        mode_layout.addWidget(self._update_radio)
        mode_layout.addWidget(self._overwrite_radio)
        layout.addWidget(mode_box)

        # Always-visible reassurance about the chapter-prose guarantee
        # plus a clear notice about the plot-canonical rule (which
        # applies in BOTH modes if any plot events are in the
        # package). Stacking these so users see what's protected and
        # what could be replaced before they pick a mode.
        prose_note = QLabel(
            "<i>Your chapter prose is never written by import — "
            "in either mode.</i><br>"
            "<i>Main-plot events (<code>plot/events/</code>) are "
            "treated as canonical whenever the package contains any "
            "of them — events in your project missing from the "
            "package will be deleted, in either mode. If the package "
            "contains no plot events, your plot is left untouched.</i>")
        prose_note.setWordWrap(True)
        layout.addWidget(prose_note)

        # Summary text — counts, mode-aware.
        self._summary_label = QLabel("")
        self._summary_label.setWordWrap(True)
        self._summary_label.setTextFormat(Qt.TextFormat.RichText)
        layout.addWidget(self._summary_label)

        # Side-by-side lists: changes vs. issues.
        lists_row = QHBoxLayout()

        changes_box = QGroupBox("Changes")
        changes_layout = QVBoxLayout(changes_box)
        self._changes_list = QListWidget()
        changes_layout.addWidget(self._changes_list)
        lists_row.addWidget(changes_box, stretch=2)

        issues_box = QGroupBox("Warnings && errors")
        issues_layout = QVBoxLayout(issues_box)
        self._issues_list = QListWidget()
        issues_layout.addWidget(self._issues_list)
        # Copy-to-clipboard button: lets the user paste the full set
        # of issues back into the LLM conversation to ask for fixes.
        # Heavily used when the LLM returns malformed JSON.
        copy_row = QHBoxLayout()
        self._copy_issues_btn = QPushButton(
            "Copy issues to clipboard")
        self._copy_issues_btn.setToolTip(
            "Copy every error and warning as plain text. Paste back "
            "into your LLM conversation to ask for corrected JSON "
            "files.")
        self._copy_issues_btn.clicked.connect(
            self._copy_issues_to_clipboard)
        copy_row.addWidget(self._copy_issues_btn)
        copy_row.addStretch()
        issues_layout.addLayout(copy_row)
        lists_row.addWidget(issues_box, stretch=1)

        layout.addLayout(lists_row, stretch=1)

        # OK / Cancel. OK is disabled when the plan has errors.
        self._buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel)
        self._buttons.button(
            QDialogButtonBox.StandardButton.Ok).setText("Apply")
        self._buttons.accepted.connect(self.accept)
        self._buttons.rejected.connect(self.reject)
        layout.addWidget(self._buttons)

        # Rebuild plan whenever the mode changes.
        self._update_radio.toggled.connect(self._rebuild_plan)
        self._overwrite_radio.toggled.connect(self._rebuild_plan)

    # ------------------------------------------------------------------
    # Plan rebuild + render
    # ------------------------------------------------------------------
    def _current_mode(self) -> ImportMode:
        return (ImportMode.OVERWRITE
                if self._overwrite_radio.isChecked()
                else ImportMode.UPDATE)

    def _rebuild_plan(self) -> None:
        mode = self._current_mode()
        try:
            self._plan = self._importer.build_plan(
                self._project, mode=mode)
        except Exception as e:
            # A truly fatal error (corrupt directory, etc.) — surface
            # it via the issues list rather than crashing the dialog.
            self._plan = None
            self._summary_label.setText(
                "<b style='color:red'>Could not build plan:</b> "
                f"{e}")
            self._changes_list.clear()
            self._issues_list.clear()
            self._issues_list.addItem(str(e))
            self._buttons.button(
                QDialogButtonBox.StandardButton.Ok).setEnabled(False)
            return
        self._render_plan()

    def _render_plan(self) -> None:
        plan = self._plan
        if plan is None:
            return
        summary = plan.summary()

        # Header line: counts.
        adds = summary["adds"]
        updates = summary["updates"]
        deletes = summary["deletes"]
        errors = summary["errors"]
        warnings = summary["warnings"]
        mode_str = summary["mode"].upper()

        head = (
            f"<b>Mode:</b> {mode_str} &nbsp; "
            f"<b>Adds:</b> {adds} &nbsp; "
            f"<b>Updates:</b> {updates} &nbsp; "
            f"<b>Deletes:</b> {deletes} &nbsp; "
            f"<b>Warnings:</b> {warnings}")
        if errors:
            head += (
                f" &nbsp; <span style='color:red'>"
                f"<b>Errors:</b> {errors}</span>")
        self._summary_label.setText(head)

        # Changes list — adds, updates, deletes, all labelled.
        self._changes_list.clear()
        for entry in plan.entries:
            tag = "+ add" if entry.action == "add" else "~ update"
            label = (
                f"{tag}  [{entry.entity_type}] "
                f"{entry.entity_id}  "
                f"({entry.file_path})")
            item = QListWidgetItem(label)
            if entry.action == "add":
                item.setForeground(Qt.GlobalColor.darkGreen)
            self._changes_list.addItem(item)
        for kind, ent_id in plan.to_delete:
            item = QListWidgetItem(
                f"- delete  [{kind}] {ent_id}")
            item.setForeground(Qt.GlobalColor.darkRed)
            self._changes_list.addItem(item)

        # Issues list — errors first (red), warnings after.
        self._issues_list.clear()
        for err in plan.errors:
            item = QListWidgetItem(f"ERROR  {err}")
            item.setForeground(Qt.GlobalColor.red)
            self._issues_list.addItem(item)
        for warn in plan.warnings:
            item = QListWidgetItem(f"warning  {warn}")
            self._issues_list.addItem(item)

        # Apply button gated by plan.errors.
        ok_btn = self._buttons.button(
            QDialogButtonBox.StandardButton.Ok)
        ok_btn.setEnabled(plan.is_applyable)
        if not plan.is_applyable:
            ok_btn.setToolTip(
                f"Cannot apply: {errors} error(s) must be fixed first.")
        else:
            ok_btn.setToolTip("")

        # Update the copy button: show the total issue count, disable
        # when there's nothing to copy.
        total_issues = len(plan.errors) + len(plan.warnings)
        self._copy_issues_btn.setEnabled(total_issues > 0)
        if total_issues > 0:
            self._copy_issues_btn.setText(
                f"Copy issues to clipboard ({total_issues})")
        else:
            self._copy_issues_btn.setText("Copy issues to clipboard")

    # ------------------------------------------------------------------
    # Clipboard
    # ------------------------------------------------------------------
    def _build_issues_text(self) -> str:
        """Render the plan's errors and warnings as paste-ready text.

        Returns "" when there is nothing to copy. Includes a short
        preface so the user can paste straight into the LLM
        conversation that produced the package; the LLM then has the
        context to fix and resend.

        Falls back to whatever is currently in the issues list widget
        when ``self._plan`` is None — that happens only on a fatal
        plan-build failure (e.g., corrupt source directory), in
        which case the dialog already populated the widget with the
        raw exception string.
        """
        plan = self._plan
        if plan is None:
            items = [self._issues_list.item(i).text()
                     for i in range(self._issues_list.count())]
            return "\n".join(items)
        if not (plan.errors or plan.warnings):
            return ""
        sections: list = []
        sections.append(
            "WritingAid could not fully import the JSON package you "
            "returned. Please fix each item below and resend the "
            "corrected files. Errors block the import; warnings are "
            "advisory but worth addressing.")
        sections.append("")
        if plan.errors:
            sections.append(f"## ERRORS ({len(plan.errors)})")
            for err in plan.errors:
                sections.append(f"- {err}")
            sections.append("")
        if plan.warnings:
            sections.append(f"## WARNINGS ({len(plan.warnings)})")
            for warn in plan.warnings:
                sections.append(f"- {warn}")
        return "\n".join(sections).rstrip() + "\n"

    def _copy_issues_to_clipboard(self) -> None:
        text = self._build_issues_text()
        if not text:
            return
        QApplication.clipboard().setText(text)
        # Brief visual confirmation. Restore the original label after
        # 1.5s so the user knows the click registered without needing
        # a separate status bar.
        original = self._copy_issues_btn.text()
        self._copy_issues_btn.setText("Copied to clipboard")
        QTimer.singleShot(
            1500,
            lambda: self._copy_issues_btn.setText(original))
