"""Dialogs shown by SMACC outside the main window."""

from dataclasses import replace
from functools import partial

from PyQt5 import QtCore, QtGui, QtWidgets

from . import events
from .utils import normalize_survey_url


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
        self.setWindowFlags(self.windowFlags() ^ QtCore.Qt.WindowContextHelpButtonHint)
        # Create subject and session text inputs, prefilled from current metadata.
        self.subject_id = QtWidgets.QLineEdit(self)
        self.session_id = QtWidgets.QLineEdit(self)
        self.subject_id.setText(subject)
        self.session_id.setText(session)
        self.subject_id.setPlaceholderText("Optional")
        self.session_id.setPlaceholderText("Optional")
        # Allow letters, numbers, underscores, and hyphens, up to 30 characters;
        # empty is allowed since the fields are optional.
        id_validator = QtGui.QRegExpValidator(QtCore.QRegExp(r"[A-Za-z0-9_-]{0,30}"))
        for field in (self.subject_id, self.session_id):
            field.setValidator(id_validator)
            field.setMaxLength(30)
        self.notes = QtWidgets.QLineEdit(self)
        self.notes.setText(notes)
        self.notes.setPlaceholderText("Optional free-text notes")
        # Create buttons to accept values or cancel.
        buttonBox = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel, self
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
    """Add or edit a single named survey: a display name and its URL.

    Used by :class:`ManageSurveysDialog` for its Add/Edit actions. The URL is
    normalized on accept (whitespace trimmed, ``https://`` added when no scheme),
    and both fields are required.
    """

    def __init__(self, name: str = "", url: str = "", parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Survey")
        # Removes the default "What's this?" question mark icon from the titlebar.
        self.setWindowFlags(self.windowFlags() ^ QtCore.Qt.WindowContextHelpButtonHint)
        self.nameEdit = QtWidgets.QLineEdit(self)
        self.nameEdit.setText(name)
        self.nameEdit.setPlaceholderText("e.g. Post-dream survey")
        self.urlEdit = QtWidgets.QLineEdit(self)
        self.urlEdit.setText(url)
        self.urlEdit.setPlaceholderText("https://…")
        buttonBox = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel, self
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


class ManageSurveysDialog(QtWidgets.QDialog):
    """Add, edit, and remove the named survey URLs saved with the session.

    Opened from the Dream-recording panel (Manage…) and File → Surveys. Edits a
    copy of the mapping; the caller reads the result with :meth:`get_options`
    only when the dialog is accepted.
    """

    def __init__(self, options: dict[str, str], parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Manage surveys")
        self.setWindowFlags(self.windowFlags() ^ QtCore.Qt.WindowContextHelpButtonHint)
        self.resize(440, 260)

        self.listWidget = QtWidgets.QListWidget(self)
        for name, url in options.items():
            self._add_row(name, url)
        self.listWidget.itemDoubleClicked.connect(self._edit_selected)

        addButton = QtWidgets.QPushButton("Add…", self)
        editButton = QtWidgets.QPushButton("Edit…", self)
        removeButton = QtWidgets.QPushButton("Remove", self)
        addButton.clicked.connect(self._add_new)
        editButton.clicked.connect(self._edit_selected)
        removeButton.clicked.connect(self._remove_selected)

        buttonCol = QtWidgets.QVBoxLayout()
        for button in (addButton, editButton, removeButton):
            buttonCol.addWidget(button)
        buttonCol.addStretch(1)

        buttonBox = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel, self
        )
        buttonBox.accepted.connect(self.accept)
        buttonBox.rejected.connect(self.reject)

        topRow = QtWidgets.QHBoxLayout()
        topRow.addWidget(self.listWidget, 1)
        topRow.addLayout(buttonCol)
        layout = QtWidgets.QVBoxLayout(self)
        layout.addLayout(topRow)
        layout.addWidget(buttonBox)

    def _add_row(self, name: str, url: str) -> None:
        """Append a list row labeled ``name — url`` carrying ``(name, url)`` as data."""
        item = QtWidgets.QListWidgetItem(f"{name} — {url}")
        item.setData(QtCore.Qt.UserRole, (name, url))
        self.listWidget.addItem(item)

    def _add_new(self) -> None:
        dialog = SurveyDialog(parent=self)
        if dialog.exec():
            name, url = dialog.get_inputs()
            self._add_row(name, url)

    def _edit_selected(self) -> None:
        item = self.listWidget.currentItem()
        if item is None:
            return
        name, url = item.data(QtCore.Qt.UserRole)
        dialog = SurveyDialog(name, url, parent=self)
        if dialog.exec():
            new_name, new_url = dialog.get_inputs()
            item.setText(f"{new_name} — {new_url}")
            item.setData(QtCore.Qt.UserRole, (new_name, new_url))

    def _remove_selected(self) -> None:
        row = self.listWidget.currentRow()
        if row >= 0:
            self.listWidget.takeItem(row)

    def get_options(self) -> dict[str, str]:
        """Return the edited mapping of survey name → URL (last wins on dupes)."""
        options: dict[str, str] = {}
        for i in range(self.listWidget.count()):
            item = self.listWidget.item(i)
            if item is None:
                continue
            name, url = item.data(QtCore.Qt.UserRole)
            options[name] = url
        return options


class EventCodesDialog(QtWidgets.QDialog):
    """View and edit the event-marker registry: codes and per-event routing.

    One row per event shows its (editable) port code plus two checkboxes —
    Trigger (send to the marker stream) and Log (write to the session log) — and
    an Increment toggle for events that support it (the dream-report start). A
    triggered event is always logged, so Log is forced on and disabled while
    Trigger is checked. Codes are unique 8-bit values (1-255); a soft "safe max"
    flags values that older trigger hardware may not accept.

    The dialog edits copies; the caller reads :meth:`get_events` /
    :meth:`get_safe_max` only when the dialog is accepted.
    """

    def __init__(self, event_list, safe_max: int, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Event codes")
        self.setWindowFlags(self.windowFlags() ^ QtCore.Qt.WindowContextHelpButtonHint)
        self.resize(560, 540)
        self._events = [replace(e) for e in event_list]  # working copies

        self.table = QtWidgets.QTableWidget(len(self._events), 5, self)
        self.table.setHorizontalHeaderLabels(
            ["Event", "Code", "Trigger", "Log", "Increment"]
        )
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionMode(QtWidgets.QAbstractItemView.NoSelection)
        self.table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)

        self._code_spins: list[QtWidgets.QSpinBox] = []
        self._trigger_boxes: list[QtWidgets.QCheckBox] = []
        self._log_boxes: list[QtWidgets.QCheckBox] = []
        self._increment_boxes: list[QtWidgets.QCheckBox] = []
        for row, event in enumerate(self._events):
            label_item = QtWidgets.QTableWidgetItem(event.label)
            label_item.setFlags(label_item.flags() & ~QtCore.Qt.ItemIsEditable)
            if event.tooltip:
                label_item.setToolTip(event.tooltip)
            self.table.setItem(row, 0, label_item)

            code_spin = QtWidgets.QSpinBox(self)
            code_spin.setRange(events.CODE_MIN, events.CODE_MAX)
            code_spin.setValue(event.code)
            self.table.setCellWidget(row, 1, code_spin)
            self._code_spins.append(code_spin)

            trig_cell, trig_box = self._checkbox_cell(event.trigger)
            log_cell, log_box = self._checkbox_cell(event.log)
            inc_cell, inc_box = self._checkbox_cell(event.increment)
            inc_box.setEnabled(event.key in events.INCREMENTABLE_KEYS)
            self.table.setCellWidget(row, 2, trig_cell)
            self.table.setCellWidget(row, 3, log_cell)
            self.table.setCellWidget(row, 4, inc_cell)
            self._trigger_boxes.append(trig_box)
            self._log_boxes.append(log_box)
            self._increment_boxes.append(inc_box)
            # A triggered event is always logged (keep markers traceable).
            trig_box.toggled.connect(partial(self._sync_log_enabled, log_box))
            self._sync_log_enabled(log_box, trig_box.isChecked())

        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QtWidgets.QHeaderView.Stretch)
        for col in range(1, 5):
            header.setSectionResizeMode(col, QtWidgets.QHeaderView.ResizeToContents)

        self.safeMaxSpin = QtWidgets.QSpinBox(self)
        self.safeMaxSpin.setRange(events.CODE_MIN, events.CODE_MAX)
        self.safeMaxSpin.setValue(int(safe_max))
        self.safeMaxSpin.setStatusTip(
            "Codes above this raise a soft warning (some older trigger hardware "
            "accepts only a limited range)."
        )
        safeRow = QtWidgets.QHBoxLayout()
        safeRow.addWidget(QtWidgets.QLabel("Safe max code:"))
        safeRow.addWidget(self.safeMaxSpin)
        safeRow.addStretch(1)

        buttonBox = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel, self
        )
        buttonBox.accepted.connect(self._on_accept)
        buttonBox.rejected.connect(self.reject)

        hint = QtWidgets.QLabel(
            "Codes are 8-bit (1-255) and must be unique among triggered events. "
            "A triggered event is always logged."
        )
        hint.setWordWrap(True)
        layout = QtWidgets.QVBoxLayout(self)
        layout.addWidget(hint)
        layout.addWidget(self.table, 1)
        layout.addLayout(safeRow)
        layout.addWidget(buttonBox)

    @staticmethod
    def _checkbox_cell(checked: bool):
        """Return a ``(container, checkbox)`` with the box centered in its cell."""
        container = QtWidgets.QWidget()
        box = QtWidgets.QCheckBox(container)
        box.setChecked(checked)
        lay = QtWidgets.QHBoxLayout(container)
        lay.addWidget(box)
        lay.setAlignment(QtCore.Qt.AlignCenter)
        lay.setContentsMargins(0, 0, 0, 0)
        return container, box

    @staticmethod
    def _sync_log_enabled(log_box: QtWidgets.QCheckBox, triggered: bool) -> None:
        """Force Log on+disabled while Trigger is checked; free it otherwise."""
        if triggered:
            log_box.setChecked(True)
            log_box.setEnabled(False)
        else:
            log_box.setEnabled(True)

    def get_events(self) -> list:
        """Return the edits as new EventDef objects (the originals are untouched)."""
        out = []
        for event, code_spin, trig, log, inc in zip(
            self._events,
            self._code_spins,
            self._trigger_boxes,
            self._log_boxes,
            self._increment_boxes,
            strict=True,
        ):
            out.append(
                replace(
                    event,
                    code=code_spin.value(),
                    trigger=trig.isChecked(),
                    log=log.isChecked(),
                    increment=inc.isChecked(),
                )
            )
        return out

    def get_safe_max(self) -> int:
        """Return the chosen soft maximum code."""
        return self.safeMaxSpin.value()

    def _on_accept(self) -> None:
        """Validate before accepting: block on hard errors, confirm soft warnings."""
        candidate = self.get_events()
        errors, warnings = events.validate_events(candidate, self.get_safe_max())
        if errors:
            QtWidgets.QMessageBox.warning(
                self, "Event codes", "Please fix these first:\n\n" + "\n".join(errors)
            )
            return
        if warnings:
            reply = QtWidgets.QMessageBox.question(
                self, "Event codes", "Save anyway?\n\n" + "\n".join(warnings)
            )
            if reply != QtWidgets.QMessageBox.Yes:
                return
        self.accept()
