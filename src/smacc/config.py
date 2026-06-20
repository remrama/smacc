"""Configuration constants for SMACC."""

import ctypes
import sys

from smacc import __version__

VERSION = __version__

# A rolling `dev` build (#251) is stamped with the git commit it was built from:
# the release workflow writes smacc._build on main-push builds only. It is absent
# in a tagged release, a PR build, or a source checkout — then BUILD is None and
# the displayed version is just VERSION. The SHA is deliberately kept out of
# __version__, which must stay a plain PEP 440 string (the exe version-info
# resource and the package metadata both derive from it).
try:
    from smacc._build import BUILD  # type: ignore[import-not-found]
except ImportError:
    BUILD = None


def display_version() -> str:
    """Human-facing version; appends the commit stamp on a rolling dev build.

    ``"0.1.2"`` for a release, ``"0.1.2 (dev build a1b2c3d)"`` for a dev build.
    Use this anywhere a person reads the version (About dialog, ``--version``,
    the crash-log banner); keep the bare :data:`VERSION` for the provenance
    written into data files, so a SMACC file never records a build stamp.
    """
    return f"{VERSION} (dev build {BUILD})" if BUILD else VERSION


DEVELOPMENT_ID = "999"
DEFAULT_VOLUME = 0.5

# Windows taskbar identity. SMACC is one app, but the EEG Annotator runs in its
# own re-exec'd process (it keeps reviewing last night's file while a session
# runs). Giving both processes the same explicit AppUserModelID makes Windows
# group them under a single taskbar button and one pinnable icon, rather than
# treating the Annotator window as a separate app.
APP_USER_MODEL_ID = "Mallett.SMACC"


def set_taskbar_app_id() -> None:
    """Pin SMACC's Windows taskbar identity; a no-op off Windows.

    Call once per process, before creating the QApplication. Best-effort: a
    failure here only affects taskbar grouping, never startup.
    """
    if sys.platform != "win32":
        return
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_USER_MODEL_ID)
    except (AttributeError, OSError):
        pass


# Named survey presets shown in the dream-recording panel's survey dropdown.
# Maps a display label to its URL. Extend per study (persisted in settings YAML).
SURVEY_OPTIONS: dict[str, str] = {}

# Quick-reply presets for the text chat (#112). Study-level config edited
# from the Chat window and persisted in the .smacc; these seed a study that
# hasn't customized them (an explicitly empty list is respected on load). Sent
# verbatim through the normal chat path, so standardized wording stays consistent
# across nights and experimenters.
CHAT_EXPERIMENTER_PRESETS: list[str] = [
    "Please describe everything that was going through your mind before the alarm.",
    "Are you awake?",
    "Going back to sleep now.",
]
# The participant has a keyboard but no mouse; these map to the number keys 1-9 so a
# drowsy participant can reply with one keystroke.
CHAT_PARTICIPANT_PRESETS: list[str] = [
    "Got it",
    "I'm awake",
    "Yes",
    "No",
]
# Participant replies map to the number keys 1-9, so at most nine are usable.
MAX_PARTICIPANT_PRESETS = 9
