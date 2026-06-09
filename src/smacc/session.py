"""Per-session shared state: a run folder, logging, and the LSL marker outlet.

The launcher and every modality window hold a reference to one ``SmaccSession``
so they all emit event markers and log lines through a single place. Each run
gets its own folder under the settings file's data directory (named by a
launch-timestamp stem) that holds the log, dream reports, and any exports together.
Subject/session are kept as optional metadata inside the log/exports rather than
baked into filenames.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from pathlib import Path

from pylsl import StreamInfo, StreamOutlet
from PyQt5 import QtWidgets

from . import bids, events, settings
from .config import PPORT_ADDRESS, VERSION


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
    """Shared session context: run folder, optional metadata, logger, LSL outlet.

    A live run records to a per-run folder under its study and emits markers on an
    LSL outlet. ``design=True`` backs the study designer instead: it configures a
    study without recording a run, so it creates no run folder, log, or outlet and
    emits no markers (cue/noise previews still work). Use :meth:`close` to release a
    live session's log handler and outlet so the launcher can open many in one run.
    """

    def __init__(
        self,
        data_dir: str | Path,
        metadata: dict | None = None,
        *,
        design: bool = False,
    ) -> None:
        now = datetime.now()
        # The data directory this session belongs to: where its cue/noise pickers
        # default and (for a live run) the parent under which this run's folder is
        # created. Comes from the loaded settings file (or the default data dir).
        self.data_dir = Path(data_dir)
        self.cues_dir = self.data_dir / "cues"
        self.design = design
        # Recording a dream report needs a run folder; the designer has none.
        self.can_record = not design
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
        self.pport_address = PPORT_ADDRESS
        # The live event-marker registry (codes + routing flags), keyed by event
        # key. Defaults here; a loaded study overrides them via set_event_codes().
        self.events = {e.key: e for e in events.default_events()}
        self.event_code_safe_max = events.DEFAULT_SAFE_MAX
        # Per-event firing counts so an incrementing event advances its code.
        self._event_counts: dict[str, int] = {}
        # Wall-clock of the most recent "Start recording" marker (None until it is
        # pressed); dream reports are timestamped relative to it (#60).
        self.recording_start_time: datetime | None = None
        # Soft interaction logs (volume/color/device/…) are gated off until the
        # main window finishes startup, so construction and study loads don't
        # spam the log; the window flips this on afterwards.
        self.log_interactions = False
        # The file handler this session owns (None in design mode), tracked so
        # close() can detach and close it without disturbing other handlers.
        self._file_handler: logging.FileHandler | None = None
        if design:
            # No run artifacts: a logger that records nothing, no folder, no outlet.
            self.session_dir: Path | None = None
            self.stem: str | None = None
            self.log_path: Path | None = None
            self.outlet: StreamOutlet | None = None
            self.init_design_logger()
        else:
            session_dir = make_session_dir(self.data_dir, now)
            self.session_dir = session_dir
            self.stem = session_dir.name
            log_path = session_dir / f"{session_dir.name}.log"
            self.log_path = log_path
            self.init_logger(log_path)
            self.init_lsl_stream()

    def init_logger(self, log_path: Path) -> None:
        """Initialize the logger that writes to this run's log file."""
        self.logger = logging.getLogger("smacc")
        self.logger.setLevel(logging.DEBUG)
        # Don't bubble up to the root logger (keeps everything out of the
        # terminal; the file/preview handlers are the only outputs).
        self.logger.propagate = False
        # Drop any handlers left by a previous session in this process (the hub can
        # open many sessions per launch); each run starts with a clean logger.
        self._clear_handlers()
        # Per-run folders are unique, so a plain "w" never clobbers another run.
        fh = logging.FileHandler(log_path, mode="w", encoding="utf-8")
        fh.setLevel(logging.DEBUG)  # the file always records every level
        formatter = logging.Formatter(
            fmt="%(asctime)s.%(msecs)03d, %(levelname)s, %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        fh.setFormatter(formatter)
        self.logger.addHandler(fh)
        self._file_handler = fh

    def init_design_logger(self) -> None:
        """Set up a no-output logger for design mode (a study run records nothing)."""
        self.logger = logging.getLogger("smacc")
        self.logger.setLevel(logging.DEBUG)
        self.logger.propagate = False
        self._clear_handlers()
        self.logger.addHandler(logging.NullHandler())

    def _clear_handlers(self) -> None:
        """Remove (and close) any handlers currently on the shared 'smacc' logger."""
        for handler in list(self.logger.handlers):
            self.logger.removeHandler(handler)
            try:
                handler.close()
            except Exception:
                pass

    def close(self) -> None:
        """Release per-session resources: the log file handler and the LSL outlet.

        Lets the launcher run many sessions in one process without leaking open log
        files or marker outlets (the 'smacc' logger is a shared singleton). Safe to
        call on a design session (it owns neither).
        """
        if self._file_handler is not None:
            try:
                self._file_handler.flush()
                self.logger.removeHandler(self._file_handler)
                self._file_handler.close()
            except Exception:
                pass
            self._file_handler = None
        self.outlet = None

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

    def emit_event(self, key: str, detail: str | None = None) -> None:
        """Route a registry event: send its marker (if triggered) and log it.

        ``detail`` appends a free-text suffix to the log label (e.g. a cue name).
        Every event is written to the log file; the event's ``preview`` flag (with
        the level filter) controls whether it also shows in the live preview. An
        ``increment`` event advances its code on each firing (by the per-key firing
        count), so each occurrence is individually findable in the trigger channel.
        """
        event = self.events.get(key)
        if event is None:
            self.logger.warning(f"Unknown event {key!r}; nothing emitted.")
            return
        self._event_counts[key] = self._event_counts.get(key, 0) + 1
        ordinal = self._event_counts[key]
        code = events.runtime_code(event, ordinal)
        if event.increment and event.code + (ordinal - 1) > events.CODE_MAX:
            self.logger.warning(
                f"{event.label}: code band exhausted (>{events.CODE_MAX}); "
                f"reusing {code}."
            )
        label = f"{event.label}: {detail}" if detail else event.label
        line = f"{label} - portcode {code}" if event.trigger else label
        # In design mode there is no outlet, so triggers are logged but not sent.
        if event.trigger and self.outlet is not None:
            self.outlet.push_sample([str(code)])
        # Every event is written to the log file; the preview flag (+ level filter)
        # gates whether it also appears in the live log viewer.
        self.logger.info(line, extra={"smacc_preview": event.preview})

    def mark_recording_start(self) -> None:
        """Stamp the recording-start reference clock and emit its marker (#60).

        The reference is what each dream report's "time since recording start" is
        measured against; pressing again restarts it (matching a restarted EEG
        acquisition). The marker routes through the normal event path, so it lands
        in the trigger channel and the log like any other.
        """
        self.recording_start_time = datetime.now()
        self.emit_event("RecordingStarted")

    def elapsed_since_recording(self) -> timedelta | None:
        """Return the time since the recording-start marker (None if unmarked)."""
        if self.recording_start_time is None:
            return None
        return datetime.now() - self.recording_start_time

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

    def show_info_popup(self, short_msg, long_msg=None, parent=None) -> None:
        """Record an info line and show an information dialog (parented if given)."""
        self.log_info_msg(short_msg if long_msg is None else f"{short_msg} {long_msg}")
        win = QtWidgets.QMessageBox(parent)
        win.setIcon(QtWidgets.QMessageBox.Information)
        win.setText(short_msg)
        if long_msg is not None:
            win.setInformativeText(long_msg)
        win.setWindowTitle("SMACC")
        win.exec()

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
