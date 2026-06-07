"""Configuration constants for SMACC."""

from smacc import __version__

VERSION = __version__

DEVELOPMENT_ID = "999"
DEFAULT_VOLUME = 0.5

SURVEY_URL = None

# Named survey presets shown in the dream-recording panel's survey dropdown.
# Maps a display label to its URL. Extend per study (persisted via study.json).
SURVEY_OPTIONS: dict[str, str] = {}

PPORT_ADDRESS = "0x3FD8"
PPORT_CODES = {
    "TriggerInitialization": 200,
    "Note": 201,
    "LightsOff": 202,
    "LightsOn": 203,
    "DreamReportStarted": 204,
    "DreamReportStopped": 205,
    "NoiseStarted": 206,
    "NoiseStopped": 207,
    "CueStopped": 208,
    "IntercomStarted": 209,
    "IntercomStopped": 210,
}
