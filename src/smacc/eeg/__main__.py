"""Run the EEG review tool: ``python -m smacc.eeg [recording]``.

The component's own entry point — its own process and ``QApplication``, never
sharing one with a live session (see the package docstring). The frozen
``SMACC-EEG.exe`` targets the same :func:`main` via ``entry_eeg.py``.

``--version`` exits immediately (code 0) without opening any window, mirroring
the base app: the release workflow smoke-tests the frozen exe with it, and
reaching that point proves the bundle unpacks and every import — including the
MNE/pyqtgraph tree — resolves. The exe is built ``--noconsole`` (no stdout),
so the check is the exit code, not the output.
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


def main() -> None:
    if "--version" in sys.argv:
        print(f"SMACC EEG review v{VERSION}")
        sys.exit(0)
    app = QApplication(sys.argv)
    app.setApplicationName("SMACC EEG review")
    window = EegReviewWindow(pick_recording_path(sys.argv))
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
