"""Philips Hue bridge client and visual-cue backend (#53).

A Hue bridge is the second visual-cue device next to the BlinkStick: room-scale
light through ordinary bulbs, reached over the local network instead of USB. This
module is the whole integration — a tiny V1 REST client built on stdlib
``urllib`` (every bridge generation speaks V1; no new dependency, no async
machinery), the press-button pairing flow, light/group enumeration for the
Devices window, and the :class:`HueBackend` the visual cue board drives.

The trade-offs a study must know (documented on the docs site): each command is
an HTTP round-trip (~50–150 ms), so a Hue cue's photon onset lags its marker by
tens of milliseconds with jitter, and the bridge rate-limits to roughly 10
commands/s per light (~1/s per group) — fine for steady cues and slow pulses
(``transitiontime`` smooths the steps), far too slow for a square-wave flash, so
the board refuses flash on Hue rather than degrade it silently. Time-locked
protocols should keep the BlinkStick.

Config (bridge IP + the app key minted by pairing) persists in the ``hue`` block
of a study's ``.smacc`` — like device bindings, it is rig state that travels with
the study. The app key is a local-network credential; treat the file accordingly.

Qt-free and unit-testable: HTTP goes through one seam (:func:`_http_json`) that
tests stub.
"""

from __future__ import annotations

import json
import socket
import urllib.request
from dataclasses import dataclass, fields
from typing import Any

# One knob for every bridge call: long enough for a sleepy bridge, short enough
# that a wrong IP fails while the operator is still looking at the dialog.
HTTP_TIMEOUT_S = 2.0
# Philips' cloud discovery endpoint: returns the bridges seen on this LAN.
DISCOVERY_URL = "https://discovery.meethue.com/"


class HueError(Exception):
    """A bridge call failed; carries an actionable, human-readable message."""


@dataclass
class HueConfig:
    """How to reach the bridge: its IP and the app key minted by pairing.

    Persisted as the ``hue`` block of a study file (the ``trigger_output``
    precedent). Empty fields mean "not set up".
    """

    bridge_ip: str = ""
    app_key: str = ""

    @property
    def configured(self) -> bool:
        return bool(self.bridge_ip and self.app_key)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to the plain mapping persisted in a study file."""
        return {f.name: getattr(self, f.name) for f in fields(self)}


def from_dict(data: object) -> HueConfig:
    """Build a :class:`HueConfig` from a persisted mapping (defaults on junk)."""
    cfg = HueConfig()
    if not isinstance(data, dict):
        return cfg
    cfg.bridge_ip = str(data.get("bridge_ip") or "")
    cfg.app_key = str(data.get("app_key") or "")
    return cfg


def load(settings: dict) -> HueConfig:
    """Return the Hue config from a study's settings mapping (default if absent)."""
    return from_dict(settings.get("hue"))


# ----- HTTP (the one seam tests stub) -----------------------------------------


def _http_json(method: str, url: str, payload: dict | None = None) -> Any:
    """One bridge/discovery round-trip: JSON in, parsed JSON out.

    Raises :class:`HueError` with the underlying reason on any transport problem
    (unreachable IP, timeout, bad JSON), so callers only handle one error type.
    """
    body = None if payload is None else json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(url, data=body, method=method)
    request.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT_S) as response:
            return json.loads(response.read().decode("utf-8"))
    except HueError:
        raise
    except Exception as exc:
        raise HueError(f"Could not reach the bridge: {exc}") from exc


def _first_error(reply: Any) -> dict | None:
    """The first ``error`` object in a bridge reply list, if any."""
    if isinstance(reply, list):
        for item in reply:
            if isinstance(item, dict) and isinstance(item.get("error"), dict):
                return item["error"]
    return None


# ----- discovery + pairing ------------------------------------------------------


def discover() -> list[str]:
    """Bridge IPs on this LAN via Philips' discovery endpoint (best effort)."""
    try:
        reply = _http_json("GET", DISCOVERY_URL)
    except HueError:
        return []
    if not isinstance(reply, list):
        return []
    return [
        item["internalipaddress"]
        for item in reply
        if isinstance(item, dict) and item.get("internalipaddress")
    ]


def pair(bridge_ip: str) -> str:
    """Mint an app key on the bridge (the operator presses its link button first).

    Returns the key. Raises :class:`HueError` with press-the-button guidance when
    the button wasn't pressed (bridge error type 101), or with the bridge's own
    message for anything else.
    """
    devicetype = f"smacc#{socket.gethostname()[:19] or 'host'}"
    reply = _http_json("POST", f"http://{bridge_ip}/api", {"devicetype": devicetype})
    error = _first_error(reply)
    if error is not None:
        if error.get("type") == 101:
            raise HueError(
                "Press the round link button on the bridge, then pair again "
                "within 30 seconds."
            )
        raise HueError(str(error.get("description") or "Pairing failed."))
    if isinstance(reply, list):
        for item in reply:
            if isinstance(item, dict) and isinstance(item.get("success"), dict):
                key = item["success"].get("username")
                if key:
                    return str(key)
    raise HueError("Unexpected reply from the bridge while pairing.")


