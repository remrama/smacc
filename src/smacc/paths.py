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
logs_directory = data_directory / "logs"
cues_directory = data_directory / "cues"
dreams_directory = data_directory / "dreams"
logs_directory.mkdir(exist_ok=True)
cues_directory.mkdir(exist_ok=True)
dreams_directory.mkdir(exist_ok=True)
