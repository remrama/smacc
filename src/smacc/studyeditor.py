"""The Study Editor: author a SMACC study file without any hardware.

A launcher tool (#301) that edits a :class:`~smacc.studyconfig.StudyConfig` — the
pure model of a ``.smacc`` — through per-section forms, and loads/saves it with
:mod:`smacc.settings` so files stay byte-compatible with what a live session
writes. It replaces the old editor, which ran the session window in a stripped
``headless`` mode and reused the run-time panels to author settings.

It is **hardware-free by construction**: this module imports none of the session,
the run-time panels, ``sounddevice`` or ``pylsl`` (enforced by the import-linter
contract in ``pyproject.toml``), so no code path here can open an audio stream,
meter a microphone, or fire a marker. Authoring a study never touches the rig: the
machine-local equipment→device bindings live in the Rig setup tool (#300), and cue
audition happens only in a live session.

The window is a navigation tree of study sections beside a stacked panel of forms.
This shell wires the file lifecycle (load/save/import, unsaved-changes prompt) over
the model; the per-section forms are filled in incrementally (#301).
"""

from __future__ import annotations

from pathlib import Path

import yaml
from PyQt6 import QtCore, QtGui, QtWidgets

from . import bids, settings
from .dialogs import SessionInfoDialog, ask_initial_or_final
from .paths import DEFAULT_DATA_DIR, LOGO_PATH, is_default_settings
from .studyconfig import StudyConfig
from .studyforms import (
    AudioCuesForm,
    BiocalsForm,
    DataDirectoryForm,
    InterfaceForm,
    MarkersForm,
    NoiseForm,
    RoutingForm,
    SectionForm,
    SurveysForm,
    VisualCuesForm,
    section_title,
)
from .toolwindow import ToolWindow

# The study sections shown in the navigation tree, in authoring order. Each gets a
# form page (those without one yet show a placeholder).
_SECTIONS: tuple[tuple[str, str], ...] = (
    ("data", "Data directory"),
    ("routing", "Routing"),
    ("audio", "Audio cues"),
    ("visual", "Visual cues"),
    ("noise", "Noise"),
    ("biocals", "Biocals"),
    ("markers", "Markers"),
    ("surveys", "Surveys"),
    ("interface", "Interface"),
)

# The form class for each section that has one (the rest fall back to a placeholder).
_FORM_TYPES: dict[str, type[SectionForm]] = {
    "data": DataDirectoryForm,
    "routing": RoutingForm,
    "audio": AudioCuesForm,
    "visual": VisualCuesForm,
    "noise": NoiseForm,
    "biocals": BiocalsForm,
    "markers": MarkersForm,
    "surveys": SurveysForm,
    "interface": InterfaceForm,
}

# Study metadata rides at the file envelope, not inside StudyConfig (so one config
# re-runs under a new subject); the editor edits these three via Session info.
_METADATA_KEYS = ("subject", "session", "notes")


