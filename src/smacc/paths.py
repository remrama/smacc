"""Filesystem paths and bundled-asset locations for SMACC."""

import sys
from pathlib import Path

from smacc import utils

# Application icon, bundled as package data in smacc/assets/. Resolves to the
# package dir in development and to the PyInstaller extraction dir in the frozen
# build (where --add-data places it under smacc/assets/).
if getattr(sys, "frozen", False):
    _asset_dir = Path(getattr(sys, "_MEIPASS", "")) / "smacc" / "assets"
else:
    _asset_dir = Path(__file__).resolve().parent / "assets"
LOGO_PATH = _asset_dir / "icon.png"
# Demo cue files shipped with SMACC (resolved the same way as the icon above);
# copied into the user's cues directory on first launch.
BUNDLED_CUES_DIR = _asset_dir / "cues"

# Define directories.
data_directory = utils.get_data_directory()
cues_directory = data_directory / "cues"
# Each run gets its own folder under sessions/ (named by a launch-timestamp stem),
# holding that run's log, dream reports, and any exports together. SmaccSession
# creates the per-run child; here we only ensure the shared parents exist.
sessions_directory = data_directory / "sessions"
cues_directory.mkdir(exist_ok=True)
sessions_directory.mkdir(exist_ok=True)
