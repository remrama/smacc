"""Device roles and routing: which physical device each modality uses.

A small, pure model (no Qt, no I/O — unit-testable) that decouples *device
selection* from the modality windows. A handful of **roles** name the physical
endpoints of a rig (the bedroom speaker, the control-room monitor, the bedroom
mic, the BlinkStick); each role is bound to a device once. Every modality
**target** (cue output, noise output, dream-report mic, …) is then routed to a
role, so several modalities can share one device and re-pointing it is a single
change.

The config persists in a settings file's ``devices`` block::

    devices:
      bindings: {bedroom_out: "Speakers (Realtek …)", bedroom_mic: "Microphone …"}
      routing:  {cue_out: bedroom_out, noise_out: bedroom_out, report_in: bedroom_mic}

A settings dict with no ``devices`` block loads the default config (each target on
its default role, with no devices bound yet).
"""

from __future__ import annotations

from dataclasses import dataclass, field

# Role kinds (a target may only route to a role of its own kind).
OUTPUT = "output"
INPUT = "input"
VISUAL = "visual"

# SMACC enumerates only WASAPI audio devices, so device names used to carry a
# redundant ", Windows WASAPI" suffix (the host-API name PortAudio appends). New
# bindings store the bare name; this constant lets older settings that saved the
# suffixed form still resolve. See :func:`strip_wasapi_suffix`.
WASAPI_HOST_API = "Windows WASAPI"
_WASAPI_SUFFIX = f", {WASAPI_HOST_API}"


def strip_wasapi_suffix(device: str) -> str:
    """Drop a trailing ", Windows WASAPI" from a stored device string.

    Device names are no longer stored with the host-API suffix (SMACC only ever
    lists WASAPI devices, so it added nothing). Older ``.smacc`` files saved the
    suffixed form, though, so every place that matches a stored device string
    normalizes through this first — the bare and suffixed forms then compare equal
    and an existing binding keeps resolving to the same device.
    """
    if device.endswith(_WASAPI_SUFFIX):
        return device[: -len(_WASAPI_SUFFIX)]
    return device


@dataclass(frozen=True)
class Role:
    """A named physical endpoint a device is bound to (e.g. the bedroom speaker)."""

    key: str
    label: str
    kind: str


# The fixed role set. Two outputs and one mic cover the issue's rig; the two light
# technologies are separate visual roles (#53: a BlinkStick binds one USB stick, a
# Hue binds one bridge light/group — the visual cue routes to whichever is in use).
# The monitor mic (#37) is a second, optional input so a lab can place a dedicated,
# sensitive mic for verifying cues without disturbing the (often cheaper)
# dream-report mic. Kept small on purpose — more can be added later.
ROLES: tuple[Role, ...] = (
    Role("bedroom_out", "Bedroom speakers", OUTPUT),
    Role("control_out", "Control-room speakers", OUTPUT),
    Role("bedroom_mic", "Bedroom mic", INPUT),
    Role("monitor_mic", "Monitor mic", INPUT),
    Role("blinkstick", "BlinkStick", VISUAL),
    Role("hue", "Philips Hue", VISUAL),
)


@dataclass(frozen=True)
class Target:
    """A modality's device need, routed to a role of the matching ``kind``."""

    key: str
    label: str
    kind: str
    default_role: str  # role key the target routes to out of the box ("" == off)
    optional: bool = False  # may be routed to "none" (an off-by-default extra route)


# Every device a modality needs, with its default role. The optional outputs are
# the new monitoring routes (the cue fan-out and the intercom return).
TARGETS: tuple[Target, ...] = (
    Target("cue_out", "Present audio cue", OUTPUT, "bedroom_out"),
    Target("cue_monitor", "Monitor audio cue", OUTPUT, "", optional=True),
    Target("noise_out", "Present audio noise", OUTPUT, "bedroom_out"),
    Target("intercom_talk", "Speak through intercom", OUTPUT, "bedroom_out"),
    Target("intercom_listen", "Listen through intercom", OUTPUT, "", optional=True),
    Target("report_in", "Capture dream report", INPUT, "bedroom_mic"),
    # The room monitor (#37) defaults to the bedroom mic so the cue meter works out
    # of the box; route it to the dedicated monitor mic for a more sensitive check.
    Target("monitor_in", "Monitor room with", INPUT, "bedroom_mic", optional=True),
    Target("visual_out", "Present visual cue", VISUAL, "blinkstick"),
)

ROLES_BY_KEY: dict[str, Role] = {r.key: r for r in ROLES}
TARGETS_BY_KEY: dict[str, Target] = {t.key: t for t in TARGETS}

# Source role for the intercom "listen" path (participant mic -> control room) and
# any other input monitor: the same mic the dream report uses.
LISTEN_SOURCE_ROLE = "bedroom_mic"


@dataclass
class DeviceConfig:
    """Role->device bindings plus target->role routing for one settings file."""

    bindings: dict[str, str] = field(default_factory=dict)  # role key -> device key
    routing: dict[str, str] = field(default_factory=dict)  # target key -> role key

    def role_for(self, target_key: str) -> str:
        """The role a target is routed to (its default when unset; "" == off)."""
        if target_key in self.routing:
            return self.routing[target_key]
        target = TARGETS_BY_KEY.get(target_key)
        return target.default_role if target else ""

    def device_for(self, target_key: str) -> str:
        """The device key a target resolves to ("" when its role is unbound/off)."""
        role = self.role_for(target_key)
        return self.bindings.get(role, "") if role else ""

    def device_for_role(self, role_key: str) -> str:
        """The device bound to a role ("" when unbound)."""
        return self.bindings.get(role_key, "")

    def to_dict(self) -> dict:
        """Serialize to the persisted ``devices`` mapping."""
        return {"bindings": dict(self.bindings), "routing": dict(self.routing)}


def default_config() -> DeviceConfig:
    """A config with each target on its default role and no devices bound yet."""
    return DeviceConfig(routing={t.key: t.default_role for t in TARGETS})


def from_dict(data: object) -> DeviceConfig:
    """Parse a persisted ``devices`` mapping (lenient; unknown/invalid keys dropped)."""
    cfg = default_config()
    if not isinstance(data, dict):
        return cfg
    bindings = data.get("bindings")
    if isinstance(bindings, dict):
        for role_key, device in bindings.items():
            if role_key in ROLES_BY_KEY and isinstance(device, str):
                cfg.bindings[role_key] = device
    routing = data.get("routing")
    if isinstance(routing, dict):
        for target_key, role_key in routing.items():
            valid = isinstance(role_key, str) and (
                role_key == "" or role_key in ROLES_BY_KEY
            )
            if target_key in TARGETS_BY_KEY and valid:
                cfg.routing[target_key] = role_key
    return cfg


def load(settings: dict) -> DeviceConfig:
    """Build the device config from a settings dict's ``devices`` block.

    A missing block yields the default config (each target on its default role, with
    no devices bound); :func:`from_dict` tolerates a malformed block the same way.
    """
    return from_dict(settings.get("devices"))
