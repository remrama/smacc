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

from pylsl import StreamInfo, StreamOutlet, local_clock
from PyQt6 import QtWidgets

from . import bids, devices, events, hue, settings, triggers
from .config import VERSION


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
        # Optional hardware TTL trigger output alongside LSL (#28). ``trigger_config``
        # is the configured intent (persisted with the study, edited in the Trigger
        # output dialog); ``trigger_out`` is the live transport opened from it, or
        # None when disabled, unconfigured, or in design mode. Each marker fires on
        # both LSL and this transport from the single emit_event path.
        self.trigger_config = triggers.TriggerConfig()
        self.trigger_out: triggers.TriggerOutput | None = None
        # Philips Hue bridge config (#53): rig state like the device bindings,
        # persisted in the study's ``hue`` block and edited in the Devices window.
        # Stateless REST — nothing to open; the visual panel resolves from it.
        self.hue_config = hue.HueConfig()
        # The live event-marker registry (codes + routing flags), keyed by event
        # key. Defaults here; a loaded study overrides them via set_event_codes().
        self.events = {e.key: e for e in events.default_events()}
        self.event_code_safe_max = events.DEFAULT_SAFE_MAX
        # Per-event firing counts so an incrementing event advances its code.
        self._event_counts: dict[str, int] = {}
        # Wall-clock of the most recent "Start recording" marker (None until it is
        # pressed); dream reports are timestamped relative to it (#60).
        self.recording_start_time: datetime | None = None
        # Saved devices from a loaded settings file that weren't connected at load
        # time; collected by the panels during apply and surfaced once by the window
        # so the operator knows to plug them in (or pick another) before recording.
        self.missing_devices: list[str] = []
        # Device roles + routing (which physical device each modality uses). The
        # Devices window edits this; modality panels resolve their device from it.
        # A loaded study replaces it via devices.load().
        self.devices = devices.default_config()
        # Master output safety cap (0-1): a single ceiling multiplied into every
        # stimulus (cue + noise) in the audio callback, so a cue at full volume on a
        # calibrated rig can't blast a sleeping participant. 1.0 == no cap. Edited in
        # the Volume window; read live by the audio threads.
        self.volume_cap = 1.0
        # Output stream latency mode for the stimulus streams (cue + noise): "high"
        # (PortAudio's robust default — larger buffer, fewer glitches) or "low"
        # (smaller buffer, less marker-to-sound delay, more underrun risk). Edited in
        # the Volume window, persisted in the study, read when a stimulus stream opens.
        # Stimulus latency is rarely critical for lucidity cueing (see docs/latency).
        self.output_latency = "high"
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
        if self.trigger_out is not None:
            self.trigger_out.close()
            self.trigger_out = None

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
        self, key: str, detail: str | None = None, *, onset_offset: float = 0.0
    ) -> None:
        """Route a registry event: send its code over each routed transport, and log it.

        The event's ``lsl`` and ``ttl`` flags route its code independently to the
        LSL marker stream and the hardware TTL trigger (when one is configured).
        ``detail`` appends a free-text suffix to the log label (e.g. a cue name).
        Every event is written to the log file; the event's ``preview`` flag (with
        the level filter) controls whether it also shows in the live preview. An
        ``increment`` event advances its code on each firing (by the per-key firing
        count), so each occurrence is individually findable in the trigger channel.

        ``onset_offset`` (seconds) shifts the marker forward to the stimulus's
        estimated physical onset. An audio cue is heard about one output buffer
        after SMACC starts the stream, so the cue/noise panels pass that buffer
        latency: the LSL timestamp and the INFO log line are then stamped at the
        onset (so the marker — and the BIDS export derived from the log — tracks the
        sound, not SMACC's buffer), while the raw software-trigger instant is kept on
        a DEBUG line. Most events fire at ``0.0`` (marker == trigger instant); see
        docs/latency for why this matters (and why it usually doesn't, for lucidity).
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
        line = f"{label} - portcode {code}" if event.triggered else label
        # In design mode there is no outlet, so triggers are logged but not sent.
        # LSL and the hardware line are written back-to-back (before any pulse-down
        # sleep) so both edges land as close together as possible. LSL is stamped at
        # the estimated onset (now + onset_offset) so it lines up with the stimulus;
        # the hardware TTL just fires its edge now (LSL is the timed path SMACC owns).
        # Snapshot the outlet: emit_event can fire from a non-GUI thread while the
        # GUI thread closes the session and Nones the attribute.
        outlet = self.outlet
        if event.lsl and outlet is not None:
            if onset_offset > 0.0:
                outlet.push_sample([str(code)], local_clock() + onset_offset)
            else:
                outlet.push_sample([str(code)])
        if event.ttl and self.trigger_out is not None:
            try:
                self.trigger_out.send(code)
            except Exception as exc:
                # A hardware fault must never take down a live night. Drop to
                # LSL-only and say so once, loudly, rather than blocking on (or
                # spamming the log for) every later event.
                self.logger.error(
                    f"Hardware trigger failed (code {code}); disabling it: {exc}"
                )
                try:
                    self.trigger_out.close()
                except Exception:
                    pass
                self.trigger_out = None
        # Every event is written to the log file; the preview flag (+ level filter)
        # gates whether it also appears in the live log viewer.
        if onset_offset > 0.0:
            # Stamp the marker at its onset, and keep the raw trigger instant (and the
            # correction applied) on a DEBUG line for audit. That DEBUG line is
            # deliberately not a "… - portcode N" line, so the BIDS parser counts the
            # event exactly once, at its onset.
            raw = datetime.now()
            self.logger.debug(
                f"{label}: software trigger at {raw:%H:%M:%S.%f}, marker advanced "
                f"+{onset_offset * 1000:.1f} ms to estimated onset (output latency)"
            )
            self._log_marker(
                line,
                when=raw + timedelta(seconds=onset_offset),
                level=logging.INFO,
                preview=event.preview,
            )
        else:
            self.logger.info(line, extra={"smacc_preview": event.preview})

    def _log_marker(
        self, line: str, *, when: datetime, level: int, preview: bool
    ) -> None:
        """Log ``line`` stamped at ``when`` rather than at the call instant.

        Records a stimulus marker at its estimated physical onset so the log — and
        the BIDS events derived from it — line up with the stimulus, not with the
        moment SMACC fired. Routes through the same handlers as a normal log call,
        including the live-preview gate (``smacc_preview``).
        """
        record = self.logger.makeRecord(
            self.logger.name,
            level,
            "(smacc)",
            0,
            line,
            (),
            None,
            extra={"smacc_preview": preview},
        )
        # The formatter reads created (H:M:S) and msecs (.mmm) separately, so set both.
        ct = when.timestamp()
        record.created = ct
        record.msecs = (ct - int(ct)) * 1000
        self.logger.handle(record)

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

    def set_trigger_output(self, config: triggers.TriggerConfig) -> str | None:
        """(Re)open the hardware trigger transport from ``config`` (#28).

        Closes any existing transport first, then opens the new one. Returns an
        error message when an *enabled* transport can't be opened (the window shows
        it to the operator), or None on success or when disabled. Never raises: a
        design session or a disabled config simply ends with no transport.
        """
        if self.trigger_out is not None:
            self.trigger_out.close()
            self.trigger_out = None
        if self.design or not config.enabled:
            return None
        try:
            self.trigger_out = triggers.open_trigger(config)
        except triggers.TriggerError as exc:
            self.logger.warning(f"Hardware trigger unavailable: {exc}")
            return str(exc)
        if self.trigger_out is not None:
            self.log_info_msg(f"Hardware trigger ready: {config.summary()}")
        return None

    def test_trigger(self, config: triggers.TriggerConfig) -> str | None:
        """Send one test pulse through ``config`` and report the outcome.

        Returns None on success or a message on failure, for the dialog's Test
        button. The test code reuses ``TriggerInitialization`` (the startup
        connection-test marker). Any live transport is released for the test (a
        serial/parallel port is exclusive) and then restored from the applied config.
        """
        live = self.trigger_out
        self.trigger_out = None
        if live is not None:
            live.close()
        init = self.events.get("TriggerInitialization")
        test_code = init.code if init is not None else 100
        try:
            out = triggers.open_trigger(config)
            if out is None:
                return "Enable a transport to test."
            try:
                out.send(test_code)
            finally:
                out.close()
            return None
        except triggers.TriggerError as exc:
            return str(exc)
        except Exception as exc:
            return f"Trigger test failed: {exc}"
        finally:
            self._restore_trigger_output()

    def _restore_trigger_output(self) -> None:
        """Best-effort reopen of the applied trigger config (used after a test)."""
        if self.design or not self.trigger_config.enabled:
            return
        try:
            self.trigger_out = triggers.open_trigger(self.trigger_config)
        except triggers.TriggerError:
            self.trigger_out = None

    def log_info_msg(self, msg: str) -> None:
        """Log an INFO message (always to file; to the preview if INFO is on)."""
        self.logger.info(msg)

    def log_debug_msg(self, msg: str) -> None:
        """Log a DEBUG message (always to file; hidden from the preview by default).

        For routine, high-frequency lines that belong in the log file for the
        record but would only clutter the live preview (whose default level gate
        starts at INFO).
        """
        self.logger.debug(msg)

    def note_missing_device(self, label: str, name: str) -> None:
        """Record that a saved ``label`` device ``name`` wasn't found on load.

        Always logged (a warning, not gated by ``log_interactions``) and collected
        in :attr:`missing_devices` so the window can surface them together once the
        whole settings load is done.
        """
        self.missing_devices.append(f"{label}: {name}")
        self.logger.warning(f"Saved {label.lower()} not connected: {name}")

    def log_interaction(self, msg: str, *, debug: bool = False) -> None:
        """Log a soft interaction (volume/color/device/…) once the session is live.

        Gated by ``log_interactions`` so the programmatic widget setup that runs
        during construction or a study load doesn't spam the log; the main window
        flips the gate on after startup. These lines never carry a port code.

        ``debug=True`` logs at DEBUG instead of INFO, for high-frequency lines
        (e.g. live volume edits) that should still hit the file but stay out of
        the live preview, whose default level gate starts at INFO.
        """
        if self.log_interactions:
            if debug:
                self.log_debug_msg(msg)
            else:
                self.log_info_msg(msg)

    def show_info_popup(self, short_msg, long_msg=None, parent=None) -> None:
        """Record an info line and show an information dialog (parented if given)."""
        self.log_info_msg(short_msg if long_msg is None else f"{short_msg} {long_msg}")
        win = QtWidgets.QMessageBox(parent)
        win.setIcon(QtWidgets.QMessageBox.Icon.Information)
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