class StudyEditorWindow(ToolWindow):
    """Author a SMACC study file (a :class:`StudyConfig`) with no hardware attached."""

    def __init__(self, settings_path: str | None = None) -> None:
        super().__init__()
        self.settings_path = settings_path
        self.metadata: dict = dict.fromkeys(_METADATA_KEYS, "")
        self.config = StudyConfig()
        # Where Save-As defaults and Import dialogs open; updated from a loaded file.
        self.data_dir = Path(DEFAULT_DATA_DIR)
        self._pages: dict[str, QtWidgets.QWidget] = {}
        self._forms: dict[str, SectionForm] = {}

        self.setWindowTitle("SMACC — Editor")
        if LOGO_PATH.is_file():
            self.setWindowIcon(QtGui.QIcon(str(LOGO_PATH)))
        self._build_menu()
        self.setCentralWidget(self._build_body())  # populates self._forms
        self.statusBar()

        if settings_path:
            self._load_file(settings_path)  # -> _adopt_settings -> _load_forms
        else:
            self._load_forms()  # populate the forms from the default config
        # The clean baseline: closing now (or after undoing every edit) prompts for
        # nothing. Compared as serialized bytes, never widget identity (see _snapshot).
        self._saved_snapshot = self._snapshot()
        self.show()

    # ----- construction -----------------------------------------------------

    def _build_menu(self) -> None:
        menu_bar = self.menuBar()
        assert menu_bar is not None
        file_menu = menu_bar.addMenu("&File")
        assert file_menu is not None

        save = QtGui.QAction("&Save SMACC file", self)
        save.setShortcut("Ctrl+S")
        save.setStatusTip("Save to the current SMACC file (or choose a name if new).")
        save.triggered.connect(self.save_in_place)
        save_as = QtGui.QAction("Save SMACC file &as…", self)
        save_as.setStatusTip("Save these settings to a new SMACC file.")
        save_as.triggered.connect(self.save_as)
        import_smacc = QtGui.QAction("&Import SMACC file…", self)
        import_smacc.setStatusTip(
            "Load another SMACC file's settings into the editor as a starting point."
        )
        import_smacc.triggered.connect(self.import_smacc)
        import_log = QtGui.QAction("Import settings from &log…", self)
        import_log.setStatusTip(
            "Load the settings recorded in a SMACC .log into the editor."
        )
        import_log.triggered.connect(self.import_from_log)
        for action in (save, save_as, import_smacc, import_log):
            file_menu.addAction(action)

        file_menu.addSeparator()
        info = QtGui.QAction("Session &info…", self)
        info.setStatusTip(
            "Edit optional subject/session/notes metadata saved with the study."
        )
        info.triggered.connect(self.edit_metadata)
        file_menu.addAction(info)

        file_menu.addSeparator()
        close = QtGui.QAction("&Close editor", self)
        close.setShortcut("Ctrl+W")
        close.setStatusTip("Close the editor and return to the SMACC Launcher.")
        close.triggered.connect(self.close)
        file_menu.addAction(close)

    def _build_body(self) -> QtWidgets.QWidget:
        """A navigation tree of sections beside a stacked panel of forms."""
        self.tree = QtWidgets.QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setStatusTip("Choose a part of the study to edit.")
        self.stack = QtWidgets.QStackedWidget()
        for key, label in _SECTIONS:
            item = QtWidgets.QTreeWidgetItem([label])
            item.setData(0, QtCore.Qt.ItemDataRole.UserRole, key)
            self.tree.addTopLevelItem(item)
            form_type = _FORM_TYPES.get(key)
            if form_type is None:
                page: QtWidgets.QWidget = self._placeholder_page(label)
            else:
                form = form_type()
                self._forms[key] = form
                page = form
            self._pages[key] = page
            self.stack.addWidget(page)
        self.tree.currentItemChanged.connect(self._on_section_changed)

        splitter = QtWidgets.QSplitter()
        splitter.addWidget(self.tree)
        splitter.addWidget(self.stack)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([180, 520])
        self.tree.setCurrentItem(self.tree.topLevelItem(0))
        return splitter

    def _placeholder_page(self, label: str) -> QtWidgets.QWidget:
        """A stand-in page until the section's form lands (#301)."""
        page = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(page)
        layout.addWidget(section_title(label))
        note = QtWidgets.QLabel(f"The {label} form goes here.")
        note.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(note)
        layout.addStretch(1)
        return page

    def _on_section_changed(
        self,
        current: QtWidgets.QTreeWidgetItem | None,
        _previous: QtWidgets.QTreeWidgetItem | None,
    ) -> None:
        if current is None:
            return
        key = current.data(0, QtCore.Qt.ItemDataRole.UserRole)
        self.stack.setCurrentWidget(self._pages[key])

    def _load_forms(self) -> None:
        """Populate every section form from the current model."""
        for form in self._forms.values():
            form.load(self.config)

    def _commit_forms(self) -> None:
        """Write every section form's widget values back into the model.

        The single sync point between widgets and ``self.config``; the model is the
        source of truth for save and unsaved-change detection, so this runs before
        either reads it.
        """
        for form in self._forms.values():
            form.commit(self.config)

    # ----- load / import ----------------------------------------------------

    def _load_file(self, path: str) -> None:
        """Load the file given at construction and adopt it as the initial study."""
        try:
            state, metadata = settings.load_settings(path)
            state = settings.resolve_paths(state, Path(path).parent)
        except (OSError, ValueError) as exc:
            self._error("Could not open settings file.", str(exc))
            return
        self.data_dir = settings.data_directory_of(
            state, Path(path).parent, DEFAULT_DATA_DIR
        )
        self._adopt_settings(state, metadata)

    def _adopt_settings(self, state: dict, metadata: dict) -> None:
        """Replace the model from a settings mapping and adopt the file's metadata.

        Unlike a live session (whose metadata comes from the start-of-session
        prompt), the editor has no prompt, so it takes the loaded file's values —
        but only non-empty ones, so importing a study that left them blank doesn't
        wipe what the operator entered via Session info.
        """
        self.config = StudyConfig.from_settings_dict(state)
        for key in _METADATA_KEYS:
            value = metadata.get(key)
            if value:
                self.metadata[key] = value
        self._load_forms()

    def import_smacc(self) -> None:
        """Load another .smacc file's settings into the editor as a starting point."""
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "Open SMACC file", str(self.data_dir), "SMACC file (*.smacc)"
        )
        if not path:
            return
        try:
            state, metadata = settings.load_settings(path)
            state = settings.resolve_paths(state, Path(path).parent)
        except (OSError, ValueError) as exc:
            self._error("Could not open settings.", str(exc))
            return
        self._adopt_settings(state, metadata)

    def import_from_log(self) -> None:
        """Load the initial or final settings recorded in a SMACC .log file."""
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "Load settings from log", str(self.data_dir), "SMACC log (*.log)"
        )
        if not path:
            return
        which = ask_initial_or_final(self, title="Load settings from log")
        if which is None:
            return
        try:
            log_text = Path(path).read_text(encoding="utf-8")
        except OSError as exc:
            self._error("Could not read log.", str(exc))
            return
        payload = bids.extract_settings_from_log(log_text, which)
        if payload is None:
            self._error(
                f"No {which} settings found in that log.",
                "The log may predate settings recording, or the session may have "
                "ended before its final settings were written.",
            )
            return
        try:
            state, metadata = settings.parse_settings_mapping(payload)
        except ValueError as exc:
            self._error("Could not load settings from log.", str(exc))
            return
        self._adopt_settings(state, metadata)

    # ----- save -------------------------------------------------------------

    def save_in_place(self) -> bool:
        """Save to the current file without prompting; fall back to Save-As if new.

        SMACC's seeded ``default.smacc`` is a read-only template, so saving it
        redirects to Save-As (it stays a known-good starting point).
        """
        if self.settings_path and not is_default_settings(self.settings_path):
            return self._write(self.settings_path)
        return self.save_as()

    def save_as(self) -> bool:
        """Prompt for a path and write the settings there. Returns success."""
        if self.settings_path and not is_default_settings(self.settings_path):
            default = self.settings_path
        else:
            default = str(self.data_dir / "settings.smacc")
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, "Save SMACC file", str(default), "SMACC file (*.smacc)"
        )
        if not path:
            return False
        return self._write(path)

    def _write(self, path: str) -> bool:
        """Write the current model to ``path`` (relativizing media paths). Returns success."""
        if is_default_settings(path):
            self._error(
                "Can’t overwrite the default settings.",
                "default.smacc is SMACC's built-in template and stays read-only so it "
                "remains a reliable starting point. Save your changes to a new .smacc "
                "file instead.",
            )
            return False
        self._commit_forms()  # fold the latest widget edits into the model
        portable = settings.relativize_paths(
            self.config.to_settings_dict(), Path(path).parent
        )
        try:
            settings.save_settings(path, portable, self.metadata)
        except (OSError, ValueError) as exc:
            self._error("Could not save settings.", str(exc))
            return False
        self.settings_path = path  # subsequent saves update this file
        self._saved_snapshot = self._snapshot()  # the editor is clean again
        bar = self.statusBar()
        if bar is not None:
            bar.showMessage(f"Saved settings to {Path(path).name}", 5000)
        return True

    # ----- metadata ---------------------------------------------------------

    def edit_metadata(self) -> None:
        """Edit the study's optional subject/session/notes metadata."""
        dialog = SessionInfoDialog(
            self.metadata.get("subject", ""),
            self.metadata.get("session", ""),
            self.metadata.get("notes", ""),
            parent=self,
        )
        if dialog.exec():
            subject, session, notes = dialog.get_inputs()
            self.metadata["subject"] = subject
            self.metadata["session"] = session
            self.metadata["notes"] = notes

    # ----- unsaved-changes / close ------------------------------------------

    def _snapshot(self) -> str:
        """A stable serialization of the savable state, for unsaved-changes detection.

        Compared as the *serialized* study (model → settings dict → YAML) plus
        metadata, never widget or model identity: the model's ``None`` sentinels
        (``biocals.rows``, the chat-preset lists) mean two equal studies can differ
        as objects, so only the bytes that would be written are authoritative (#301).
        """
        self._commit_forms()  # reflect the live widget state before serializing
        payload = {
            "settings": self.config.to_settings_dict(),
            "metadata": dict(self.metadata),
        }
        return yaml.safe_dump(payload, sort_keys=False, allow_unicode=True)

    def has_unsaved_changes(self) -> bool:
        """True if the study differs from what was last loaded or saved."""
        return self._snapshot() != self._saved_snapshot

    def closeEvent(self, event: QtGui.QCloseEvent | None) -> None:
        """Prompt to save unsaved changes, then close and return to the launcher."""
        if self.has_unsaved_changes():
            box = QtWidgets.QMessageBox(self)
            box.setWindowTitle("Close editor")
            box.setText("Save changes to the SMACC file before closing?")
            box.setStandardButtons(
                QtWidgets.QMessageBox.StandardButton.Save
                | QtWidgets.QMessageBox.StandardButton.Discard
                | QtWidgets.QMessageBox.StandardButton.Cancel
            )
            box.setDefaultButton(QtWidgets.QMessageBox.StandardButton.Save)
            choice = box.exec()
            if choice == QtWidgets.QMessageBox.StandardButton.Cancel:
                if event is not None:
                    event.ignore()
                return
            if (
                choice == QtWidgets.QMessageBox.StandardButton.Save
                and not self.save_in_place()
            ):
                if event is not None:
                    event.ignore()  # save cancelled/failed → keep the editor open
                return
        if event is not None:
            event.accept()
        self.closed.emit()

    # ----- helpers ----------------------------------------------------------

    def _error(self, text: str, detail: str = "") -> None:
        """Show a non-fatal warning dialog (the editor has no session log to write to)."""
        box = QtWidgets.QMessageBox(self)
        box.setIcon(QtWidgets.QMessageBox.Icon.Warning)
        box.setWindowTitle("SMACC Editor")
        box.setText(text)
        if detail:
            box.setInformativeText(detail)
        box.exec()
