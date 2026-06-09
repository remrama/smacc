"""Intercom window: live experimenter-mic -> participant-output routing (#20)."""

from __future__ import annotations

import queue

import sounddevice as sd
from PyQt6 import QtCore, QtWidgets

from .. import audio
from ..session import SmaccSession
from .base import ModalityWindow, describe_target, make_section_title


class IntercomWindow(ModalityWindow):
    """Talk to the participant; latch with the button or hold spacebar (push-to-talk)."""

    TITLE = "Intercom"

    def __init__(self, session: SmaccSession, parent: QtWidgets.QWidget | None = None):
        super().__init__(session, parent)
        self.intercom_input_stream: sd.InputStream | None = None
        self.intercom_output_stream: sd.OutputStream | None = None
        self._intercom_queue: queue.Queue | None = None
        self._intercom_resampler: audio.LinearResampler | None = None
        self._intercom_push_to_talk = False  # True while held via spacebar
        self.setCentralWidget(self._build())
        # App-wide spacebar push-to-talk works regardless of the focused window.
        app = QtWidgets.QApplication.instance()
        if app is not None:
            app.installEventFilter(self)

    def _build(self) -> QtWidgets.QWidget:
        # The participant's output device is chosen in the Devices window.
        self.deviceLabel = QtWidgets.QLabel(self)
        self.deviceLabel.setStatusTip(
            "Set in the Devices window (Intercom → participant)."
        )
        self.refresh_device_indicator()

        intercomButton = QtWidgets.QPushButton("Intercom (talk)", self)
        intercomButton.setStatusTip(
            "Click to latch the intercom on/off, or press and hold the spacebar to "
            "talk (push-to-talk). Warning: risks feedback near open speakers."
        )
        intercomButton.setCheckable(True)
        intercomButton.toggled.connect(self.toggle_intercom)
        self.intercomButton = intercomButton

        layout = QtWidgets.QFormLayout()
        layout.setLabelAlignment(QtCore.Qt.AlignmentFlag.AlignRight)
        layout.addRow(make_section_title("Intercom"))
        layout.addRow("To participant:", self.deviceLabel)
        layout.addRow(intercomButton)
        central = QtWidgets.QWidget()
        central.setLayout(layout)
        return central

    def refresh_device_indicator(self) -> None:
        """Show where the participant output resolves (set in the Devices window)."""
        self.deviceLabel.setText(describe_target(self.session, "intercom_talk"))

    def is_streaming(self) -> bool:
        """True while the intercom is live (mic/output streams open)."""
        return (
            self.intercom_input_stream is not None
            or self.intercom_output_stream is not None
        )

    def toggle_intercom(self, enabled: bool) -> None:
        """Start/stop routing the experimenter mic to the participant output.

        Two single-direction streams (each at its device's native rate) bridged by
        a queue + resampler, so mismatched sample rates are fine. Logged and marked
        in the EEG record via LSL. Warning: a mic near open speakers risks feedback.
        """
        if enabled:
            output_device = self.session.devices.device_for("intercom_talk") or None
            if not self._start_intercom_streams(output_device):
                self.intercomButton.setChecked(False)
                return
            self.session.emit_event("IntercomStarted")
        elif self._stop_intercom_streams():
            self.session.emit_event("IntercomStopped")

    def _start_intercom_streams(self, output_device: str | None) -> bool:
        """Build and start the mic/output streams; return True on success.

        On any PortAudio error (no device, busy, etc.) the partial streams are torn
        down and an error popup is shown; the caller is responsible for resetting any
        UI state (e.g. unchecking the talk button).
        """
        try:
            in_rate = int(sd.query_devices(kind="input")["default_samplerate"])
            out_info = (
                sd.query_devices(output_device, "output")
                if output_device
                else sd.query_devices(kind="output")
            )
            out_rate = int(out_info["default_samplerate"])
            self._intercom_queue = queue.Queue(maxsize=32)
            self._intercom_resampler = audio.LinearResampler(in_rate, out_rate)
            self.intercom_input_stream = sd.InputStream(
                samplerate=in_rate,
                channels=1,
                callback=self._intercom_in_callback,
            )
            self.intercom_output_stream = sd.OutputStream(
                samplerate=out_rate,
                channels=1,
                device=output_device,
                callback=self._intercom_out_callback,
            )
            self.intercom_input_stream.start()
            self.intercom_output_stream.start()
        except Exception as exc:  # PortAudio errors, no device, etc.
            self._stop_intercom_streams()
            self.session.show_error_popup(
                "Could not start intercom.", str(exc), parent=self
            )
            return False
        return True

    def _stop_intercom_streams(self) -> bool:
        """Tear down both intercom streams; return True if any were running."""
        stopped = False
        for attr in ("intercom_input_stream", "intercom_output_stream"):
            stream = getattr(self, attr)
            if stream is not None:
                stream.abort()
                stream.close()
                setattr(self, attr, None)
                stopped = True
        self._intercom_queue = None
        self._intercom_resampler = None
        return stopped

    def _intercom_in_callback(self, indata, frames, time, status) -> None:
        """Mic stream (audio thread): queue captured frames for the output stream."""
        if self._intercom_queue is not None:
            try:
                self._intercom_queue.put_nowait(indata[:, 0].copy())
            except queue.Full:
                pass  # output not keeping up; drop a block rather than block

    def _intercom_out_callback(self, outdata, frames, time, status) -> None:
        """Output stream (audio thread): resample queued mic frames to the device."""
        if self._intercom_queue is not None and self._intercom_resampler is not None:
            while True:
                try:
                    self._intercom_resampler.push(self._intercom_queue.get_nowait())
                except queue.Empty:
                    break
            outdata[:, 0] = self._intercom_resampler.pull(frames)
        else:
            outdata.fill(0)

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
        """Application-wide spacebar push-to-talk for the intercom.

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
                if not event.isAutoRepeat() and not self.intercomButton.isChecked():
                    self._intercom_push_to_talk = True
                    self.intercomButton.setChecked(True)  # -> toggle_intercom(True)
            elif not event.isAutoRepeat() and self._intercom_push_to_talk:
                self._intercom_push_to_talk = False
                self.intercomButton.setChecked(False)  # -> toggle_intercom(False)
            return True  # consume so the focused widget doesn't also see space
        return super().eventFilter(obj, event)

    def cleanup(self) -> None:
        app = QtWidgets.QApplication.instance()
        if app is not None:
            app.removeEventFilter(self)
        self._stop_intercom_streams()
