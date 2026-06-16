"""The EEG Annotator: post-hoc trace viewing and annotation (#136).

This subpackage is SMACC's EEG Annotator. It opens a recorded EEG file (EDF,
BrainVision, FIF), scrolls its traces, applies display-only filters, and saves
named annotations to a TSV sidecar — the source file is never modified. It is
an annotation tool, not a real-time display: nothing here runs during a live
session, and nothing in the live-session path imports from here.

The Annotator always runs as its own process with its own ``QApplication`` —
so it can outlive the launcher and keep showing last night's recording while
tonight's session runs, and so its heavy MNE/pyqtgraph work can never crash the
lab-critical session app. It is *not* a separate program: it is a mode of the
single SMACC binary, re-exec'd with ``--eeg`` (see :func:`launch`).

Layout keeps the heavy dependency at the edges: :mod:`~smacc.eeg.annotations`
(the model and sidecar I/O) and :mod:`~smacc.eeg.dsp` (display filtering) are
pure Python over numpy/scipy and import no MNE; :mod:`~smacc.eeg.io` is the
only module that touches MNE, and imports it lazily. This module itself stays
import-light so the launcher can pull it in without paying for MNE until the
Annotator is actually opened.
"""

# NO `from __future__ import annotations` here, on purpose: in a package
# __init__ it would bind the name "annotations" to the __future__ feature and
# shadow the smacc.eeg.annotations submodule for `from smacc.eeg import
# annotations` (the runtime annotations below don't need the future import).
import sys


def launch(args: list[str] | None = None) -> bool:
    """Re-exec SMACC into the EEG Annotator as its own detached process.

    Detached on purpose: the Annotator outlives the launcher (or a session) and
    never shares a process with them — see the isolation rationale above. Both
    the packaged exe and a dev checkout re-exec *this same binary* with
    ``--eeg`` (the frozen build bundles MNE, so there is no separate exe);
    ``smacc.__main__`` routes ``--eeg`` to the Annotator's entry point. ``args``
    are extra command-line arguments (e.g. ``["--log", path]`` for the Analyzer
    handoff), forwarded after ``--eeg`` so both paths receive them identically.
    """
    from PyQt6 import QtCore  # deferred: keep this module import-light

    extra = list(args) if args else []
    if getattr(sys, "frozen", False):
        argv = ["--eeg", *extra]
    else:
        argv = ["-m", "smacc", "--eeg", *extra]
    started, _pid = QtCore.QProcess.startDetached(sys.executable, argv)
    return started
