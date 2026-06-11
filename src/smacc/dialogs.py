"""Dialogs shown by SMACC outside the main window."""

from typing import cast

from PyQt6 import QtCore, QtGui, QtWidgets

from . import config, events, hue, surveys
from .utils import normalize_survey_url


def ask_initial_or_final(parent=None, title: str = "Settings snapshot") -> str | None:
    """Ask whether to use the log's ``initial`` or ``final`` settings block.

    Returns ``"initial"``/``"final"``, or ``None`` if cancelled. Shared by loading a
    study from a log (session window) and recovering one (analyze window).
    """
    box = QtWidgets.QMessageBox(parent)
    box.setWindowTitle(title)
    box.setText("Use which settings snapshot from the log?")
    initial_btn = box.addButton("Initial", QtWidgets.QMessageBox.ButtonRole.AcceptRole)
    final_btn = box.addButton("Final", QtWidgets.QMessageBox.ButtonRole.AcceptRole)
    box.addButton(QtWidgets.QMessageBox.StandardButton.Cancel)
    box.exec()
    clicked = box.clickedButton()
    if clicked is initial_btn:
        return "initial"
    if clicked is final_btn:
        return "final"
    return None


class SessionInfoDialog(QtWidgets.QDialog):
    """Edit the session's optional metadata: subject, session, and free-text notes.

    All fields are optional and blank by default; they're recorded inside the log
    and exports rather than driving filenames. Opened on demand from
    File -> Session info….
    """

    def __init__(
        self,
        subject: str = "",
        session: str = "",
        notes: str = "",
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Session information")
        # Removes the default "What's this?" question mark icon from the titlebar.
        self.setWindowFlags(
            self.windowFlags() ^ QtCore.Qt.WindowType.WindowContextHelpButtonHint
        )
        # Create subject and session text inputs, prefilled from current metadata.
        self.subject_id = QtWidgets.QLineEdit(self)
        self.session_id = QtWidgets.QLineEdit(self)
        self.subject_id.setText(subject)
        self.session_id.setText(session)
        self.subject_id.setPlaceholderText("Optional")
        self.session_id.setPlaceholderText("Optional")
        # Allow letters, numbers, underscores, and hyphens, up to 30 characters;
        # empty is allowed since the fields are optional.
        id_validator = QtGui.QRegularExpressionValidator(
            QtCore.QRegularExpression(r"[A-Za-z0-9_-]{0,30}")
        )
        for field in (self.subject_id, self.session_id):
            field.setValidator(id_validator)
            field.setMaxLength(30)
        self.notes = QtWidgets.QLineEdit(self)
        self.notes.setText(notes)
        self.notes.setPlaceholderText("Optional free-text notes")
        # Create buttons to accept values or cancel.
        buttonBox = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.StandardButton.Ok
            | QtWidgets.QDialogButtonBox.StandardButton.Cancel,
            self,
        )
        buttonBox.accepted.connect(self.accept)
        buttonBox.rejected.connect(self.reject)
        # Put everything in a layout.
        layout = QtWidgets.QFormLayout(self)
        layout.addRow("Subject ID", self.subject_id)
        layout.addRow("Session ID", self.session_id)
        layout.addRow("Notes", self.notes)
        layout.addWidget(buttonBox)

    def get_inputs(self) -> tuple[str, str, str]:
        """Return the edited subject, session, and notes as strings."""
        return self.subject_id.text(), self.session_id.text(), self.notes.text()


