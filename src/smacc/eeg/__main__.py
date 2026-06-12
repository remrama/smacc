"""Run the EEG review tool: ``python -m smacc.eeg [recording]``.

The component's own entry point — its own process and ``QApplication``, never
sharing one with a live session (see the package docstring). The frozen
``SMACC-EEG.exe`` targets the same :func:`main` via ``entry_eeg.py``.

``--version`` exits immediately (code 0) without opening any window, mirroring
the base app: reaching that point proves the bundle unpacks and every import —
including the pyqtgraph tree — resolves. It does *not* prove MNE works: MNE is
imported lazily inside :mod:`smacc.eeg.io`, so a bundle missing half of it
would still print a version. That is what ``--selftest`` is for — it
round-trips a synthetic recording through MNE, the slice filters, and the
annotation sidecar, headless, and is what the release workflow runs against
the frozen ``SMACC-EEG.exe``. The exe is built ``--noconsole`` (no stdout), so
the check is the exit code, not the output.
"""

from __future__ import annotations

import sys

from PyQt6.QtWidgets import QApplication

from ..config import VERSION

# Imported eagerly, on purpose: --version must prove the whole MNE/pyqtgraph
# import tree resolves in the frozen bundle (that is the point of the smoke
# test — a lazy import would make it pass on a bundle that can't open a file).
from .window import EegReviewWindow

# Flags that take a following value, so the recording-path scan skips that value.
_VALUE_FLAGS = ("--rater", "--blind")


def pick_recording_path(args: list[str]) -> str | None:
    """Return the recording to open from CLI args, or ``None``.

    The last non-flag argument wins, mirroring the base app's settings-file
    handling; existence and format errors are left to the window so the user
    sees a dialog, not a vanishing process. A value following ``--rater`` or
    ``--blind`` is skipped, so ``--rater alice night1.edf`` opens the recording,
    not the rater id.
    """
    candidates: list[str] = []
    skip = False
    for arg in args[1:]:
        if skip:  # the value consumed by a preceding value-flag
            skip = False
            continue
        if arg in _VALUE_FLAGS:
            skip = True
            continue
        if arg.startswith("-"):  # any flag, incl. "--rater=alice"
            continue
        candidates.append(arg)
    return candidates[-1] if candidates else None


def _flag_value(args: list[str], flag: str) -> str | None:
    """Return the value of ``flag`` (``--flag v`` or ``--flag=v``), or ``None``."""
    prefix = f"{flag}="
    for index, arg in enumerate(args):
        if arg == flag and index + 1 < len(args):
            return args[index + 1]
        if arg.startswith(prefix):
            return arg.split("=", 1)[1]
    return None


def pick_rater_id(args: list[str]) -> str | None:
    """Return the ``--rater`` value from CLI args, or ``None``.

    Accepts both ``--rater alice`` and ``--rater=alice`` so a coordinator can
    hand out a one-click command (``SMACC-EEG.exe --rater alice night1.edf``).
    Sanitizing/validation is the window's job — an empty or unusable id falls
    back to single-rater there rather than failing the launch.
    """
    return _flag_value(args, "--rater")


def pick_blind_spec(args: list[str]) -> str | None:
    """Return the ``--blind`` value (a preset name or a config path), or ``None``.

    Validation is the window's job: an unknown preset or unreadable config is
    surfaced as a dialog after the window opens, not as a vanishing process.
    """
    return _flag_value(args, "--blind")


def selftest() -> int:
    """Exercise the full non-GUI stack on a synthetic recording; 0 on success.

    The frozen bundle's real smoke test: a broken MNE bundling (a missed
    lazy_loader submodule, a dropped data file) only surfaces when MNE
    actually runs, which ``--version`` never makes it do. Builds a recording
    in memory, saves it as FIF, reopens it through :mod:`smacc.eeg.io`,
    filters a slice, and round-trips an annotation sidecar — every layer the
    viewer sits on, no window needed.
    """
    import tempfile
    from pathlib import Path

    import mne
    import numpy as np

    from . import dsp
    from .annotations import Annotation, read_annotations_tsv, write_annotations_tsv
    from .io import embedded_annotations, open_recording

    info = mne.create_info(["C3", "C4"], sfreq=100.0, ch_types="eeg", verbose="error")
    raw = mne.io.RawArray(np.zeros((2, 1000)), info, verbose="error")
    raw.set_annotations(
        mne.Annotations(onset=[1.0], duration=[0.5], description=["selftest"])
    )
    with tempfile.TemporaryDirectory(prefix="smacc-eeg-selftest-") as tmp:
        fif = Path(tmp) / "selftest_raw.fif"
        raw.save(fif, verbose="error")
        recording = open_recording(fif)
        _times, data = recording.get_slice(2.0, 8.0)
        assert data.shape == (2, 600), data.shape
        filtered = dsp.apply(data, 100.0, dsp.FilterSpec(highpass=0.3, lowpass=35.0))
        assert filtered.shape == data.shape
        found = embedded_annotations(recording)
        assert [a.description for a in found] == ["selftest"], found
        tsv = Path(tmp) / "selftest.annotations.tsv"
        write_annotations_tsv([Annotation(1.0, 0.5, "selftest")], tsv)
        assert read_annotations_tsv(tsv) == [Annotation(1.0, 0.5, "selftest")]
        # Rater-keyed + blind-rater (#181): round-trip a per-rater sidecar and a
        # blind config, and exercise the filter, so the frozen bundle proves them.
        from . import blind
        from .annotations import rater_sidecar_paths

        rater_tsv, _ = rater_sidecar_paths(fif, "selftest")
        write_annotations_tsv([Annotation(1.0, 0.0, "SignalObserved")], rater_tsv)
        assert read_annotations_tsv(rater_tsv) == [
            Annotation(1.0, 0.0, "SignalObserved")
        ]
        blind_path = Path(tmp) / f"selftest{blind.BLIND_SUFFIX}"
        blind.write_blind_config(blind.preset_config(blind.PRESET_CLASSIFY), blind_path)
        config = blind.read_blind_config(blind_path)
        hidden = blind.apply_blind([Annotation(1.0, 0.0, "SignalObserved")], config)
        assert hidden == [Annotation(1.0, 0.0, "?")], hidden
        # Figure export (#180): prove matplotlib's PNG/PDF/SVG backends are bundled
        # — a missed backend only surfaces when one actually writes a file.
        from .export import ExportOptions, render
        from .snapshot import Snapshot, SnapshotTrace

        figure_snapshot = Snapshot(
            times=np.linspace(0.0, 6.0, 600),
            window_seconds=6.0,
            traces=(SnapshotTrace("C3", "eeg", 0, np.zeros(600), 100.0),),
        )
        for fmt in ("png", "pdf", "svg"):
            out = Path(tmp) / f"selftest.{fmt}"
            render(figure_snapshot, ExportOptions(fmt=fmt, dpi=100), out)
            assert out.stat().st_size > 0, fmt
    print("selftest ok")
    return 0


def main() -> None:
    if "--version" in sys.argv:
        print(f"SMACC EEG review v{VERSION}")
        sys.exit(0)
    if "--selftest" in sys.argv:
        sys.exit(selftest())
    app = QApplication(sys.argv)
    app.setApplicationName("SMACC EEG review")
    window = EegReviewWindow(
        pick_recording_path(sys.argv),
        rater_id=pick_rater_id(sys.argv),
        blind_spec=pick_blind_spec(sys.argv),
    )
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
