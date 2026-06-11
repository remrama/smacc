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
# App-level logs, global to this machine (run logs live in per-run folders).
LOGS_DIR = smacc_directory / "logs"
# The persistent crash log: faulthandler dumps, uncaught-exception tracebacks,
# and Qt fatal messages land here even when no run log exists (see smacc.crashlog).
CRASH_LOG_PATH = LOGS_DIR / "crash.log"
# Biocal voice recordings (#78). The standard set is read straight from the
# bundle (so it tracks the app on upgrade, #122); this folder is an optional
# *override* — a lab drops a same-named WAV here to replace one — and is not
# seeded, so it may not exist until a lab adds one.
BIOCALS_DIR = smacc_directory / "biocals"
# User-built survey definitions (#114), written by the in-app builder (or by
# hand, same YAML format); loaded alongside the bundled built-ins. Created lazily
# on the first build.
SURVEYS_DIR = smacc_directory / "surveys"


def resolve_biocal_voice(filename: str) -> Path:
    """The biocal voice WAV to play: a lab override if present, else the bundle.

    A same-named file in :data:`BIOCALS_DIR` wins (a lab's own recording);
    otherwise the bundled copy is used directly, so the standard set needs no
    seeding and stays current across upgrades (#122). The returned path may not
    exist if a (custom) biocal has no recording in either place.
    """
    override = BIOCALS_DIR / filename
    return override if override.is_file() else BUNDLED_BIOCALS_DIR / filename


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
