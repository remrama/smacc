"""Intercom window: live talk (experimenter -> participant) and listen (back) (#20).

Two independent one-direction bridges: **Talk** pipes the experimenter's mic to the
participant's output (``speak_to_participant``), and **Listen** pipes the participant's mic
(``bedroom_mic_1``) to the control-room output (``listen_to_participant``). Each is a pair of
single-direction streams bridged by a queue + resampler, so mismatched device rates
are fine, and the two can run together (full duplex).

Below the voice controls sits the **text chat** (#92): the experimenter's view of
the typed channel for hearing-impaired participants, sharing a transcript with the
participant-facing window (:mod:`smacc.panels.chat`). A section rather than a
Voice/Text mode toggle, on purpose — voice and text run together (a participant may
read text but reply by voice), and nothing live should hide behind an inactive tab.
"""

from __future__ import annotations

import queue
from functools import partial

import sounddevice as sd
from PyQt6 import QtCore, QtGui, QtWidgets

from .. import audio, devices
from ..dialogs import ManageChatPresetsDialog
from ..session import SmaccSession
from .base import (
    PanelWindow,
    describe_action,
    describe_equipment,
    make_section_title,
    require_device,
    require_equipment_device,
)
from .chat import EXPERIMENTER, ChatPresets, ChatTranscript, post_chat_message
from .meter import LevelMeter

# Cap an experimenter prompt's button label so a long standardized question doesn't
# stretch the panel; the full text rides along in the tooltip/status tip.
_PRESET_LABEL_LIMIT = 48


def _elide(text: str, limit: int = _PRESET_LABEL_LIMIT) -> str:
    """Shorten ``text`` to ``limit`` chars with an ellipsis (full text in a tooltip)."""
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


class _Bridge:
    """A one-direction live audio bridge: an input device piped to an output device.

    The input and output run as separate streams at their own native rates, bridged
    by a queue + linear resampler. On overrun a block is dropped rather than blocking
    the audio thread.
    """

    def __init__(self) -> None:
        self._input: sd.InputStream | None = None
        self._output: sd.OutputStream | None = None
        self._queue: queue.Queue | None = None
        self._resampler: audio.LinearResampler | None = None
        # Latest input level (dBFS), stashed by the audio callback for the
        # window's level meters (a plain float store; the GUI timer reads it).
        self.level_db = audio.FLOOR_DBFS

    def active(self) -> bool:
        """True while either stream is open."""
        return self._input is not None or self._output is not None

    def start(
        self, input_device: int | str | None, output_device: int | str | None
    ) -> None:
        """Open and start the streams; raises (and tears down) on a PortAudio error."""
        try:
            in_rate = int(sd.query_devices(input_device, "input")["default_samplerate"])
            out_rate = int(
                sd.query_devices(output_device, "output")["default_samplerate"]
            )
            self._queue = queue.Queue(maxsize=32)
            self._resampler = audio.LinearResampler(in_rate, out_rate)
            self._input = sd.InputStream(
                samplerate=in_rate,
                channels=1,
                device=input_device,
                callback=self._in_callback,
            )
            self._output = sd.OutputStream(
                samplerate=out_rate,
                channels=1,
                device=output_device,
                callback=self._out_callback,
            )
            self._input.start()
            self._output.start()
        except Exception:
            self.stop()
            raise

    def stop(self) -> bool:
        """Tear down both streams; return True if either was running."""
        stopped = False
        for stream in (self._input, self._output):
            if stream is not None:
                stream.abort()
                stream.close()
                stopped = True
        self._input = None
        self._output = None
        self._queue = None
        self._resampler = None
        self.level_db = audio.FLOOR_DBFS
        return stopped

    def _in_callback(self, indata, frames, time, status) -> None:
        self.level_db = audio.rms_dbfs(indata)
        if self._queue is not None:
            try:
                self._queue.put_nowait(indata[:, 0].copy())
            except queue.Full:
                pass  # output not keeping up; drop a block rather than block

    def _out_callback(self, outdata, frames, time, status) -> None:
        if self._queue is not None and self._resampler is not None:
            while True:
                try:
                    self._resampler.push(self._queue.get_nowait())
                except queue.Empty:
                    break
            outdata[:, 0] = self._resampler.pull(frames)
        else:
            outdata.fill(0)


