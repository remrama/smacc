"""In-app survey window: render a survey and save its responses to the run folder.

Opened by the Dream-recording panel for any ``smacc://survey/<key>`` selection —
auto-opened when a dream report starts recording (attached to that report's
number) or standalone from File → Surveys. Non-modal on purpose: the operator
must keep the intercom reachable while administering a questionnaire to a
participant who is in bed in the dark.

Submitting writes one JSON file per administration into the run folder (named to
sort beside the report it accompanies; see :func:`smacc.surveys.response_filename`)
and emits the ``SurveySubmitted`` marker. Without a run folder (the study
designer, or a preview from the Manage-surveys dialog) the survey renders for
inspection but Submit is disabled, mirroring how the record button is gated.
"""

from __future__ import annotations

import json
from datetime import datetime

from PyQt6 import QtCore, QtWidgets

from .. import surveys
from ..session import SmaccSession
from .base import make_section_title


class SurveyWindow(QtWidgets.QDialog):
    """Administer one survey: a Likert matrix, optional notes, and Submit.

    One instance per administration (several can be open at once; each writes its
    own response file). ``report_number`` links an auto-opened survey to its dream
    report; ``session=None`` renders a pure preview (builder/manage inspection).
    """

    def __init__(
        self,
        survey: surveys.SurveyDef,
        session: SmaccSession | None,
        *,
        report_number: int | None = None,
        parent: QtWidgets.QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.survey = survey
        self.session = session
        self.report_number = report_number
        self.opened_at = datetime.now()
        self.setWindowTitle(survey.title)
        self.setWindowFlags(
            self.windowFlags() ^ QtCore.Qt.WindowType.WindowContextHelpButtonHint
        )
        self._groups: list[QtWidgets.QButtonGroup] = []
        self._build()

    # ----- layout -------------------------------------------------------------

    def _build(self) -> None:
        layout = QtWidgets.QVBoxLayout(self)
        layout.addWidget(make_section_title(self.survey.title))

        if self.survey.citation:
            citation = QtWidgets.QLabel(self.survey.citation, self)
            citation.setWordWrap(True)
            font = citation.font()
            font.setItalic(True)
            citation.setFont(font)
            layout.addWidget(citation)

        if self.survey.instructions:
            instructions = QtWidgets.QLabel(self.survey.instructions, self)
            instructions.setWordWrap(True)
            layout.addWidget(instructions)

        layout.addWidget(self._build_matrix(), 1)

        self.notesEdit = QtWidgets.QLineEdit(self)
        self.notesEdit.setPlaceholderText("Optional free-text notes")
        notesRow = QtWidgets.QFormLayout()
        notesRow.addRow("Notes:", self.notesEdit)
        layout.addLayout(notesRow)

        buttonBox = QtWidgets.QDialogButtonBox(self)
        submitButton = buttonBox.addButton(
            "Submit", QtWidgets.QDialogButtonBox.ButtonRole.AcceptRole
        )
        assert submitButton is not None
        self.submitButton = submitButton
        buttonBox.addButton(QtWidgets.QDialogButtonBox.StandardButton.Cancel)
        buttonBox.accepted.connect(self._on_submit)
        buttonBox.rejected.connect(self.reject)
        if self.session is None or not self.session.can_record:
            # Same gating language as the record button: collecting responses
            # needs a run folder to save into; previews/designer render only.
            self.submitButton.setEnabled(False)
            self.submitButton.setToolTip(
                "Submitting is available when running a session, not in a preview."
            )
        layout.addWidget(buttonBox)
        self.resize(720, 560)

    def _build_matrix(self) -> QtWidgets.QScrollArea:
        """The item × scale-point radio matrix, in a scroll area."""
        survey = self.survey
        grid = QtWidgets.QGridLayout()
        grid.setHorizontalSpacing(12)
        # Header row: each scale value with its anchor underneath.
        for col, value in enumerate(range(survey.scale_min, survey.scale_max + 1)):
            anchor = survey.anchor_for(value)
            text = f"{value}\n{anchor}" if anchor else str(value)
            header = QtWidgets.QLabel(text, self)
            header.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
            header.setWordWrap(True)
            grid.addWidget(header, 0, col + 1)
        for row, item in enumerate(survey.items, start=1):
            label = QtWidgets.QLabel(item, self)
            label.setWordWrap(True)
            grid.addWidget(label, row, 0)
            group = QtWidgets.QButtonGroup(self)
            for col, value in enumerate(range(survey.scale_min, survey.scale_max + 1)):
                radio = QtWidgets.QRadioButton(self)
                anchor = survey.anchor_for(value)
                if anchor:
                    radio.setToolTip(anchor)
                group.addButton(radio, value)
                cell = QtWidgets.QHBoxLayout()
                cell.setContentsMargins(0, 0, 0, 0)
                cell.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
                cell.addWidget(radio)
                holder = QtWidgets.QWidget(self)
                holder.setLayout(cell)
                grid.addWidget(holder, row, col + 1)
            self._groups.append(group)
        grid.setColumnStretch(0, 1)

        inner = QtWidgets.QWidget(self)
        inner.setLayout(grid)
        scroll = QtWidgets.QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setWidget(inner)
        return scroll

    # ----- responses ------------------------------------------------------------

    def responses(self) -> list[int | None]:
        """One scale value per item, in order (None where unanswered)."""
        out: list[int | None] = []
        for group in self._groups:
            checked = group.checkedId()
            out.append(None if checked == -1 else checked)
        return out

    def _on_submit(self) -> None:
        """Confirm gaps, write the response JSON, emit the marker, and close."""
        session = self.session
        if session is None or session.session_dir is None:
            return  # Submit is disabled in previews; belt and braces.
        responses = self.responses()
        unanswered = sum(1 for r in responses if r is None)
        if unanswered:
            reply = QtWidgets.QMessageBox.question(
                self,
                self.survey.name,
                f"{unanswered} item(s) are unanswered. Submit anyway?",
            )
            if reply != QtWidgets.QMessageBox.StandardButton.Yes:
                return
        payload = surveys.response_payload(
            self.survey,
            responses,
            metadata=session.metadata,
            opened=self.opened_at,
            submitted=datetime.now(),
            elapsed=session.elapsed_since_recording(),
            report_number=self.report_number,
            notes=self.notesEdit.text(),
        )
        stem = surveys.response_filename(
            self.survey.key,
            report_number=self.report_number,
            ordinal=surveys.next_response_ordinal(session.session_dir),
        )
        path = surveys.unique_response_path(session.session_dir, stem)
        try:
            path.write_text(
                json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
        except OSError as exc:
            session.show_error_popup(
                "Could not save the survey responses.", str(exc), parent=self
            )
            return
        session.emit_event(
            "SurveySubmitted", detail=f"{self.survey.name} ({path.name})"
        )
        self.accept()
