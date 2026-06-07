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

# LSL event-marker codes, looked up by name in send_event_marker.
COMMON_EVENT_CODES = {
    "REM detected": 41,
    "Tech in room": 42,
    "TLR training start": 43,
    "TLR training end": 44,
    "LRLR detected": 45,
    "Sleep onset": 46,
    "Lights off": 47,
    "Lights on": 48,
    "Clapper": 49,
}

# Event names shown as buttons in the event-logging grid, mapped to tooltips.
COMMON_EVENT_TIPS = {
    # "Lights off"/"Lights on" are intentionally omitted here: they are driven
    # by the dedicated lightswitch toggle (which also flips the dark theme), not
    # by the auto-generated event-marker grid. Their codes remain in
    # COMMON_EVENT_CODES so send_event_marker still resolves them.
    "TLR training start": "Mark the start of Targeted Lucidity Reactivation training",
    "TLR training end": "Mark the end of Targeted Lucidity Reactivation training",
    "Tech in room": "Mark the entry of an experimenter/technician in the participant bedroom",
    "Sleep onset": "Mark observed sleep onset",
    "REM detected": "Mark observed REM",
    "LRLR detected": "Mark an observed left-right-left-right lucid signal",
    "Clapper": "Synchronize a marker with EEG",
    "Note": "Mark a note and enter free text",
}
