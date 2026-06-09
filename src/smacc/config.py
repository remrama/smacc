"""Configuration constants for SMACC."""

from smacc import __version__

VERSION = __version__

DEVELOPMENT_ID = "999"
DEFAULT_VOLUME = 0.5

# Named survey presets shown in the dream-recording panel's survey dropdown.
# Maps a display label to its URL. Extend per study (persisted in settings YAML).
SURVEY_OPTIONS: dict[str, str] = {}
