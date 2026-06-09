"""Intercom window: live talk (experimenter -> participant) and listen (back) (#20).

Two independent one-direction bridges: **Talk** pipes the experimenter's mic to the
participant's output (``intercom_talk``), and **Listen** pipes the participant's mic
(``bedroom_mic``) to the control-room output (``intercom_listen``). Each is a pair of
single-direction streams bridged by a queue + resampler, so mismatched device rates
are fine, and the two can run together (full duplex).
"""

from __future__ import annotations

import queue

import sounddevice as sd
from PyQt6 import QtCore, QtWidgets

from .. import audio, devices
from ..session import SmaccSession
from .base import ModalityWindow, describe_target, make_section_title


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

    def __init__(self, session: SmaccSession, parent: QtWidgets.QWidget | None = None):
        super().__init__(session, parent)
        self._talk = _Bridge()  # experimenter mic -> participant output
        self._listen = _Bridge()  # participant mic -> control-room output
        self._talk_push = False  # True while talk is held via the spacebar
        self.setCentralWidget(self._build())
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

        layout = QtWidgets.QFormLayout()
        layout.setLabelAlignment(QtCore.Qt.AlignmentFlag.AlignRight)
        layout.addRow(make_section_title("Intercom"))
        layout.addRow("To participant:", self.talkDeviceLabel)
        layout.addRow(talkButton)
        layout.addRow("From participant:", self.listenDeviceLabel)
        layout.addRow(listenButton)
        central = QtWidgets.QWidget()
        central.setLayout(layout)
        return central

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
