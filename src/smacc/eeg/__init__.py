"""The EEG review tool: post-hoc trace viewing and annotation (#136).

This subpackage is SMACC's *optional* EEG component. It opens a recorded EEG
file (EDF, BrainVision, FIF), scrolls its traces, applies display-only filters,
and saves named annotations to a TSV sidecar — the source file is never
modified. It is a review tool, not a real-time display: nothing here runs
during a live session, and nothing in the live-session path imports from here.

The component always runs as its own process with its own ``QApplication``.
The base ``SMACC.exe`` does not bundle MNE, so an in-process viewer is
impossible in the packaged app; keeping development behavior identical gives
one code path and isolates the heavy MNE/pyqtgraph process from the
lab-critical session app.

Layout keeps the heavy dependency at the edges: :mod:`~smacc.eeg.annotations`
(the model and sidecar I/O) and :mod:`~smacc.eeg.dsp` (display filtering) are
pure Python over numpy/scipy and import no MNE; :mod:`~smacc.eeg.io` is the
only module that touches MNE, and imports it lazily. This module itself stays
import-light so the base app can probe for the component without paying for it:
:func:`available` and :func:`launch` below are everything the launcher uses.
"""

# NO `from __future__ import annotations` here, on purpose: in a package
# __init__ it would bind the name "annotations" to the __future__ feature and
# shadow the smacc.eeg.annotations submodule for `from smacc.eeg import
# annotations` (the runtime annotations below don't need the future import).
import sys
from importlib.util import find_spec
from pathlib import Path

# The frozen EEG component, installed beside SMACC.exe by the installer's
# optional "EEG Review Tools" component (see tools/smacc.iss).
EXE_NAME = "SMACC-EEG.exe"


def component_exe() -> Path:
    """Where the packaged build expects the frozen EEG exe (beside SMACC.exe)."""
    return Path(sys.executable).resolve().parent / EXE_NAME


def available() -> bool:
    """True when the EEG review tool can be launched from this install.

    Packaged build: the installer component dropped ``SMACC-EEG.exe`` next to
    ``SMACC.exe``. Development: the ``eeg`` extra (mne + pyqtgraph) is in the
    environment. Checked via ``find_spec`` so probing costs no imports —
    the launcher calls this at startup.
    """
    if getattr(sys, "frozen", False):
        return component_exe().is_file()
    return find_spec("mne") is not None and find_spec("pyqtgraph") is not None


def launch(args: list[str] | None = None) -> bool:
    """Start the EEG review tool as its own detached process; True if started.

    Detached on purpose: the viewer outlives the launcher (or a session) and
    never shares a process with them — see the isolation rationale above. The
    development path runs ``python -m smacc.eeg`` with the current
    interpreter, the packaged path runs the installed exe. ``args`` are extra
    command-line arguments (e.g. ``["--log", path]`` for the Analyze handoff),
    appended after the module/exe so both paths receive them identically.
    """
    from PyQt6 import QtCore  # deferred: keep this module import-light

    extra = list(args) if args else []
    if getattr(sys, "frozen", False):
        started, _pid = QtCore.QProcess.startDetached(str(component_exe()), extra)
    else:
        started, _pid = QtCore.QProcess.startDetached(
            sys.executable, ["-m", "smacc.eeg", *extra]
        )
    return started
