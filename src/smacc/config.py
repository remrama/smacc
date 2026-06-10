"""Configuration constants for SMACC."""

from smacc import __version__

VERSION = __version__

DEVELOPMENT_ID = "999"
DEFAULT_VOLUME = 0.5

# Named survey presets shown in the dream-recording panel's survey dropdown.
# Maps a display label to its URL. Extend per study (persisted in settings YAML).
SURVEY_OPTIONS: dict[str, str] = {}

# Quick-reply presets for the intercom text chat (#112). Study-level config edited
# from the Intercom panel and persisted in the .smacc; these seed a study that
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
