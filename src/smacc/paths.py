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

# The SMACC root directory ($SMACC_DIRECTORY, else ~/SMACC). It holds the per-study
# workspaces under studies/ and the global, machine-level preferences.yaml. A
# study's own cues and session runs live inside its own folder (see smacc.study),
# not directly under this root.
smacc_directory = utils.get_smacc_directory()
studies_directory = smacc_directory / "studies"
studies_directory.mkdir(exist_ok=True)

# Operator/machine preferences (window/theme/log-preview), auto-managed by the app.
# These stay global to the machine, separate from a portable per-study config.
preferences_path = smacc_directory / "preferences.yaml"
