"""Dialogs shown by SMACC outside the main window."""

from collections.abc import Callable
from dataclasses import replace

from PyQt6 import QtCore, QtGui, QtWidgets

from . import config, events, hue, triggers
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
    """Add or edit a single named survey: a display name and its URL.

    Used by :class:`ManageSurveysDialog` for its Add/Edit actions. The URL is
    normalized on accept (whitespace trimmed, ``https://`` added when no scheme),
    and both fields are required.
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


class ManageSurveysDialog(QtWidgets.QDialog):
    """Add, edit, and remove the named survey URLs saved with the session.

    Opened from the Dream-recording panel (Manage…) and File → Surveys. Edits a
    copy of the mapping; the caller reads the result with :meth:`get_options`
    only when the dialog is accepted.
    """

    def __init__(self, options: dict[str, str], parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Manage surveys")
        self.setWindowFlags(
            self.windowFlags() ^ QtCore.Qt.WindowType.WindowContextHelpButtonHint
        )
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
        layout.addLayout(topRow)
        layout.addWidget(buttonBox)

    def _add_row(self, name: str, url: str) -> None:
        """Append a list row labeled ``name — url`` carrying ``(name, url)`` as data."""
        item = QtWidgets.QListWidgetItem(f"{name} — {url}")
        item.setData(QtCore.Qt.ItemDataRole.UserRole, (name, url))
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
        name, url = item.data(QtCore.Qt.ItemDataRole.UserRole)
        dialog = SurveyDialog(name, url, parent=self)
        if dialog.exec():
            new_name, new_url = dialog.get_inputs()
            item.setText(f"{new_name} — {new_url}")
            item.setData(QtCore.Qt.ItemDataRole.UserRole, (new_name, new_url))

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
            name, url = item.data(QtCore.Qt.ItemDataRole.UserRole)
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


class EventCodesDialog(QtWidgets.QDialog):
    """View and edit the event-marker registry: codes, routing, and custom events.

    One row per event shows its port code plus independent Trigger (send to the
    marker stream) and Preview (show in the live log viewer) checkboxes, and an
    Increment toggle (advance the code on each firing). The log *file* always
    records every event regardless of Preview. Built-in events can be retuned but
    not removed or renamed; custom events (added here) have an editable label, can
    be removed, and appear as buttons in the Event logging panel. Codes are unique
    8-bit values (1-255); a soft "safe max" flags values older hardware may reject.

    The dialog edits copies; the caller reads :meth:`get_events` /
    :meth:`get_safe_max` only when the dialog is accepted.
    """

    def __init__(self, event_list, safe_max: int, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Event codes")
        self.setWindowFlags(
            self.windowFlags() ^ QtCore.Qt.WindowType.WindowContextHelpButtonHint
        )
        self.resize(600, 560)
        self._events = [replace(e) for e in event_list]  # working copies

        self.table = QtWidgets.QTableWidget(0, 5, self)
        self.table.setHorizontalHeaderLabels(
            ["Event", "Code", "Trigger", "Preview", "Increment"]
        )
        for col, tip in (
            (2, "Send this event's code to the marker stream (EEG)."),
            (
                3,
                "Show this event in the live log viewer (the log file always records it).",
            ),
            (4, "Advance the code on each firing (e.g. dream reports: 201, 202, …)."),
        ):
            header_item = self.table.horizontalHeaderItem(col)
            if header_item is not None:
                header_item.setToolTip(tip)
        vheader = self.table.verticalHeader()
        assert vheader is not None
        vheader.setVisible(False)
        self.table.setSelectionMode(
            QtWidgets.QAbstractItemView.SelectionMode.SingleSelection
        )
        self.table.setSelectionBehavior(
            QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows
        )
        self.table.setEditTriggers(
            QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers
        )
        header = self.table.horizontalHeader()
        assert header is not None
        header.setSectionResizeMode(0, QtWidgets.QHeaderView.ResizeMode.Stretch)
        for col in range(1, 5):
            header.setSectionResizeMode(
                col, QtWidgets.QHeaderView.ResizeMode.ResizeToContents
            )

        addButton = QtWidgets.QPushButton("Add event…", self)
        addButton.setStatusTip("Add a custom event button.")
        addButton.clicked.connect(self._add_event)
        self.removeButton = QtWidgets.QPushButton("Remove", self)
        self.removeButton.setStatusTip("Remove the selected custom event.")
        self.removeButton.clicked.connect(self._remove_selected)
        addRemoveRow = QtWidgets.QHBoxLayout()
        addRemoveRow.addWidget(addButton)
        addRemoveRow.addWidget(self.removeButton)
        addRemoveRow.addStretch(1)

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
            QtWidgets.QDialogButtonBox.StandardButton.Ok
            | QtWidgets.QDialogButtonBox.StandardButton.Cancel,
            self,
        )
        buttonBox.accepted.connect(self._on_accept)
        buttonBox.rejected.connect(self.reject)

        hint = QtWidgets.QLabel(
            "Codes are 8-bit (1-255) and must be unique among triggered events. "
            "The log file records every event; Preview only controls the live viewer."
        )
        hint.setWordWrap(True)
        layout = QtWidgets.QVBoxLayout(self)
        layout.addWidget(hint)
        layout.addWidget(self.table, 1)
        layout.addLayout(addRemoveRow)
        layout.addLayout(safeRow)
        layout.addWidget(buttonBox)

        self._populate()

    # ----- table build / sync ------------------------------------------------

    def _populate(self) -> None:
        """(Re)build the table rows from ``self._events`` (called after add/remove)."""
        self._code_spins: list[QtWidgets.QSpinBox] = []
        self._trigger_boxes: list[QtWidgets.QCheckBox] = []
        self._preview_boxes: list[QtWidgets.QCheckBox] = []
        self._increment_boxes: list[QtWidgets.QCheckBox] = []
        self._label_edits: list[QtWidgets.QLineEdit | None] = []
        self.table.setRowCount(len(self._events))
        for row, event in enumerate(self._events):
            if event.builtin:
                label_item = QtWidgets.QTableWidgetItem(event.label)
                label_item.setFlags(
                    label_item.flags() & ~QtCore.Qt.ItemFlag.ItemIsEditable
                )
                if event.tooltip:
                    label_item.setToolTip(event.tooltip)
                self.table.setItem(row, 0, label_item)
                self._label_edits.append(None)
            else:
                label_edit = QtWidgets.QLineEdit(event.label, self)
                label_edit.setPlaceholderText("Custom event label")
                self.table.setCellWidget(row, 0, label_edit)
                self._label_edits.append(label_edit)

            code_spin = QtWidgets.QSpinBox(self)
            code_spin.setRange(events.CODE_MIN, events.CODE_MAX)
            code_spin.setValue(event.code)
            self.table.setCellWidget(row, 1, code_spin)
            self._code_spins.append(code_spin)

            trig_cell, trig_box = self._checkbox_cell(event.trigger)
            preview_cell, preview_box = self._checkbox_cell(event.preview)
            inc_cell, inc_box = self._checkbox_cell(event.increment)
            self.table.setCellWidget(row, 2, trig_cell)
            self.table.setCellWidget(row, 3, preview_cell)
            self.table.setCellWidget(row, 4, inc_cell)
            self._trigger_boxes.append(trig_box)
            self._preview_boxes.append(preview_box)
            self._increment_boxes.append(inc_box)

    def _sync(self) -> None:
        """Read widget values back into ``self._events`` before add/remove/accept."""
        for i, event in enumerate(self._events):
            label = event.label
            edit = self._label_edits[i]
            if edit is not None:
                label = edit.text().strip() or event.label
            self._events[i] = replace(
                event,
                label=label,
                code=self._code_spins[i].value(),
                trigger=self._trigger_boxes[i].isChecked(),
                preview=self._preview_boxes[i].isChecked(),
                increment=self._increment_boxes[i].isChecked(),
            )

    @staticmethod
    def _checkbox_cell(checked: bool):
        """Return a ``(container, checkbox)`` with the box centered in its cell."""
        container = QtWidgets.QWidget()
        box = QtWidgets.QCheckBox(container)
        box.setChecked(checked)
        lay = QtWidgets.QHBoxLayout(container)
        lay.addWidget(box)
        lay.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        lay.setContentsMargins(0, 0, 0, 0)
        return container, box

    # ----- add / remove ------------------------------------------------------

    def _suggested_code(self) -> int:
        """A free-ish default code for a new event (one past the current max)."""
        used = [e.code for e in self._events if isinstance(e.code, int)]
        return min((max(used) + 1) if used else events.CODE_MIN, events.CODE_MAX)

    def _add_event(self) -> None:
        self._sync()
        dialog = AddEventDialog(self._suggested_code(), parent=self)
        if not dialog.exec():
            return
        label, code, tooltip, increment = dialog.get_inputs()
        event = events.make_custom_event(
            label,
            code,
            [e.key for e in self._events],
            tooltip=tooltip,
            increment=increment,
        )
        self._events.append(event)
        self._populate()
        self.table.selectRow(len(self._events) - 1)

    def _remove_selected(self) -> None:
        row = self.table.currentRow()
        if row < 0:
            return
        self._sync()
        if self._events[row].builtin:
            QtWidgets.QMessageBox.information(
                self, "Event codes", "Built-in events can't be removed."
            )
            return
        del self._events[row]
        self._populate()

    # ----- result ------------------------------------------------------------

    def get_events(self) -> list:
        """Return the edits as new EventDef objects (the originals are untouched)."""
        self._sync()
        return [replace(e) for e in self._events]

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
            if reply != QtWidgets.QMessageBox.StandardButton.Yes:
                return
        self.accept()


# Common serial baud rates offered in the dropdown (it stays editable for any other).
_COMMON_BAUDS = (9600, 19200, 38400, 57600, 115200, 230400)


class TriggerOutputDialog(QtWidgets.QDialog):
    """Configure optional hardware TTL trigger output alongside LSL (#28).

    LSL marker output is always on; this dialog edits the *opt-in* second path —
    transport (serial USB box / parallel LPT), the port/address, and whether the
    line is pulsed (SMACC times the pulse) or set-and-hold. A Test button sends one
    pulse through the current settings and reports the result inline, so the rig can
    be verified before relying on it. The dialog edits a copy; the caller reads
    :meth:`get_config` only when accepted.
    """

    def __init__(
        self,
        config: triggers.TriggerConfig,
        test_callback: Callable[[triggers.TriggerConfig], str | None] | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Trigger output")
        self.setWindowFlags(
            self.windowFlags() ^ QtCore.Qt.WindowType.WindowContextHelpButtonHint
        )
        self._test_callback = test_callback

        hint = QtWidgets.QLabel(
            "SMACC always emits markers over LSL. Optionally also drive a hardware "
            "TTL trigger for amplifiers that read a physical pulse. One transport at "
            "a time; see the Triggers docs."
        )
        hint.setWordWrap(True)

        self.enabledBox = QtWidgets.QCheckBox("Enable hardware trigger output", self)
        self.enabledBox.setChecked(config.enabled)
        self.enabledBox.toggled.connect(self._update_enabled_state)

        self.transportCombo = QtWidgets.QComboBox(self)
        self.transportCombo.addItem("Serial (USB trigger box)", "serial")
        self.transportCombo.addItem("Parallel port (LPT)", "parallel")
        self.transportCombo.currentIndexChanged.connect(self._on_transport_changed)

        # Serial page: COM port (editable, in case the rig isn't attached now) + baud.
        self.portCombo = QtWidgets.QComboBox(self)
        self.portCombo.setEditable(True)
        self.portCombo.setMinimumWidth(220)
        refreshButton = QtWidgets.QPushButton("Refresh", self)
        refreshButton.setStatusTip("Rescan for attached serial ports.")
        refreshButton.clicked.connect(self._refresh_ports)
        portRow = QtWidgets.QHBoxLayout()
        portRow.addWidget(self.portCombo, 1)
        portRow.addWidget(refreshButton)
        self.baudCombo = QtWidgets.QComboBox(self)
        self.baudCombo.setEditable(True)
        self.baudCombo.addItems([str(b) for b in _COMMON_BAUDS])
        serialPage = QtWidgets.QWidget(self)
        serialForm = QtWidgets.QFormLayout(serialPage)
        serialForm.setContentsMargins(0, 0, 0, 0)
        serialForm.addRow("Port", portRow)
        serialForm.addRow("Baud", self.baudCombo)

        # Parallel page: base address (hex), with help on finding it.
        self.addressEdit = QtWidgets.QLineEdit(self)
        self.addressEdit.setPlaceholderText(triggers.DEFAULT_LPT_ADDRESS)
        addressHelp = QtWidgets.QLabel(
            "Base I/O address as hex (e.g. 0x378). Find it in Device Manager → the "
            "LPT port → Resources → I/O Range. Needs the InpOut32 driver installed "
            "(see the Triggers docs)."
        )
        addressHelp.setWordWrap(True)
        parallelPage = QtWidgets.QWidget(self)
        parallelForm = QtWidgets.QFormLayout(parallelPage)
        parallelForm.setContentsMargins(0, 0, 0, 0)
        parallelForm.addRow("Address", self.addressEdit)
        parallelForm.addRow("", addressHelp)

        self.transportStack = QtWidgets.QStackedWidget(self)
        self.transportStack.addWidget(serialPage)  # index 0 == serial
        self.transportStack.addWidget(parallelPage)  # index 1 == parallel

        self.modeCombo = QtWidgets.QComboBox(self)
        self.modeCombo.addItem("Pulsed (SMACC times the pulse)", "pulsed")
        self.modeCombo.addItem("Set-and-hold (until next event)", "hold")
        self.modeCombo.currentIndexChanged.connect(self._update_pulse_enabled)
        self.pulseSpin = QtWidgets.QSpinBox(self)
        self.pulseSpin.setRange(1, 1000)
        self.pulseSpin.setSuffix(" ms")
        self.pulseSpin.setValue(config.pulse_ms)

        self.testButton = QtWidgets.QPushButton("Test", self)
        self.testButton.setStatusTip("Send one test pulse through these settings.")
        self.testButton.clicked.connect(self._on_test)
        self.testResult = QtWidgets.QLabel("", self)
        self.testResult.setWordWrap(True)
        testRow = QtWidgets.QHBoxLayout()
        testRow.addWidget(self.testButton)
        testRow.addWidget(self.testResult, 1)

        # The transport/mode/pulse/test controls are gated behind the enable box.
        self._config_widget = QtWidgets.QWidget(self)
        configForm = QtWidgets.QFormLayout(self._config_widget)
        configForm.setContentsMargins(0, 0, 0, 0)
        configForm.addRow("Transport", self.transportCombo)
        configForm.addRow(self.transportStack)
        configForm.addRow("Mode", self.modeCombo)
        configForm.addRow("Pulse width", self.pulseSpin)
        configForm.addRow(testRow)

        buttonBox = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.StandardButton.Ok
            | QtWidgets.QDialogButtonBox.StandardButton.Cancel,
            self,
        )
        buttonBox.accepted.connect(self.accept)
        buttonBox.rejected.connect(self.reject)

        layout = QtWidgets.QVBoxLayout(self)
        layout.addWidget(hint)
        layout.addWidget(self.enabledBox)
        layout.addWidget(self._config_widget)
        layout.addStretch(1)
        layout.addWidget(buttonBox)

        # Seed the widgets from the incoming config, then sync dependent states.
        self._select_data(self.transportCombo, config.transport)
        self._select_data(self.modeCombo, config.mode)
        self._refresh_ports(selected=config.port)
        self.baudCombo.setCurrentText(str(config.baud))
        self.addressEdit.setText(config.address)
        self._on_transport_changed()
        self._update_pulse_enabled()
        self._update_enabled_state()

    @staticmethod
    def _select_data(combo: QtWidgets.QComboBox, value: str) -> None:
        """Select the combo entry whose itemData is ``value`` (no-op if absent)."""
        index = combo.findData(value)
        if index >= 0:
            combo.setCurrentIndex(index)

    def _refresh_ports(self, *, selected: str | None = None) -> None:
        """Repopulate the serial-port dropdown, preserving the current selection."""
        if selected is None:
            selected = self._current_port()
        self.portCombo.clear()
        for device, description in triggers.list_serial_ports():
            label = device if description == device else f"{device} — {description}"
            self.portCombo.addItem(label, device)
        if selected:
            index = self.portCombo.findData(selected)
            if index >= 0:
                self.portCombo.setCurrentIndex(index)
            else:
                # Saved port not attached now: show it as free text, and clear the
                # current index so it doesn't resolve back to a *listed* port.
                self.portCombo.setCurrentIndex(-1)
                self.portCombo.setEditText(selected)

    def _on_transport_changed(self) -> None:
        self.transportStack.setCurrentIndex(self.transportCombo.currentIndex())

    def _update_pulse_enabled(self) -> None:
        self.pulseSpin.setEnabled(self.modeCombo.currentData() == "pulsed")

    def _update_enabled_state(self) -> None:
        self._config_widget.setEnabled(self.enabledBox.isChecked())

    def _current_port(self) -> str:
        """Resolve the chosen port to its device name.

        The combo is editable and its labels may carry a description, so the shown
        text isn't always the device. If it matches a listed entry, return that
        entry's device (itemData); otherwise it's a free-typed port (a rig not
        attached now), so return the text as-is. Avoids the stale ``currentData()``
        an editable combo keeps when its edit text was set without changing index.
        """
        text = self.portCombo.currentText().strip()
        index = self.portCombo.findText(text)
        if index >= 0:
            device = self.portCombo.itemData(index)
            return str(device) if device else text
        return text

    def _current_baud(self) -> int:
        try:
            return int(self.baudCombo.currentText().strip())
        except ValueError:
            return triggers.DEFAULT_BAUD

    def _on_test(self) -> None:
        """Send one test pulse through the current settings and report the result."""
        if self._test_callback is None:
            return
        error = self._test_callback(self.get_config())
        if error:
            self.testResult.setText(f"⚠ {error}")
        else:
            self.testResult.setText("✓ Sent test pulse — check the amplifier.")

    def get_config(self) -> triggers.TriggerConfig:
        """Return the edited config (read only when the dialog is accepted)."""
        return triggers.TriggerConfig(
            enabled=self.enabledBox.isChecked(),
            transport=self.transportCombo.currentData(),
            port=self._current_port(),
            baud=self._current_baud(),
            address=self.addressEdit.text().strip() or triggers.DEFAULT_LPT_ADDRESS,
            mode=self.modeCombo.currentData(),
            pulse_ms=self.pulseSpin.value(),
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
