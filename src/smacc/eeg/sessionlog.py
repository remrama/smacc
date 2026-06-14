"""Parse a SMACC session log into timeline entries for the annotator overlay (#125).

The EEG annotator can overlay a past session's ``.log`` on its timeline as a
read-only reference track: every marker, cue, dream report, and survey shown
where it happened, so a reviewer sees what SMACC *did* alongside the EEG. This
module is the pure model behind that overlay — no GUI, no MNE — so it is
directly unit-testable and safe to import in the frozen ``SMACC-EEG.exe``. It
builds on the log parsers in :mod:`smacc.bids` (shared with the Analyzer),
adding the per-entry classification, dream-report numbering, and the wall-clock
placement math the overlay needs.

**Placement.** A log line carries a wall-clock timestamp (the recording PC's
clock); the EEG carries data-seconds from its own start. To draw a log entry on
the EEG timeline it is placed at ``(entry_time - origin) + offset`` seconds,
where ``origin`` is the recording's data-second-0 wall time (from
:func:`smacc.eeg.window.wall_time`, which owns the per-format clock rule) and
``offset`` is the manual/auto clock-skew correction. Both sides are compared as
naive *wall-clock readings* (:func:`wall_clock_naive`): a new offset-aware log
(#215) and an old naive one place identically, and a tz-aware origin never
raises against a naive log.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import numpy as np

from ..bids import parse_log, parse_marker

# Entry kinds. A marker line ("… - portcode N") is one of REPORT/SURVEY/MARKER
# by what it points at; any other parseable log line is OTHER (a soft
# interaction or a system line), carried so the overlay's per-level filter can
# show it.
MARKER = "marker"
REPORT = "report"  # a dream-report start — points at report-NN.wav
SURVEY = "survey"  # a survey opened/submitted — points at a response file
OTHER = "other"

# App-defined marker labels (from smacc.events) whose entries carry a session
# artifact, matched against the label parsed off a "… - portcode N" line. Kept
# as literals so this pure model needn't import the live event registry; the
# labels are app-defined and stable (a study overrides codes/routing, not
# labels — see the portcodes reference).
_REPORT_LABEL = "Dream report started"
_SURVEY_LABELS = ("Survey opened", "Survey submitted")
# The report's file stem as written into the log line by the recording panel
# ("Dream report started: report-02, t+…"); lets an entry resolve report-NN.wav
# directly, robust to a saturated increment band or a dropped entry.
_REPORT_NUMBER_RE = re.compile(r"report-(\d+)")


@dataclass(frozen=True)
class LogEntry:
    """One parseable line of a session log, classified for the overlay.

    ``timestamp`` is the line's wall clock (naive for an old log, offset-aware
    for a new one). ``code``/``label`` are filled for a marker line (the label
    is the message minus its ``" - portcode N"`` suffix), ``None`` otherwise.
    ``kind`` is one of :data:`MARKER`/:data:`REPORT`/:data:`SURVEY`/:data:`OTHER`;
    ``report_number`` is the resolved ``report-NN`` index for a :data:`REPORT`
    entry (explicit from the line, else its 1-based order among reports), and
    ``None`` for every other kind.
    """

    timestamp: datetime
    level: str
    message: str
    code: int | None
    label: str | None
    kind: str
    report_number: int | None


def parse_session_log(log_text: str) -> list[LogEntry]:
    """Classify every parseable line of ``log_text`` into :class:`LogEntry` rows.

    Order is the log's own (chronological). Marker lines are recognized via
    :func:`smacc.bids.parse_marker`; dream reports are numbered in order, taking
    the explicit ``report-NN`` from the line when present and falling back to
    their 1-based position so an old log (no number in the line) still resolves.
    """
    entries: list[LogEntry] = []
    report_index = 0
    for when, level, message in parse_log(log_text):
        marker = parse_marker(message)
        if marker is None:
            entries.append(LogEntry(when, level, message, None, None, OTHER, None))
            continue
        label, code = marker
        kind = _classify(label)
        number: int | None = None
        if kind == REPORT:
            report_index += 1
            match = _REPORT_NUMBER_RE.search(message)
            number = int(match.group(1)) if match else report_index
        entries.append(LogEntry(when, level, message, code, label, kind, number))
    return entries


def read_session_log(path: str | Path) -> list[LogEntry]:
    """Read a ``.log`` file and parse it into :class:`LogEntry` rows.

    Raises:
        OSError: if the file can't be read.
    """
    text = Path(path).read_text(encoding="utf-8")
    return parse_session_log(text)


def _classify(label: str) -> str:
    """Map a marker label to its artifact-bearing kind (or plain :data:`MARKER`)."""
    if label.startswith(_REPORT_LABEL):
        return REPORT
    if any(label.startswith(prefix) for prefix in _SURVEY_LABELS):
        return SURVEY
    return MARKER


def wall_clock_naive(when: datetime) -> datetime:
    """Return ``when`` as a naive wall-clock reading (drop any UTC offset).

    The log's timestamps and the EEG origin are compared as the clock *readings*
    they show, not as absolute instants: a log written ``22:00:00-0500`` reads
    22:00 on the recording-PC clock, and dropping the offset keeps that — never
    converting it into the reviewer's zone. The origin from
    :func:`smacc.eeg.window.wall_time` already applies the per-format rule (a
    true-UTC FIF ``meas_date`` is localized there; an EDF/BrainVision wall-clock
    stamp is left as-is), so stripping here is the matching, format-agnostic step.
    """
    return when.replace(tzinfo=None) if when.tzinfo is not None else when


def seconds_at(entry: LogEntry, origin: datetime, offset: float = 0.0) -> float:
    """Data-seconds where ``entry`` lands: ``(entry - origin) + offset``.

    ``origin`` is the recording's data-second-0 wall time; ``offset`` is the
    clock-skew correction (manual drag/pair or an auto estimate). Both sides are
    reduced to wall-clock readings first, so a naive and an offset-aware log
    place identically and the subtraction never mixes aware with naive.
    """
    delta = wall_clock_naive(entry.timestamp) - wall_clock_naive(origin)
    return delta.total_seconds() + offset


def log_span(entries: list[LogEntry]) -> tuple[datetime, datetime] | None:
    """Return ``(first, last)`` entry timestamps, or ``None`` for an empty log."""
    if not entries:
        return None
    return entries[0].timestamp, entries[-1].timestamp


def report_wav(entry: LogEntry, folder: str | Path) -> Path | None:
    """Return the ``report-NN.wav`` a dream-report entry points at, if it exists.

    Resolved by the session's own naming convention (``report-02.wav`` beside the
    log); ``None`` for a non-report entry, an unnumbered one, or a missing file.
    The audio half of #179 plays exactly this file.
    """
    if entry.kind != REPORT or entry.report_number is None:
        return None
    wav = Path(folder) / f"report-{entry.report_number:02d}.wav"
    return wav if wav.is_file() else None


class LogTimeline:
    """A zero-channel :class:`~smacc.eeg.view.SliceProvider` for standalone mode.

    Lets the trace view show a log on a bare time axis with no EEG loaded (#125):
    the view's channel/overlay split means a log-only display is the same widget
    with a provider that has no channels and no samples — its only real datum is
    the duration the log spans, so the axis and scrollbar size themselves. The
    log marks are drawn by the overlay layer, not fetched through ``get_slice``.
    """

    def __init__(self, entries: list[LogEntry]) -> None:
        self._entries = list(entries)

    @property
    def ch_names(self) -> list[str]:
        return []

    @property
    def ch_types(self) -> list[str]:
        return []

    @property
    def sfreq(self) -> float:
        return 1.0

    @property
    def duration(self) -> float:
        """Seconds from the first to the last log entry (0 for an empty log)."""
        span = log_span(self._entries)
        if span is None:
            return 0.0
        first, last = span
        return (wall_clock_naive(last) - wall_clock_naive(first)).total_seconds()

    @property
    def meas_date(self) -> datetime | None:
        """The first entry's timestamp — data-second 0 for standalone placement."""
        return self._entries[0].timestamp if self._entries else None

    def get_slice(self, start_s: float, stop_s: float) -> tuple[np.ndarray, np.ndarray]:
        """No channels, so every slice is empty (the view draws no curves)."""
        return np.empty(0), np.empty((0, 0))
