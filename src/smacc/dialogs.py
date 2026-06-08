"""Dialogs shown by SMACC outside the main window."""

from PyQt5 import QtCore, QtGui, QtWidgets

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
