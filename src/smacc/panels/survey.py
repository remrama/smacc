"""In-app survey window: render a survey and save its responses to the run folder.

Opened by the Dream-recording panel for any ``smacc://survey/<key>`` selection —
auto-opened when a dream report starts recording (attached to that report's
number) or standalone from File → Surveys. Non-modal on purpose: the operator
must keep the intercom reachable while administering a questionnaire to a
participant who is in bed in the dark.

Items render by type (#118): a run of consecutive Likert items collapses into one
shared-scale radio matrix (the original single-scale look); ``select`` items are
dropdowns, ``number`` and ``text`` are free entry, and ``heading`` items are
display-only section titles. Submitting writes one JSON file per administration
into the run folder (named to sort beside the report it accompanies; see
:func:`smacc.surveys.response_filename`) and emits the ``SurveySubmitted`` marker.
Without a run folder (the study designer, or a preview from the Manage-surveys
dialog) the survey renders for inspection but Submit is disabled, mirroring how
the record button is gated.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import datetime
from typing import Any

from PyQt6 import QtCore, QtWidgets

from .. import surveys
from ..session import SmaccSession
from .base import make_section_title


class SurveyWindow(QtWidgets.QDialog):
    """Administer one survey: typed item widgets, optional notes, and Submit.

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
        # The Likert radio groups, in item order (kept for tests/inspection), and
        # one (item, control, value-getter) per responding item, also in order, so
        # responses() lines up with survey.response_items. ``control`` is the
        # QButtonGroup (Likert) or the input widget (select/number/text).
        self._groups: list[QtWidgets.QButtonGroup] = []
        self._fields: list[tuple[surveys.SurveyItem, QtCore.QObject, Callable[[], Any]]]
        self._fields = []
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

        layout.addWidget(self._build_body(), 1)

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

    def _build_body(self) -> QtWidgets.QScrollArea:
        """Render items in order: Likert runs as matrices, other types as rows."""
        container = QtWidgets.QWidget(self)
        vbox = QtWidgets.QVBoxLayout(container)
        vbox.setContentsMargins(0, 0, 0, 0)
        items = list(self.survey.items)
        index = 0
        while index < len(items):
            if items[index].type == surveys.LIKERT:
                run = []
                while index < len(items) and items[index].type == surveys.LIKERT:
                    run.append(items[index])
                    index += 1
                vbox.addWidget(self._build_likert_matrix(run))
            else:
                vbox.addWidget(self._build_item_row(items[index]))
                index += 1
        vbox.addStretch(1)

        scroll = QtWidgets.QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setWidget(container)
        return scroll

    def _build_likert_matrix(
        self, items: list[surveys.SurveyItem]
    ) -> QtWidgets.QWidget:
        """A radio matrix for a run of Likert items sharing the survey scale."""
        survey = self.survey
        grid = QtWidgets.QGridLayout()
        grid.setHorizontalSpacing(12)
        for col, value in enumerate(range(survey.scale_min, survey.scale_max + 1)):
            anchor = survey.anchor_for(value)
            text = f"{value}\n{anchor}" if anchor else str(value)
            header = QtWidgets.QLabel(text, self)
            header.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
            header.setWordWrap(True)
            grid.addWidget(header, 0, col + 1)
        for row, item in enumerate(items, start=1):
            label = QtWidgets.QLabel(item.text, self)
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
            self._fields.append((item, group, self._likert_getter(group)))
        grid.setColumnStretch(0, 1)
        wrapper = QtWidgets.QWidget(self)
        wrapper.setLayout(grid)
        return wrapper

    def _build_item_row(self, item: surveys.SurveyItem) -> QtWidgets.QWidget:
        """Render a non-Likert item (heading, select, number, or text)."""
        wrapper = QtWidgets.QWidget(self)
        col = QtWidgets.QVBoxLayout(wrapper)
        col.setContentsMargins(0, 4, 0, 4)

        if item.type == surveys.HEADING:
            heading = QtWidgets.QLabel(item.text, self)
            heading.setWordWrap(True)
            font = heading.font()
            font.setBold(True)
            heading.setFont(font)
            col.addWidget(heading)
            if item.help:
                col.addWidget(self._help_label(item.help))
            return wrapper

        label = QtWidgets.QLabel(item.text, self)
        label.setWordWrap(True)
        col.addWidget(label)
        if item.help:
            col.addWidget(self._help_label(item.help))

        field: QtWidgets.QWidget
        getter: Callable[[], Any]
        if item.type == surveys.SELECT:
            field, getter = self._select_field(item)
        elif item.type == surveys.NUMBER:
            field, getter = self._number_field(item)
        else:  # text
            field, getter = self._text_field()
        col.addWidget(field)
        self._fields.append((item, field, getter))
        return wrapper

    def _help_label(self, text: str) -> QtWidgets.QLabel:
        """A wrapped, italic sub-label for an item's help/definition text."""
        help_label = QtWidgets.QLabel(text, self)
        help_label.setWordWrap(True)
        font = help_label.font()
        font.setItalic(True)
        help_label.setFont(font)
        return help_label

    # ----- typed field widgets + getters --------------------------------------

    @staticmethod
    def _likert_getter(group: QtWidgets.QButtonGroup) -> Callable[[], int | None]:
        return lambda: None if group.checkedId() == -1 else group.checkedId()

    def _select_field(
        self, item: surveys.SurveyItem
    ) -> tuple[QtWidgets.QWidget, Callable[[], int | None]]:
        combo = QtWidgets.QComboBox(self)
        combo.addItem("—", None)  # leading blank == unanswered
        for value, label in item.levels:
            combo.addItem(label, value)
        return combo, lambda: combo.currentData()

    def _number_field(
        self, item: surveys.SurveyItem
    ) -> tuple[QtWidgets.QWidget, Callable[[], int | None]]:
        spin = QtWidgets.QSpinBox(self)
        low = item.number_min if item.number_min is not None else 0
        high = item.number_max if item.number_max is not None else 9999
        # One step below the real minimum is the "unanswered" slot, shown as "—"
        # (Qt's special value text), so a number field can be left blank.
        spin.setRange(low - 1, high)
        spin.setValue(low - 1)
        spin.setSpecialValueText("—")
        if item.unit:
            spin.setSuffix(f" {item.unit}")
        return spin, lambda: None if spin.value() < low else spin.value()

    def _text_field(self) -> tuple[QtWidgets.QWidget, Callable[[], str | None]]:
        edit = QtWidgets.QLineEdit(self)
        return edit, lambda: edit.text().strip() or None

    # ----- responses ----------------------------------------------------------

    def responses(self) -> list[Any]:
        """One value per responding item, in order (None where unanswered)."""
        return [getter() for _, _, getter in self._fields]

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