class SurveyDialog(QtWidgets.QDialog):
    """Add or edit a single named *web* survey: a display name and its URL.

    Used by :class:`ManageSurveysDialog` for its URL rows (in-app surveys are
    built/edited with :class:`BuildSurveyDialog` instead). The URL is normalized
    on accept (whitespace trimmed, ``https://`` added when no scheme), and both
    fields are required.
    """

    def __init__(self, name: str = "", url: str = "", parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Survey")
        # Removes the default "What's this?" question mark icon from the titlebar.
        self.setWindowFlags(
            self.windowFlags() ^ QtCore.Qt.WindowType.WindowContextHelpButtonHint
        )
        self.nameEdit = QtWidgets.QLineEdit(self)
        self.nameEdit.setText(name)
        self.nameEdit.setPlaceholderText("e.g. Post-dream survey")
        self.urlEdit = QtWidgets.QLineEdit(self)
        self.urlEdit.setText(url)
        self.urlEdit.setPlaceholderText("https://…")
        buttonBox = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.StandardButton.Ok
            | QtWidgets.QDialogButtonBox.StandardButton.Cancel,
            self,
        )
        buttonBox.accepted.connect(self._on_accept)
        buttonBox.rejected.connect(self.reject)
        layout = QtWidgets.QFormLayout(self)
        layout.addRow("Name", self.nameEdit)
        layout.addRow("URL", self.urlEdit)
        layout.addWidget(buttonBox)

    def _on_accept(self) -> None:
        """Require a name and URL (normalizing the URL) before accepting."""
        name = self.nameEdit.text().strip()
        url = normalize_survey_url(self.urlEdit.text())
        if not name or not url:
            QtWidgets.QMessageBox.warning(
                self, "Survey", "Please enter both a name and a URL."
            )
            return
        self.urlEdit.setText(url)
        self.accept()

    def get_inputs(self) -> tuple[str, str]:
        """Return the entered (name, normalized URL)."""
        return self.nameEdit.text().strip(), normalize_survey_url(self.urlEdit.text())


