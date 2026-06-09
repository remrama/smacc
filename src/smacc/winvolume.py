"""Read-only view of the Windows volume stages (best-effort, via pycaw).

Surfaces the two OS volume controls that multiply with SMACC's own software gain
and are otherwise invisible: the default output endpoint's master volume and
SMACC's own per-app level in the Windows Volume Mixer. Everything is best-effort —
any failure (non-Windows, no audio, a COM error) returns ``None`` so callers can
show "unavailable" instead of crashing.
"""

from __future__ import annotations

import os

try:
    from pycaw.pycaw import AudioUtilities

    _AVAILABLE = True
except Exception:  # pragma: no cover - non-Windows or pycaw missing
    _AVAILABLE = False


def available() -> bool:
    """True if the pycaw backend imported (Windows with pycaw installed)."""
    return _AVAILABLE


def endpoint_volume() -> float | None:
    """The default output device's master volume as a 0-1 scalar (None on failure)."""
    if not _AVAILABLE:
        return None
    try:
        endpoint = AudioUtilities.GetSpeakers().EndpointVolume
        return float(endpoint.GetMasterVolumeLevelScalar())
    except Exception:
        return None


def app_volume() -> float | None:
    """SMACC's own volume in the Windows mixer as a 0-1 scalar (None on failure)."""
    if not _AVAILABLE:
        return None
    try:
        pid = os.getpid()
        for session in AudioUtilities.GetAllSessions():
            if session.Process is not None and session.Process.pid == pid:
                return float(session.SimpleAudioVolume.GetMasterVolume())
        return None
    except Exception:
        return None