class IntercomWindow(PanelWindow):
    """Talk to the participant (push-to-talk) and listen back, in either direction."""

    TITLE = "Intercom"

    # Asks the main window to show + activate the participant chat window. Routed
    # there because activating it is also how the machine's single keyboard focus
    # is handed to the participant (see panels/chat.py).
    open_participant_chat = QtCore.pyqtSignal()

    def __init__(
        self,
        session: SmaccSession,
        transcript: ChatTranscript | None = None,
        presets: ChatPresets | None = None,
        parent: QtWidgets.QWidget | None = None,
    ):
        super().__init__(session, parent)
        self._talk = _Bridge()  # experimenter mic -> participant output
        self._listen = _Bridge()  # participant mic -> control-room output
        self._talk_push = False  # True while talk is held via the spacebar
        # Renders each live bridge's input level onto its meter; runs only while
        # a direction is on (started/stopped by the toggles).
        self._level_timer = QtCore.QTimer(self)
        self._level_timer.setInterval(50)  # ~20 Hz display refresh
        self._level_timer.timeout.connect(self._render_levels)
        self._transcript = (
            transcript if transcript is not None else ChatTranscript(self)
        )
        self._presets = presets if presets is not None else ChatPresets(self)
        self.setCentralWidget(self._build())
        self._transcript.message_posted.connect(self._append_chat_message)
        self._presets.changed.connect(self._rebuild_preset_buttons)
        self._rebuild_preset_buttons()
        # App-wide spacebar push-to-talk works regardless of the focused window.
        app = QtWidgets.QApplication.instance()
        if app is not None:
            app.installEventFilter(self)

    def _build(self) -> QtWidgets.QWidget:
        # Devices are chosen in the Devices window; show where each direction routes.
        self.talkDeviceLabel = QtWidgets.QLabel(self)
        self.listenDeviceLabel = QtWidgets.QLabel(self)
        self.refresh_device_indicator()

        talkButton = QtWidgets.QPushButton("Talk (to participant)", self)
        talkButton.setStatusTip(
            "Click to latch on/off, or press and hold the spacebar to talk "
            "(push-to-talk). Warning: risks feedback near open speakers."
        )
        talkButton.setCheckable(True)
        talkButton.toggled.connect(self.toggle_talk)
        self.talkButton = talkButton

        listenButton = QtWidgets.QPushButton("Listen (to participant)", self)
        listenButton.setStatusTip(
            "Hear the participant's mic on the control-room output (set the route in "
            "the Devices window)."
        )
        listenButton.setCheckable(True)
        listenButton.toggled.connect(self.toggle_listen)
        self.listenButton = listenButton

        # A level meter beside each direction, fed from that bridge's live input
        # callback — signal on the bar means audio is actually flowing (your mic
        # for Talk, the participant's mic for Listen), not just a latched button.
        self.talkMeter = LevelMeter(self)
        self.talkMeter.setStatusTip("Your mic's live level while Talk is on.")
        self.listenMeter = LevelMeter(self)
        self.listenMeter.setStatusTip(
            "The participant mic's live level while Listen is on."
        )
        talkRow = QtWidgets.QHBoxLayout()
        talkRow.addWidget(talkButton, 1)
        talkRow.addWidget(self.talkMeter, 1)
        listenRow = QtWidgets.QHBoxLayout()
        listenRow.addWidget(listenButton, 1)
        listenRow.addWidget(self.listenMeter, 1)

        # --- Text chat (#92): the experimenter's view of the typed channel -----
        chatView = QtWidgets.QPlainTextEdit(self)
        chatView.setReadOnly(True)
        chatView.setMinimumHeight(120)
        chatView.setStatusTip(
            "The typed conversation (always recorded in the session log)."
        )
        self.chatView = chatView

        chatEntry = QtWidgets.QLineEdit(self)
        chatEntry.setPlaceholderText("Type to the participant…")
        chatEntry.setStatusTip(
            "Enter sends; Ctrl+Enter sends and passes the keyboard to the participant."
        )
        chatEntry.returnPressed.connect(self.send_chat_message)
        self.chatEntry = chatEntry
        # Ctrl+Enter = send-and-pass, only while the entry itself has focus.
        sendAndPass = QtGui.QShortcut(QtGui.QKeySequence("Ctrl+Return"), chatEntry)
        sendAndPass.setContext(QtCore.Qt.ShortcutContext.WidgetShortcut)
        sendAndPass.activated.connect(self.send_and_pass_keyboard)

        sendButton = QtWidgets.QPushButton("Send", self)
        sendButton.setStatusTip("Show the typed message to the participant.")
        sendButton.clicked.connect(self.send_chat_message)
        entryRow = QtWidgets.QHBoxLayout()
        entryRow.addWidget(chatEntry, 1)
        entryRow.addWidget(sendButton)

        passButton = QtWidgets.QPushButton("Pass keyboard to participant", self)
        passButton.setStatusTip(
            "Show the participant chat window and give it keyboard focus — the "
            "machine has one focus, so only one side can type at a time."
        )
        passButton.clicked.connect(self.open_participant_chat.emit)

        # Quick messages (#112): one-click standardized prompts, sent verbatim through
        # the same path as a typed message. Rebuilt from the shared presets.
        self._presetContainer = QtWidgets.QWidget(self)
        self._presetLayout = QtWidgets.QVBoxLayout(self._presetContainer)
        self._presetLayout.setContentsMargins(0, 0, 0, 0)
        self._preset_buttons: list[QtWidgets.QPushButton] = []

        manageButton = QtWidgets.QPushButton("Manage quick messages…", self)
        manageButton.setStatusTip(
            "Add, edit, or reorder the experimenter prompts and the participant's "
            "number-key replies (saved with the study)."
        )
        manageButton.clicked.connect(self.manage_presets)

        layout = QtWidgets.QFormLayout()
        layout.setLabelAlignment(QtCore.Qt.AlignmentFlag.AlignRight)
        layout.addRow(make_section_title("Intercom"))
        layout.addRow("To participant:", self.talkDeviceLabel)
        layout.addRow(talkRow)
        layout.addRow("From participant:", self.listenDeviceLabel)
        layout.addRow(listenRow)
        layout.addRow(make_section_title("Text chat"))
        layout.addRow(chatView)
        layout.addRow(self._presetContainer)
        layout.addRow(entryRow)
        layout.addRow(passButton)
        layout.addRow(manageButton)
        central = QtWidgets.QWidget()
        central.setLayout(layout)
        return central

    def send_chat_message(self) -> None:
        """Post the typed entry to the shared transcript (logged; marker if enabled)."""
        posted = post_chat_message(
            self.session, self._transcript, EXPERIMENTER, self.chatEntry.text()
        )
        if posted is not None:
            self.chatEntry.clear()

    def send_and_pass_keyboard(self) -> None:
        """Send the entry (if any), then hand the keyboard to the participant."""
        self.send_chat_message()
        self.open_participant_chat.emit()

    def _append_chat_message(self, sender: str, text: str) -> None:
        name = "You" if sender == EXPERIMENTER else "Participant"
        self.chatView.appendPlainText(f"{name}:  {text}")
        scrollbar = self.chatView.verticalScrollBar()
        if scrollbar is not None:
            scrollbar.setValue(scrollbar.maximum())

    # ----- quick messages (#112) ----------------------------------------------

    def _rebuild_preset_buttons(self) -> None:
        """Rebuild the one-click prompt buttons from the shared presets."""
        for button in self._preset_buttons:
            button.deleteLater()
        self._preset_buttons = []
        for text in self._presets.experimenter:
            button = QtWidgets.QPushButton(_elide(text), self._presetContainer)
            button.setToolTip(text)
            button.setStatusTip(f"Send to the participant: {text}")
            button.clicked.connect(partial(self._send_preset, text))
            self._presetLayout.addWidget(button)
            self._preset_buttons.append(button)
        self._presetContainer.setVisible(bool(self._preset_buttons))

    def _send_preset(self, text: str) -> None:
        """Send a standardized prompt through the same path as a typed message."""
        post_chat_message(self.session, self._transcript, EXPERIMENTER, text)

    def manage_presets(self) -> None:
        """Edit both preset lists; on accept, update the shared presets in place."""
        dialog = ManageChatPresetsDialog(
            self._presets.experimenter, self._presets.participant, parent=self
        )
        if dialog.exec():
            experimenter, participant = dialog.get_presets()
            self._presets.set(experimenter, participant)  # -> both views rebuild
            self.session.log_interaction("Edited chat quick-reply presets")

    def refresh_device_indicator(self) -> None:
        """Show both halves of each direction (devices set in the Devices window).

        Talk and Listen are mic → output paths, so each indicator shows the
        output route plus the source mic ("• mic: …"), the same separator idiom
        the Audio cue window uses for its monitor.
        """
        talk = describe_action(self.session, "speak_to_participant")
        talk += f"   •   mic: {describe_equipment(self.session, devices.TALK_SOURCE)}"
        self.talkDeviceLabel.setText(talk)
        listen = describe_action(self.session, "listen_to_participant")
        listen += (
            f"   •   mic: {describe_equipment(self.session, devices.LISTEN_SOURCE)}"
        )
        self.listenDeviceLabel.setText(listen)

    def is_streaming(self) -> bool:
        """True while either direction is live."""
        return self._talk.active() or self._listen.active()

    def _sync_level_timer(self) -> None:
        """Run the meter refresh only while a direction is live; clear idle bars."""
        if self.is_streaming():
            if not self._level_timer.isActive():
                self._level_timer.start()
        else:
            self._level_timer.stop()
        self._render_levels()

    def _render_levels(self) -> None:
        """GUI-thread timer: render each live bridge's input level onto its meter."""
        for bridge, meter in (
            (self._talk, self.talkMeter),
            (self._listen, self.listenMeter),
        ):
            if bridge.active():
                meter.show_level(bridge.level_db)
            else:
                meter.clear_level()

    def toggle_talk(self, enabled: bool) -> None:
        """Start/stop piping the experimenter mic to the participant output.

        Marked in the EEG record via LSL (the experimenter's voice is a manipulation
        the participant hears). The mic is the Control-room mic equipment (#160),
        the output the ``speak_to_participant`` route — both pinned by name,
        like every other audio path.
        """
        if enabled:
            mic = require_equipment_device(
                self.session,
                devices.TALK_SOURCE,
                devices.INPUT,
                failure="Could not start intercom talk.",
                parent=self,
            )
            if mic is None:
                self.talkButton.setChecked(False)
                return
            output = require_device(
                self.session,
                "speak_to_participant",
                devices.OUTPUT,
                failure="Could not start intercom talk.",
                parent=self,
            )
            if output is None:
                self.talkButton.setChecked(False)
                return
            try:
                self._talk.start(mic, output)
            except Exception as exc:  # PortAudio errors, no device, busy, etc.
                self.session.show_error_popup(
                    "Could not start intercom talk.", str(exc), parent=self
                )
                self.talkButton.setChecked(False)
                return
            self.session.emit_event("IntercomStarted")
        elif self._talk.stop():
            self.session.emit_event("IntercomStopped")
        self._sync_level_timer()

    def toggle_listen(self, enabled: bool) -> None:
        """Start/stop piping the participant mic to the control-room output.

        Passive monitoring (no EEG marker), the reverse of Talk: the bedroom mic is
        the source, the ``listen_to_participant`` route the destination.
        """
        if enabled:
            mic = require_equipment_device(
                self.session,
                devices.LISTEN_SOURCE,
                devices.INPUT,
                failure="Could not start intercom listen.",
                parent=self,
            )
            if mic is None:
                self.listenButton.setChecked(False)
                return
            output = require_device(
                self.session,
                "listen_to_participant",
                devices.OUTPUT,
                failure="Could not start intercom listen.",
                parent=self,
            )
            if output is None:
                self.listenButton.setChecked(False)
                return
            try:
                self._listen.start(mic, output)
            except Exception as exc:  # PortAudio errors, no device, busy, etc.
                self.session.show_error_popup(
                    "Could not start intercom listen.", str(exc), parent=self
                )
                self.listenButton.setChecked(False)
                return
            self.session.log_interaction("Intercom listen on")
        else:
            self._listen.stop()
            self.session.log_interaction("Intercom listen off")
        self._sync_level_timer()

    @staticmethod
    def _is_text_widget_focused() -> bool:
        """True if a text-entry widget has focus (so space should type, not talk)."""
        widget = QtWidgets.QApplication.focusWidget()
        return isinstance(
            widget,
            (
                QtWidgets.QLineEdit,
                QtWidgets.QAbstractSpinBox,
                QtWidgets.QTextEdit,
                QtWidgets.QPlainTextEdit,
            ),
        )

    def eventFilter(self, obj, event) -> bool:
        """Application-wide spacebar push-to-talk for the Talk direction.

        Installed on the QApplication so it sees the spacebar regardless of which
        widget/window has focus. Hold space to talk, release to stop; auto-repeat
        is swallowed so the intercom never rapidly toggles. Space passes through
        untouched while a text-entry widget is focused, so typing still works.
        """
        etype = event.type()
        if (
            etype in (QtCore.QEvent.Type.KeyPress, QtCore.QEvent.Type.KeyRelease)
            and event.key() == QtCore.Qt.Key.Key_Space
            and not self._is_text_widget_focused()
        ):
            if etype == QtCore.QEvent.Type.KeyPress:
                if not event.isAutoRepeat() and not self.talkButton.isChecked():
                    self._talk_push = True
                    self.talkButton.setChecked(True)  # -> toggle_talk(True)
            elif not event.isAutoRepeat() and self._talk_push:
                self._talk_push = False
                self.talkButton.setChecked(False)  # -> toggle_talk(False)
            return True  # consume so the focused widget doesn't also see space
        return super().eventFilter(obj, event)

    # ----- persisted state ----------------------------------------------------

    def gather_state(self) -> dict:
        """Persist the quick-reply presets (the shared object's view)."""
        return self._presets.gather_state()

    def apply_state(self, state: dict) -> None:
        """Load the quick-reply presets; both chat views rebuild via the signal."""
        self._presets.apply_state(state)

    def cleanup(self) -> None:
        app = QtWidgets.QApplication.instance()
        if app is not None:
            app.removeEventFilter(self)
        self._level_timer.stop()
        self._talk.stop()
        self._listen.stop()