class BuildSurveyDialog(QtWidgets.QDialog):
    """Create or edit a custom in-app survey (#114).

    Deliberately constrained to the shape of the bundled instruments — one
    shared Likert scale plus a list of item texts — which keeps the builder a
    simple form (anchors and items are typed one per line). Validation is
    delegated to :func:`smacc.surveys.parse_survey_mapping`, the same gate a
    hand-written survey file passes through. The caller reads
    :meth:`get_survey` only when the dialog is accepted.
    """

    def __init__(
        self,
        survey: surveys.SurveyDef | None = None,
        existing_keys: tuple[str, ...] = (),
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Build survey" if survey is None else "Edit survey")
        self.setWindowFlags(
            self.windowFlags() ^ QtCore.Qt.WindowType.WindowContextHelpButtonHint
        )
        # An edited survey keeps its key (it names response files); only a new
        # survey derives one from the name on accept.
        self._key = survey.key if survey is not None else None
        self._existing_keys = set(existing_keys)
        self._survey: surveys.SurveyDef | None = None

        self.nameEdit = QtWidgets.QLineEdit(self)
        self.nameEdit.setPlaceholderText("Short label, e.g. DLQ")
        self.titleEdit = QtWidgets.QLineEdit(self)
        self.titleEdit.setPlaceholderText("Full title (optional; defaults to the name)")
        self.versionEdit = QtWidgets.QLineEdit("1.0", self)
        self.versionEdit.setStatusTip(
            "Content version recorded in every response file; bump it when the "
            "items change."
        )
        self.citationEdit = QtWidgets.QLineEdit(self)
        self.citationEdit.setPlaceholderText("Optional citation")
        self.instructionsEdit = QtWidgets.QPlainTextEdit(self)
        self.instructionsEdit.setPlaceholderText("Optional instructions shown on top")
        self.instructionsEdit.setFixedHeight(64)
        self.minSpin = QtWidgets.QSpinBox(self)
        self.minSpin.setRange(-100, 100)
        self.minSpin.setValue(0)
        self.maxSpin = QtWidgets.QSpinBox(self)
        self.maxSpin.setRange(-100, 100)
        self.maxSpin.setValue(4)
        scaleRow = QtWidgets.QHBoxLayout()
        scaleRow.addWidget(QtWidgets.QLabel("from"))
        scaleRow.addWidget(self.minSpin)
        scaleRow.addWidget(QtWidgets.QLabel("to"))
        scaleRow.addWidget(self.maxSpin)
        scaleRow.addStretch(1)
        self.anchorsEdit = QtWidgets.QPlainTextEdit(self)
        self.anchorsEdit.setPlaceholderText(
            "One label per scale point, in order (optional)"
        )
        self.anchorsEdit.setFixedHeight(96)
        self.itemsEdit = QtWidgets.QPlainTextEdit(self)
        self.itemsEdit.setPlaceholderText("One item per line")

        if survey is not None:
            self.nameEdit.setText(survey.name)
            self.titleEdit.setText(survey.title)
            self.versionEdit.setText(survey.version)
            self.citationEdit.setText(survey.citation)
            self.instructionsEdit.setPlainText(survey.instructions)
            self.minSpin.setValue(survey.scale_min)
            self.maxSpin.setValue(survey.scale_max)
            self.anchorsEdit.setPlainText("\n".join(survey.anchors))
            # The builder only ever opens simple-Likert surveys (the caller
            # guards this), so each item is a plain Likert statement.
            self.itemsEdit.setPlainText("\n".join(it.text for it in survey.items))

        buttonBox = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.StandardButton.Save
            | QtWidgets.QDialogButtonBox.StandardButton.Cancel,
            self,
        )
        buttonBox.accepted.connect(self._on_accept)
        buttonBox.rejected.connect(self.reject)

        form = QtWidgets.QFormLayout(self)
        form.addRow("Name", self.nameEdit)
        form.addRow("Title", self.titleEdit)
        form.addRow("Version", self.versionEdit)
        form.addRow("Citation", self.citationEdit)
        form.addRow("Instructions", self.instructionsEdit)
        form.addRow("Scale", scaleRow)
        form.addRow("Anchors", self.anchorsEdit)
        form.addRow("Items", self.itemsEdit)
        form.addWidget(buttonBox)
        self.resize(520, 620)

    @staticmethod
    def _lines(edit: QtWidgets.QPlainTextEdit) -> list[str]:
        """Non-blank lines of a one-per-line text box, stripped, in order."""
        return [
            line.strip() for line in edit.toPlainText().splitlines() if line.strip()
        ]

    def _unique_key(self, name: str) -> str:
        """Derive a new survey's key from its name, dodging taken keys."""
        base = surveys.slugify_key(name)
        key = base
        suffix = 2
        while key in self._existing_keys:
            key = f"{base}-{suffix}"
            suffix += 1
        return key

    def _on_accept(self) -> None:
        """Assemble the mapping and run it through the shared survey validator."""
        name = self.nameEdit.text().strip()
        mapping = {
            "kind": surveys.KIND,
            "schema_version": surveys.SCHEMA_VERSION,
            "key": self._key or self._unique_key(name or "survey"),
            "name": name,
            "title": self.titleEdit.text().strip(),
            "version": self.versionEdit.text().strip(),
            "citation": self.citationEdit.text().strip(),
            "instructions": self.instructionsEdit.toPlainText().strip(),
            "scale": {
                "min": self.minSpin.value(),
                "max": self.maxSpin.value(),
                "anchors": self._lines(self.anchorsEdit),
            },
            "items": self._lines(self.itemsEdit),
        }
        try:
            self._survey = surveys.parse_survey_mapping(mapping, builtin=False)
        except ValueError as exc:
            QtWidgets.QMessageBox.warning(self, "Build survey", str(exc))
            return
        self.accept()

    def get_survey(self) -> surveys.SurveyDef:
        """Return the validated survey (read only when the dialog is accepted)."""
        assert self._survey is not None  # _on_accept validated before accept()
        return self._survey


