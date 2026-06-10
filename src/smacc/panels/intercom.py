"""Intercom window: live talk (experimenter -> participant) and listen (back) (#20).

Two independent one-direction bridges: **Talk** pipes the experimenter's mic to the
participant's output (``intercom_talk``), and **Listen** pipes the participant's mic
(``bedroom_mic``) to the control-room output (``intercom_listen``). Each is a pair of
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

import sounddevice as sd
from PyQt6 import QtCore, QtGui, QtWidgets

from .. import audio, devices
from ..session import SmaccSession
from .base import ModalityWindow, describe_target, make_section_title
from .chat import EXPERIMENTER, ChatTranscript, post_chat_message


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

    def active(self) -> bool:
        """True while either stream is open."""
        return self._input is not None or self._output is not None

    def start(self, input_device: str | None, output_device: str | None) -> None:
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
        return stopped

    def _in_callback(self, indata, frames, time, status) -> None:
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


class IntercomWindow(ModalityWindow):
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
        parent: QtWidgets.QWidget | None = None,
    ):
        super().__init__(session, parent)
        self._talk = _Bridge()  # experimenter mic -> participant output
        self._listen = _Bridge()  # participant mic -> control-room output
        self._talk_push = False  # True while talk is held via the spacebar
        self._transcript = (
            transcript if transcript is not None else ChatTranscript(self)
        )
        self.setCentralWidget(self._build())
        self._transcript.message_posted.connect(self._append_chat_message)
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

        layout = QtWidgets.QFormLayout()
        layout.setLabelAlignment(QtCore.Qt.AlignmentFlag.AlignRight)
        layout.addRow(make_section_title("Intercom"))
        layout.addRow("To participant:", self.talkDeviceLabel)
        layout.addRow(talkButton)
        layout.addRow("From participant:", self.listenDeviceLabel)
        layout.addRow(listenButton)
        layout.addRow(make_section_title("Text chat"))
        layout.addRow(chatView)
        layout.addRow(entryRow)
        layout.addRow(passButton)
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

    def refresh_device_indicator(self) -> None:
        """Show where each direction routes (devices set in the Devices window)."""
        self.talkDeviceLabel.setText(describe_target(self.session, "intercom_talk"))
        self.listenDeviceLabel.setText(describe_target(self.session, "intercom_listen"))

    def is_streaming(self) -> bool:
        """True while either direction is live."""
        return self._talk.active() or self._listen.active()

    def toggle_talk(self, enabled: bool) -> None:
        """Start/stop piping the experimenter mic to the participant output.

        Marked in the EEG record via LSL (the experimenter's voice is a manipulation
        the participant hears). The mic is the system default input.
        """
        if enabled:
            output = self.session.devices.device_for("intercom_talk") or None
            try:
                self._talk.start(None, output)
            except Exception as exc:  # PortAudio errors, no device, busy, etc.
                self.session.show_error_popup(
                    "Could not start intercom talk.", str(exc), parent=self
                )
                self.talkButton.setChecked(False)
                return
            self.session.emit_event("IntercomStarted")
        elif self._talk.stop():
            self.session.emit_event("IntercomStopped")

    def toggle_listen(self, enabled: bool) -> None:
        """Start/stop piping the participant mic to the control-room output.

        Passive monitoring (no EEG marker), the reverse of Talk: the bedroom mic is
        the source, the ``intercom_listen`` route the destination.
        """
        if enabled:
            mic = (
                self.session.devices.device_for_role(devices.LISTEN_SOURCE_ROLE) or None
            )
            output = self.session.devices.device_for("intercom_listen") or None
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

    def cleanup(self) -> None:
        app = QtWidgets.QApplication.instance()
        if app is not None:
            app.removeEventFilter(self)
        self._talk.stop()
        self._listen.stop()
