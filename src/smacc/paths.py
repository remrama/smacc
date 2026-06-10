"""Filesystem paths and bundled-asset locations for SMACC."""

import os
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
# copied into the default data directory's cues on first launch.
BUNDLED_CUES_DIR = _asset_dir / "cues"
# Pre-rendered biocal voice instructions shipped with SMACC (#78); copied into
# the SMACC root's biocals folder on first launch.
BUNDLED_BIOCALS_DIR = _asset_dir / "biocals"
# Shipped example/default settings, copied to the SMACC root on first run so the
# defaults live in a readable .smacc file (not in Python) — see smacc.settings.
BUNDLED_DEFAULT_SETTINGS = _asset_dir / "default.smacc"
# Built-in survey definitions shipped with SMACC (#114); loaded straight from the
# bundle (never copied out), so updates reach every install.
BUNDLED_SURVEYS_DIR = _asset_dir / "surveys"

# The SMACC root directory ($SMACC_DIRECTORY, else ~/SMACC). It holds the global
# interface preferences, the seeded default.smacc, and the default data directory.
# A settings (.smacc) file may point its own data directory anywhere.
smacc_directory = utils.get_smacc_directory()
# Interface/machine preferences (theme, window, log-preview), global to this machine.
preferences_path = smacc_directory / "preferences.yaml"
# The default settings file, seeded on first run and opened when no other is chosen.
DEFAULT_SETTINGS_PATH = smacc_directory / "default.smacc"
# Where runs go when a settings file doesn't name its own data directory.
DEFAULT_DATA_DIR = smacc_directory / "data"
# Biocal voice recordings, seeded from the bundled set on first run (#78). A lab
# can replace any file with its own recording (same name) — seeding never
# overwrites — and their presence is verified at each session start.
BIOCALS_DIR = smacc_directory / "biocals"
# User-built survey definitions (#114), written by the in-app builder (or by
# hand, same YAML format); loaded alongside the bundled built-ins. Created lazily
# on the first build.
SURVEYS_DIR = smacc_directory / "surveys"


def is_default_settings(path: str | Path) -> bool:
    """True if ``path`` is the seeded ``default.smacc`` (case/realpath-insensitive).

    The editor uses this to keep SMACC's known-good default template from being
    overwritten — saving the default redirects to Save-As instead. Compares resolved,
    case-normalized paths so it holds regardless of how the path was spelled and even
    if the file doesn't exist yet (a Save-As target the user typed by hand).
    """

    def _norm(p: str | Path) -> str:
        try:
            resolved = Path(p).expanduser().resolve()
        except OSError:
            resolved = Path(p).expanduser()
        return os.path.normcase(str(resolved))

    return _norm(path) == _norm(DEFAULT_SETTINGS_PATH)