# ----- enumeration ----------------------------------------------------------------


def targets(cfg: HueConfig) -> list[tuple[str, str]]:
    """``(label, key)`` for each light and group on the bridge.

    Keys are stable ``light:<id>`` / ``group:<id>`` strings — what a Devices-window
    binding persists. Raises :class:`HueError` when the bridge can't be read.
    """
    if not cfg.configured:
        return []
    base = f"http://{cfg.bridge_ip}/api/{cfg.app_key}"
    out: list[tuple[str, str]] = []
    for kind, path in (("light", "lights"), ("group", "groups")):
        reply = _http_json("GET", f"{base}/{path}")
        error = _first_error(reply)
        if error is not None:
            raise HueError(str(error.get("description") or f"Could not list {path}."))
        if not isinstance(reply, dict):
            continue
        for ident in sorted(reply, key=lambda i: (len(i), i)):
            item = reply[ident]
            name = item.get("name") if isinstance(item, dict) else None
            label = f"{name or kind.title()} ({kind} {ident})"
            out.append((label, f"{kind}:{ident}"))
    return out


# ----- color ------------------------------------------------------------------------


def rgb_to_xy_bri(rgb: tuple[int, int, int]) -> tuple[float, float, int]:
    """Map an 8-bit RGB to Hue's ``xy`` chromaticity + ``bri`` (Philips' formula).

    Inverse-gamma sRGB to linear, Philips' wide-gamut D65 matrix to XYZ, then
    chromaticity. ``bri`` carries the value component (the engine already shaped
    brightness/envelope into the RGB), clamped to the bridge's 1..254.
    """
    r, g, b = (component / 255.0 for component in rgb)

    def linear(channel: float) -> float:
        if channel > 0.04045:
            return ((channel + 0.055) / 1.055) ** 2.4
        return channel / 12.92

    lr, lg, lb = linear(r), linear(g), linear(b)
    x_comp = lr * 0.664511 + lg * 0.154324 + lb * 0.162028
    y_comp = lr * 0.283881 + lg * 0.668433 + lb * 0.047685
    z_comp = lr * 0.000088 + lg * 0.072310 + lb * 0.986039
    total = x_comp + y_comp + z_comp
    if total <= 0.0:
        x, y = 0.3127, 0.3290  # D65 white point; bri 0 means the caller turns off
    else:
        x, y = x_comp / total, y_comp / total
    bri = max(1, min(254, round(max(r, g, b) * 254)))
    return (round(x, 4), round(y, 4), bri)


# ----- the visual-cue backend ---------------------------------------------------------


class HueBackend:
    """Drives one Hue light or group as a visual-cue target.

    Satisfies the :class:`smacc.lights.LightBackend` protocol. Each ``apply`` is
    one HTTP PUT with a 100 ms ``transitiontime``, which smooths the steps a slow
    pulse arrives in; a black frame turns the light off. ``supports_flash`` is
    False — the bridge's rate limits can't honor a square wave, and the board
    refuses rather than degrade the stimulus silently.
    """

    supports_flash = False

    def __init__(self, cfg: HueConfig, target_key: str) -> None:
        kind, _, ident = target_key.partition(":")
        base = f"http://{cfg.bridge_ip}/api/{cfg.app_key}"
        if kind == "group":
            self._url = f"{base}/groups/{ident}/action"
        else:
            self._url = f"{base}/lights/{ident}/state"

    def _put(self, state: dict) -> None:
        reply = _http_json("PUT", self._url, state)
        error = _first_error(reply)
        if error is not None:
            raise HueError(str(error.get("description") or "The bridge refused."))

    def apply(self, rgb: tuple[int, int, int]) -> None:
        if rgb == (0, 0, 0):
            self._put({"on": False, "transitiontime": 1})
            return
        x, y, bri = rgb_to_xy_bri(rgb)
        self._put({"on": True, "bri": bri, "xy": [x, y], "transitiontime": 1})

    def off(self) -> None:
        self._put({"on": False, "transitiontime": 0})


def resolve_backend(cfg: HueConfig, target_key: str) -> HueBackend | None:
    """Wrap the bound light/group (None when the bridge or binding isn't set).

    Construction is offline on purpose — resolution runs on every Devices-window
    change, so a probe here would block the GUI; an unreachable bridge surfaces
    at the first write instead.
    """
    if not cfg.configured or not target_key:
        return None
    return HueBackend(cfg, target_key)