class ManageSurveysDialog(QtWidgets.QDialog):
    """Manage every survey the dropdown offers (#114).

    Three kinds of rows: *built-in* surveys (shipped with SMACC; viewable, not
    editable or removable), *custom* surveys (built here; stored as YAML files in
    the SMACC root's surveys folder, so building/editing/removing them applies
    immediately, even if the dialog is later cancelled — ``files_changed`` tells
    the caller to refresh), and *web* survey URLs (saved with the study; the
    caller reads the edited mapping with :meth:`get_options` only on accept).

    Opened from the Dream-recording panel's Manage… button. Constructed without
    survey directories it degrades to the URL-only manager (used in tests).
    """

    def __init__(
        self,
        options: dict[str, str],
        builtin_dir=None,
        user_dir=None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Manage surveys")
        self.setWindowFlags(
            self.windowFlags() ^ QtCore.Qt.WindowType.WindowContextHelpButtonHint
        )
        self.resize(520, 320)
        self._builtin_dir = builtin_dir
        self._user_dir = user_dir
        self.files_changed = False  # any custom-survey file built/edited/removed
        self._previews: list[QtWidgets.QDialog] = []  # keep built-in views alive

        hint = QtWidgets.QLabel(
            "Built-in surveys ship with SMACC and open in a SMACC window; build "
            "your own in the same style, or add a web survey by URL.",
            self,
        )
        hint.setWordWrap(True)

        self.listWidget = QtWidgets.QListWidget(self)
        self.listWidget.itemDoubleClicked.connect(self._view_or_edit_selected)
        self._populate(options)

        addUrlButton = QtWidgets.QPushButton("Add URL…", self)
        addUrlButton.setStatusTip("Add a web survey opened in the browser.")
        addUrlButton.clicked.connect(self._add_url)
        buildButton = QtWidgets.QPushButton("Build survey…", self)
        buildButton.setStatusTip(
            "Create a custom in-app survey (a Likert scale and items)."
        )
        buildButton.clicked.connect(self._build_new)
        buildButton.setEnabled(user_dir is not None)
        editButton = QtWidgets.QPushButton("View/Edit…", self)
        editButton.setStatusTip("View a built-in survey, or edit your own entry.")
        editButton.clicked.connect(self._view_or_edit_selected)
        removeButton = QtWidgets.QPushButton("Remove", self)
        removeButton.setStatusTip("Remove the selected custom survey or URL.")
        removeButton.clicked.connect(self._remove_selected)

        buttonCol = QtWidgets.QVBoxLayout()
        for button in (addUrlButton, buildButton, editButton, removeButton):
            buttonCol.addWidget(button)
        buttonCol.addStretch(1)

        buttonBox = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.StandardButton.Ok
            | QtWidgets.QDialogButtonBox.StandardButton.Cancel,
            self,
        )
        buttonBox.accepted.connect(self.accept)
        buttonBox.rejected.connect(self.reject)

        topRow = QtWidgets.QHBoxLayout()
        topRow.addWidget(self.listWidget, 1)
        topRow.addLayout(buttonCol)
        layout = QtWidgets.QVBoxLayout(self)
        layout.addWidget(hint)
        layout.addLayout(topRow)
        layout.addWidget(buttonBox)

    # ----- list build ---------------------------------------------------------

    def _populate(self, url_options: dict[str, str]) -> None:
        """Rebuild the list: built-ins, then custom surveys, then URL rows."""
        self.listWidget.clear()
        if self._builtin_dir is not None and self._user_dir is not None:
            loaded, problems = surveys.all_surveys(self._builtin_dir, self._user_dir)
            for survey in loaded.values():
                kind = "builtin" if survey.builtin else "custom"
                item = QtWidgets.QListWidgetItem(
                    f"{survey.name} — {'built-in' if survey.builtin else 'custom'} survey"
                )
                item.setToolTip(survey.title)
                item.setData(QtCore.Qt.ItemDataRole.UserRole, (kind, survey))
                self.listWidget.addItem(item)
            for problem in problems:
                broken = QtWidgets.QListWidgetItem(f"⚠ {problem}")
                broken.setFlags(QtCore.Qt.ItemFlag.NoItemFlags)
                self.listWidget.addItem(broken)
        for name, url in url_options.items():
            self._add_url_row(name, url)

    def _reload_surveys(self) -> None:
        """Re-read the survey files, preserving the current URL rows."""
        self._populate(self.get_options())

    def _add_url_row(self, name: str, url: str) -> None:
        """Append a web-survey row labeled ``name — url``."""
        item = QtWidgets.QListWidgetItem(f"{name} — {url}")
        item.setData(QtCore.Qt.ItemDataRole.UserRole, ("url", (name, url)))
        self.listWidget.addItem(item)

    def _selected(self) -> tuple[str, object] | None:
        item = self.listWidget.currentItem()
        if item is None:
            return None
        data = item.data(QtCore.Qt.ItemDataRole.UserRole)
        return data if data else None

    def _survey_keys(self) -> tuple[str, ...]:
        """Every key currently taken (for deriving a fresh builder key)."""
        keys = []
        for i in range(self.listWidget.count()):
            item = self.listWidget.item(i)
            data = item.data(QtCore.Qt.ItemDataRole.UserRole) if item else None
            if data and data[0] in ("builtin", "custom"):
                keys.append(data[1].key)
        return tuple(keys)

    # ----- actions ------------------------------------------------------------

    def _add_url(self) -> None:
        dialog = SurveyDialog(parent=self)
        if dialog.exec():
            name, url = dialog.get_inputs()
            self._add_url_row(name, url)

    def _build_new(self) -> None:
        if self._user_dir is None:
            return
        dialog = BuildSurveyDialog(existing_keys=self._survey_keys(), parent=self)
        if not dialog.exec():
            return
        self._save_custom(dialog.get_survey())

    def _save_custom(self, survey: surveys.SurveyDef) -> None:
        """Write a built/edited custom survey to its YAML and refresh the list."""
        try:
            surveys.save_survey(survey, self._user_dir)
        except OSError as exc:
            QtWidgets.QMessageBox.warning(
                self, "Build survey", f"Could not save the survey file:\n{exc}"
            )
            return
        self.files_changed = True
        self._reload_surveys()

    def _view_or_edit_selected(self) -> None:
        selected = self._selected()
        if selected is None:
            return
        kind, payload = selected
        if kind == "url":
            name, url = cast(tuple[str, str], payload)
            urlDialog = SurveyDialog(name, url, parent=self)
            if urlDialog.exec():
                item = self.listWidget.currentItem()
                assert item is not None
                new_name, new_url = urlDialog.get_inputs()
                item.setText(f"{new_name} — {new_url}")
                item.setData(
                    QtCore.Qt.ItemDataRole.UserRole, ("url", (new_name, new_url))
                )
            return
        survey = cast(surveys.SurveyDef, payload)
        if kind == "custom":
            # The builder authors only the simple shared-scale Likert shape; a
            # survey with typed items/help/headings must be edited as a file.
            if not survey.is_simple_likert:
                where = f"\n\n{survey.path}" if survey.path else ""
                QtWidgets.QMessageBox.information(
                    self,
                    "Manage surveys",
                    "This survey uses advanced item types and can't be edited here. "
                    f"Edit its file directly:{where}",
                )
                return
            existing = tuple(k for k in self._survey_keys() if k != survey.key)
            buildDialog = BuildSurveyDialog(survey, existing_keys=existing, parent=self)
            if buildDialog.exec():
                self._save_custom(buildDialog.get_survey())
        else:  # builtin: read-only preview of the real window, no session attached
            from .panels.survey import SurveyWindow  # deferred: dialogs stay Qt-light

            preview = SurveyWindow(survey, None, parent=self)
            self._previews.append(preview)
            preview.show()

    def _remove_selected(self) -> None:
        selected = self._selected()
        if selected is None:
            return
        kind, payload = selected
        if kind == "url":
            self.listWidget.takeItem(self.listWidget.currentRow())
        elif kind == "custom":
            survey = cast(surveys.SurveyDef, payload)
            reply = QtWidgets.QMessageBox.question(
                self,
                "Manage surveys",
                f"Delete the custom survey “{survey.name}” and its file?",
            )
            if reply != QtWidgets.QMessageBox.StandardButton.Yes:
                return
            try:
                if survey.path is not None:
                    survey.path.unlink(missing_ok=True)
            except OSError as exc:
                QtWidgets.QMessageBox.warning(
                    self, "Manage surveys", f"Could not delete the file:\n{exc}"
                )
                return
            self.files_changed = True
            self._reload_surveys()
        else:
            QtWidgets.QMessageBox.information(
                self, "Manage surveys", "Built-in surveys ship with SMACC and stay."
            )

    # ----- result ---------------------------------------------------------------

    def get_options(self) -> dict[str, str]:
        """Return the edited web-survey mapping name → URL (last wins on dupes)."""
        options: dict[str, str] = {}
        for i in range(self.listWidget.count()):
            item = self.listWidget.item(i)
            if item is None:
                continue
            data = item.data(QtCore.Qt.ItemDataRole.UserRole)
            if data and data[0] == "url":
                name, url = data[1]
                options[name] = url
        return options


