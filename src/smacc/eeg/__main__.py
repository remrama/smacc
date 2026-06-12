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


def pick_recording_path(args: list[str]) -> str | None:
    """Return the recording to open from CLI args, or ``None``.

    The last non-flag argument wins, mirroring the base app's settings-file
    handling; existence and format errors are left to the window so the user
    sees a dialog, not a vanishing process.
    """
    candidates = [arg for arg in args[1:] if not arg.startswith("-")]
    return candidates[-1] if candidates else None


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
    window = EegReviewWindow(pick_recording_path(sys.argv))
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
