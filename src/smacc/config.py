"""Configuration constants for SMACC."""

from smacc import __version__

VERSION = __version__

DEVELOPMENT_ID = "999"
DEFAULT_VOLUME = 0.5

# Named survey presets shown in the dream-recording panel's survey dropdown.
# Maps a display label to its URL. Extend per study (persisted in settings YAML).
SURVEY_OPTIONS: dict[str, str] = {}

# Legacy parallel-port address, kept for the future hardware-trigger path (#28).
# Event-marker codes now live in smacc.events as a configurable registry.
PPORT_ADDRESS = "0x3FD8"