class _PresetListEditor(QtWidgets.QWidget):
    """A titled, reorderable list of preset messages with add/edit/remove controls.

    Used twice by :class:`ManageChatPresetsDialog`, once per chat direction. Order
    matters for the participant replies (it maps to the number keys), so rows move
    up and down; ``max_items`` caps the list (``None`` is unlimited).
    """

    def __init__(
        self,
        title: str,
        items: list[str],
        *,
        max_items: int | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._max_items = max_items

        self.listWidget = QtWidgets.QListWidget(self)
        self.listWidget.addItems(items)
        self.listWidget.itemDoubleClicked.connect(self._edit_selected)

        addButton = QtWidgets.QPushButton("Add…", self)
        editButton = QtWidgets.QPushButton("Edit…", self)
        removeButton = QtWidgets.QPushButton("Remove", self)
        upButton = QtWidgets.QPushButton("Move up", self)
        downButton = QtWidgets.QPushButton("Move down", self)
        addButton.clicked.connect(self._add)
        editButton.clicked.connect(self._edit_selected)
        removeButton.clicked.connect(self._remove_selected)
        upButton.clicked.connect(lambda: self._move(-1))
        downButton.clicked.connect(lambda: self._move(1))

        buttonCol = QtWidgets.QVBoxLayout()
        for button in (addButton, editButton, removeButton, upButton, downButton):
            buttonCol.addWidget(button)
        buttonCol.addStretch(1)

        row = QtWidgets.QHBoxLayout()
        row.addWidget(self.listWidget, 1)
        row.addLayout(buttonCol)

        label = QtWidgets.QLabel(title, self)
        label.setWordWrap(True)
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(label)
        layout.addLayout(row)

    def items(self) -> list[str]:
        """Return the current rows, in display order."""
        rows: list[str] = []
        for i in range(self.listWidget.count()):
            item = self.listWidget.item(i)
            if item is not None:
                rows.append(item.text())
        return rows

    def _prompt(self, text: str = "") -> str | None:
        """Ask for one message; return the trimmed text (None if cancelled/blank)."""
        value, ok = QtWidgets.QInputDialog.getText(
            self, "Quick message", "Message:", text=text
        )
        if not ok:
            return None
        return value.strip() or None

    def _add(self) -> None:
        if self._max_items is not None and self.listWidget.count() >= self._max_items:
            QtWidgets.QMessageBox.information(
                self,
                "Quick messages",
                f"Up to {self._max_items} replies — one per number key "
                f"(1–{self._max_items}).",
            )
            return
        text = self._prompt()
        if text is not None:
            self.listWidget.addItem(text)

    def _edit_selected(self) -> None:
        item = self.listWidget.currentItem()
        if item is None:
            return
        text = self._prompt(item.text())
        if text is not None:
            item.setText(text)

    def _remove_selected(self) -> None:
        row = self.listWidget.currentRow()
        if row >= 0:
            self.listWidget.takeItem(row)

    def _move(self, delta: int) -> None:
        """Shift the selected row by ``delta`` (-1 up, +1 down), keeping it selected."""
        row = self.listWidget.currentRow()
        target = row + delta
        if row < 0 or not (0 <= target < self.listWidget.count()):
            return
        item = self.listWidget.takeItem(row)
        self.listWidget.insertItem(target, item)
        self.listWidget.setCurrentRow(target)


class ManageChatPresetsDialog(QtWidgets.QDialog):
    """Add, edit, reorder, and remove the intercom's quick-reply presets (#112).

    Opened from the Intercom panel. Two ordered lists — the experimenter's one-click
    prompts and the participant's number-key replies (capped at the digit keys 1–9).
    Edits copies; the caller reads :meth:`get_presets` only when accepted.
    """

    def __init__(
        self, experimenter: list[str], participant: list[str], parent=None
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Quick-reply presets")
        self.setWindowFlags(
            self.windowFlags() ^ QtCore.Qt.WindowType.WindowContextHelpButtonHint
        )
        self.resize(520, 460)

        self._experimenter = _PresetListEditor(
            "Experimenter prompts — one click sends to the participant:",
            experimenter,
            parent=self,
        )
        self._participant = _PresetListEditor(
            "Participant replies — sent with the number keys "
            f"1–{config.MAX_PARTICIPANT_PRESETS}:",
            participant,
            max_items=config.MAX_PARTICIPANT_PRESETS,
            parent=self,
        )

        buttonBox = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.StandardButton.Ok
            | QtWidgets.QDialogButtonBox.StandardButton.Cancel,
            self,
        )
        buttonBox.accepted.connect(self.accept)
        buttonBox.rejected.connect(self.reject)

        layout = QtWidgets.QVBoxLayout(self)
        layout.addWidget(self._experimenter)
        layout.addWidget(self._participant)
        layout.addWidget(buttonBox)

    def get_presets(self) -> tuple[list[str], list[str]]:
        """Return the edited ``(experimenter, participant)`` lists, in order."""
        return self._experimenter.items(), self._participant.items()


class AddEventDialog(QtWidgets.QDialog):
    """Define a new custom event button: a label, a port code, and options."""

    def __init__(self, default_code: int, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Add event")
        self.setWindowFlags(
            self.windowFlags() ^ QtCore.Qt.WindowType.WindowContextHelpButtonHint
        )
        self.labelEdit = QtWidgets.QLineEdit(self)
        self.labelEdit.setPlaceholderText("e.g. Spontaneous arousal")
        self.codeSpin = QtWidgets.QSpinBox(self)
        self.codeSpin.setRange(events.CODE_MIN, events.CODE_MAX)
        self.codeSpin.setValue(default_code)
        self.tooltipEdit = QtWidgets.QLineEdit(self)
        self.tooltipEdit.setPlaceholderText("Optional status-bar hint")
        self.incrementBox = QtWidgets.QCheckBox(
            "Increment the code on each press", self
        )
        buttonBox = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.StandardButton.Ok
            | QtWidgets.QDialogButtonBox.StandardButton.Cancel,
            self,
        )
        buttonBox.accepted.connect(self._on_accept)
        buttonBox.rejected.connect(self.reject)
        form = QtWidgets.QFormLayout(self)
        form.addRow("Label", self.labelEdit)
        form.addRow("Code", self.codeSpin)
        form.addRow("Tooltip", self.tooltipEdit)
        form.addRow("", self.incrementBox)
        form.addWidget(buttonBox)

    def _on_accept(self) -> None:
        if not self.labelEdit.text().strip():
            QtWidgets.QMessageBox.warning(self, "Add event", "Please enter a label.")
            return
        self.accept()

    def get_inputs(self) -> tuple[str, int, str, bool]:
        """Return ``(label, code, tooltip, increment)``."""
        return (
            self.labelEdit.text().strip(),
            self.codeSpin.value(),
            self.tooltipEdit.text().strip(),
            self.incrementBox.isChecked(),
        )


class HueBridgeDialog(QtWidgets.QDialog):
    """Find and pair with a Philips Hue bridge (#53).

    The flow mirrors the Hue app's: find the bridge's IP (auto-discovery, or type
    it in), press the bridge's round link button, then Pair — the bridge mints the
    app key SMACC stores. A Test button lists the bridge's lights/groups inline so
    the rig can be verified before relying on it. The dialog edits a copy; the
    caller reads :meth:`get_config` only when accepted.
    """

    def __init__(self, config: hue.HueConfig, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Philips Hue bridge")
        self.setWindowFlags(
            self.windowFlags() ^ QtCore.Qt.WindowType.WindowContextHelpButtonHint
        )
        self._app_key = config.app_key

        hint = QtWidgets.QLabel(
            "Pair once per bridge: find its IP, press the round link button on "
            "the bridge itself, then click Pair within 30 seconds. The pairing "
            "key is stored in the study's .smacc file."
        )
        hint.setWordWrap(True)

        self.ipEdit = QtWidgets.QLineEdit(config.bridge_ip, self)
        self.ipEdit.setPlaceholderText("e.g. 192.168.1.23")
        self.ipEdit.setStatusTip("The bridge's IP on this network.")
        self.ipEdit.textChanged.connect(self._refresh_status)
        discoverButton = QtWidgets.QPushButton("Find bridge", self)
        discoverButton.setStatusTip(
            "Ask Philips' discovery service for bridges on this network."
        )
        discoverButton.clicked.connect(self._discover)
        ipRow = QtWidgets.QHBoxLayout()
        ipRow.addWidget(self.ipEdit)
        ipRow.addWidget(discoverButton)

        pairButton = QtWidgets.QPushButton("Pair", self)
        pairButton.setStatusTip(
            "Mint an app key (press the bridge's link button first)."
        )
        pairButton.clicked.connect(self._pair)
        testButton = QtWidgets.QPushButton("Test", self)
        testButton.setStatusTip(
            "List the bridge's lights and groups with the current key."
        )
        testButton.clicked.connect(self._test)
        actionRow = QtWidgets.QHBoxLayout()
        actionRow.addWidget(pairButton)
        actionRow.addWidget(testButton)

        self.statusLabel = QtWidgets.QLabel(self)
        self.statusLabel.setWordWrap(True)
        self._refresh_status()

        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.StandardButton.Ok
            | QtWidgets.QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        form = QtWidgets.QFormLayout()
        form.setLabelAlignment(QtCore.Qt.AlignmentFlag.AlignRight)
        form.addRow("Bridge IP:", ipRow)
        form.addRow(actionRow)
        form.addRow(self.statusLabel)

        layout = QtWidgets.QVBoxLayout()
        layout.addWidget(hint)
        layout.addLayout(form)
        layout.addWidget(buttons)
        self.setLayout(layout)

    # ----- actions (each is one user-initiated, short-timeout bridge call) ----

    def _discover(self) -> None:
        found = hue.discover()
        if found:
            self.ipEdit.setText(found[0])
            extra = f" (+{len(found) - 1} more)" if len(found) > 1 else ""
            self._set_status(f"Found a bridge at {found[0]}{extra}.")
        else:
            self._set_status(
                "No bridge found. Enter its IP by hand (the Hue app shows it "
                "under bridge settings)."
            )

    def _pair(self) -> None:
        ip = self.ipEdit.text().strip()
        if not ip:
            self._set_status("Enter the bridge IP first.")
            return
        try:
            self._app_key = hue.pair(ip)
        except hue.HueError as err:
            self._set_status(str(err))
            return
        self._set_status("Paired ✓ — now Test, then OK.")

    def _test(self) -> None:
        cfg = self.get_config()
        if not cfg.configured:
            self._set_status("Pair with the bridge first.")
            return
        try:
            found = hue.targets(cfg)
        except hue.HueError as err:
            self._set_status(str(err))
            return
        n_lights = sum(1 for _, key in found if key.startswith("light:"))
        n_groups = len(found) - n_lights
        self._set_status(
            f"Bridge OK: {n_lights} light(s), {n_groups} group(s). Bind one to "
            "the Philips Hue role after closing this dialog."
        )

    def _set_status(self, text: str) -> None:
        self.statusLabel.setText(text)

    def _refresh_status(self) -> None:
        """The resting status line: paired or not, for the current IP."""
        if self._app_key:
            self._set_status("Paired ✓")
        else:
            self._set_status("Not paired yet.")

    def get_config(self) -> hue.HueConfig:
        """The edited config (read by the caller when the dialog is accepted)."""
        return hue.HueConfig(
            bridge_ip=self.ipEdit.text().strip(), app_key=self._app_key
        )
