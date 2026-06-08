"""Per-session shared state: a run folder, logging, and the LSL marker outlet.

The launcher and every modality window hold a reference to one ``SmaccSession``
so they all emit event markers and log lines through a single place. Each run
gets its own folder under ``sessions/`` (named by a launch-timestamp stem) that
holds the log, dream reports, and any exports together. Subject/session are kept
as optional metadata inside the log/exports rather than baked into filenames.
"""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path

from pylsl import StreamInfo, StreamOutlet
from PyQt5 import QtWidgets

from . import bids, events, settings
from .config import PPORT_ADDRESS, VERSION
from .paths import sessions_directory


def make_session_dir(base: Path, now: datetime) -> Path:
    """Create and return a unique per-run folder under ``base``.

    Named by a launch-timestamp stem (``smacc-YYYYmmdd-HHMMSS``); a numeric suffix
    is appended when a folder for the same second already exists, so two launches
    never collide.
    """
    stem = now.strftime("smacc-%Y%m%d-%H%M%S")
    session_dir = base / stem
    counter = 2
    while session_dir.exists():
        session_dir = base / f"{stem}-{counter}"
        counter += 1
    session_dir.mkdir(parents=True)
    return session_dir


class SmaccSession:
    """Shared session context: run folder, optional metadata, logger, LSL outlet."""

    def __init__(self, metadata: dict | None = None) -> None:
        now = datetime.now()
        # Subject/session/notes are optional metadata recorded inside the log and
        # exports (blank by default); they no longer drive filenames.
        self.metadata = {
            "subject": "",
            "session": "",
            "notes": "",
            "created": now.isoformat(timespec="seconds"),
        }
        if metadata:
            self.metadata.update(metadata)
        self.session_dir = make_session_dir(sessions_directory, now)
        self.stem = self.session_dir.name
        self.log_path = self.session_dir / f"{self.stem}.log"
        self.pport_address = PPORT_ADDRESS
        # The live event-marker registry (codes + routing flags), keyed by event
        # key. Defaults here; a loaded study overrides them via set_event_codes().
        self.events = {e.key: e for e in events.default_events()}
        self.event_code_safe_max = events.DEFAULT_SAFE_MAX
        # Soft interaction logs (volume/color/device/…) are gated off until the
        # main window finishes startup, so construction and study loads don't
        # spam the log; the window flips this on afterwards.
        self.log_interactions = False
        self.init_logger()
        self.init_lsl_stream()

    def init_logger(self) -> None:
        """Initialize the logger that writes to this run's log file."""
        self.logger = logging.getLogger("smacc")
        self.logger.setLevel(logging.DEBUG)
        # Don't bubble up to the root logger (keeps everything out of the
        # terminal; the file/preview handlers are the only outputs).
        self.logger.propagate = False
        # Per-run folders are unique, so a plain "w" never clobbers another run.
        fh = logging.FileHandler(self.log_path, mode="w", encoding="utf-8")
        fh.setLevel(logging.DEBUG)  # the file always records every level
        formatter = logging.Formatter(
            fmt="%(asctime)s.%(msecs)03d, %(levelname)s, %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        fh.setFormatter(formatter)
        self.logger.addHandler(fh)

    def begin_log(self, settings_state: dict) -> None:
        """Record the initial settings near the top of the log, then log startup.

        Called once the window's panels exist so their state can be gathered. A
        couple of device-enumeration debug lines may precede the block; that's
        fine — the block is located by its sentinels, not its position.
        """
        self._append_settings_block(settings_state, "initial")
        self.log_info_msg("Opened SMACC v" + VERSION)
        # Optional connection-test marker; a no-op unless a study enables it.
        self.emit_event("TriggerInitialization")

    def end_log(self, settings_state: dict) -> None:
        """Append the final settings (post-edits) as the log's tail, at quit."""
        self._append_settings_block(settings_state, "final")

    def _append_settings_block(self, settings_state: dict, which: str) -> None:
        """Write a commented settings block through the file handler's stream."""
        payload = settings.build_payload(settings_state, self.metadata)
        block = bids.format_settings_block(payload, which)
        for handler in self.logger.handlers:
            if isinstance(handler, logging.FileHandler):
                handler.acquire()
                try:
                    handler.flush()
                    if handler.stream is not None:  # always open (delay=False)
                        handler.stream.write(block)
                        handler.flush()
                finally:
                    handler.release()

    def init_lsl_stream(self, stream_id: str = "myuidw43536") -> None:
        """Create the LSL marker stream and its outlet."""
        self.info = StreamInfo("MyMarkerStream", "Markers", 1, 0, "string", stream_id)
        self.outlet = StreamOutlet(self.info)

    def emit_event(
        self, key: str, detail: str | None = None, ordinal: int | None = None
    ) -> None:
        """Route a registry event: push its marker and/or log it per its flags.

        ``detail`` appends a free-text suffix to the log label (e.g. a cue name).
        ``ordinal`` is the 1-based firing count for incrementing events (dream
        reports). A *triggered* event is always logged so the sent marker stays
        traceable; a non-triggered event is logged only when its ``log`` flag is
        on (and never carries a portcode).
        """
        event = self.events.get(key)
        if event is None:
            self.logger.warning(f"Unknown event {key!r}; nothing emitted.")
            return
        code = events.runtime_code(event, ordinal)
        if event.increment and ordinal and event.code + (ordinal - 1) > events.CODE_MAX:
            self.logger.warning(
                f"{event.label}: code band exhausted (>{events.CODE_MAX}); "
                f"reusing {code}."
            )
        label = f"{event.label}: {detail}" if detail else event.label
        if event.trigger:
            self.outlet.push_sample([str(code)])
            self.log_info_msg(f"{label} - portcode {code}")
        elif event.log:
            self.log_info_msg(label)

    def set_event_codes(self, event_codes, safe_max: int | None = None) -> None:
        """Replace the live registry from a loaded/edited list of code overrides."""
        self.events = {e.key: e for e in events.merge_event_codes(event_codes)}
        if safe_max is not None:
            try:
                self.event_code_safe_max = int(safe_max)
            except (TypeError, ValueError):
                self.event_code_safe_max = events.DEFAULT_SAFE_MAX

    def event_codes_as_list(self) -> list[dict]:
        """Return the current registry as the compact list persisted in a study."""
        return events.events_to_list(self.events.values())

    def log_info_msg(self, msg: str) -> None:
        """Log an INFO message (always to file; to the preview if INFO is on)."""
        self.logger.info(msg)

    def log_interaction(self, msg: str) -> None:
        """Log a soft interaction (volume/color/device/…) once the session is live.

        Gated by ``log_interactions`` so the programmatic widget setup that runs
        during construction or a study load doesn't spam the log; the main window
        flips the gate on after startup. These lines never carry a portcode.
        """
        if self.log_interactions:
            self.log_info_msg(msg)

    def show_error_popup(self, short_msg, long_msg=None, parent=None) -> None:
        """Record an error in the log and show a dialog (parented if given)."""
        # Record the error in the log file (and preview if Error is enabled).
        self.logger.error(short_msg if long_msg is None else f"{short_msg} {long_msg}")
        win = QtWidgets.QMessageBox(parent)  # parent so it stacks above its window
        win.setText(short_msg)
        if long_msg is not None:
            win.setInformativeText(long_msg)
        win.setWindowTitle("Error")
        win.exec()
