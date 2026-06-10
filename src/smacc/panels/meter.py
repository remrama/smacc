"""Reusable level meters shared by the recorder and the cue monitor (#37).

Two small widgets, both rendering a dBFS bar:

* :class:`LevelMeter` displays a level you feed it from outside — the cue panel's
  output "sending" meter pushes the block it emits here, so it never owns a stream.
* :class:`InputLevelMeter` drives itself from a sounddevice input stream and tracks
  a rolling ambient baseline, so a faint cue's *rise* above the room noise shows
  even when the absolute level is low.

The absolute level is always the bar (it can't collapse to zero on a sustained
sound); the baseline only adds a "+N dB above floor" readout in the text.
"""

from __future__ import annotations

import sounddevice as sd
from PyQt6 import QtCore, QtWidgets

from .. import audio


class LevelMeter(QtWidgets.QProgressBar):
    """A dBFS level bar fed from outside (no stream of its own).

    Used for the cue panel's output "sending" meter: the audio callback measures the
    block it emits and pushes it here via :meth:`show_level`. This confirms SMACC is
    *emitting* a cue — a diagnostic, not proof the bedroom speaker actually sounded
    (only a mic can confirm that; see :class:`InputLevelMeter`).
    """

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.setRange(0, 100)
        self.setValue(0)
        self.setTextVisible(True)
        self.setFormat("")

    def show_level(self, db: float) -> None:
        """Render ``db`` dBFS onto the bar (value + text)."""
        self.setValue(audio.dbfs_to_meter(db))
        self.setFormat(f"{db:.0f} dBFS")

    def clear_level(self) -> None:
        """Reset the bar to empty (e.g. when playback stops)."""
        self.setValue(0)
        self.setFormat("")


class InputLevelMeter(LevelMeter):
    """A level meter that drives itself from a sounddevice input stream.

    Owns the :class:`sounddevice.InputStream` and a ~20 Hz refresh timer; the audio
    callback stashes the latest level and the timer renders it. A rolling
    :class:`smacc.audio.AmbientBaseline` adds a "+N dB above floor" readout so a
    cue that lifts a cheap mic only a little above the room noise is still visible.

    The stream is the panel's, so a panel that embeds this must report it from
    ``is_streaming()`` (a device rescan re-inits PortAudio and would cut it).
    """

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self._stream: sd.InputStream | None = None
        self._level_db = audio.FLOOR_DBFS
        self._baseline = audio.AmbientBaseline()
        self._timer = QtCore.QTimer(self)
        self._timer.setInterval(50)  # ~20 Hz display refresh
        self._timer.timeout.connect(self._refresh)

    def is_active(self) -> bool:
        """True while the input stream is open."""
        return self._stream is not None

    def start(self, device: int | str | None) -> None:
        """Open the input stream on ``device`` (raises on a PortAudio error).

        The caller surfaces any error (and reverts its toggle); this leaves the meter
        stopped on failure. A fresh start forgets the previous room's baseline.
        """
        self.stop()
        self._baseline.reset()
        self._level_db = audio.FLOOR_DBFS
        stream = sd.InputStream(channels=1, device=device, callback=self._capture)
        stream.start()
        self._stream = stream
        self._timer.start()

    def stop(self) -> None:
        """Close the input stream and clear the bar (safe to call when stopped)."""
        self._timer.stop()
        if self._stream is not None:
            self._stream.abort()
            self._stream.close()
            self._stream = None
        self.clear_level()

    def _capture(self, indata, frames, time, status) -> None:
        """sounddevice callback (audio thread): stash the latest input level."""
        self._level_db = audio.rms_dbfs(indata)

    def _refresh(self) -> None:
        """GUI-thread timer: render absolute level + the rise above the room floor."""
        db = self._level_db
        rise = self._baseline.update(db)
        self.setValue(audio.dbfs_to_meter(db))
        self.setFormat(f"{db:.0f} dBFS  (+{rise:.0f})")
