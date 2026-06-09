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
      bindings: {bedroom_out: "Speakers …, Windows WASAPI", bedroom_mic: "…"}
      routing:  {cue_out: bedroom_out, noise_out: bedroom_out, report_in: bedroom_mic}

A pre-roles study (no ``devices`` block) is migrated from its per-panel device
keys; see :func:`migrate_legacy`.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# Role kinds (a target may only route to a role of its own kind).
OUTPUT = "output"
INPUT = "input"
VISUAL = "visual"


@dataclass(frozen=True)
class Role:
    """A named physical endpoint a device is bound to (e.g. the bedroom speaker)."""

    key: str
    label: str
    kind: str


# The fixed role set. Two outputs and one mic cover the issue's rig; BlinkStick is
# its own (visual) role. The monitor mic (#37) is a second, optional input so a lab
# can place a dedicated, sensitive mic for verifying cues without disturbing the
# (often cheaper) dream-report mic. Kept small on purpose — more can be added later.
ROLES: tuple[Role, ...] = (
    Role("bedroom_out", "Bedroom output", OUTPUT),
    Role("control_out", "Control-room output", OUTPUT),
    Role("bedroom_mic", "Bedroom mic", INPUT),
    Role("monitor_mic", "Monitor mic", INPUT),
    Role("blinkstick", "BlinkStick", VISUAL),
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
    Target("cue_out", "Audio cue", OUTPUT, "bedroom_out"),
    Target("cue_monitor", "Cue monitor", OUTPUT, "", optional=True),
    Target("noise_out", "Noise", OUTPUT, "bedroom_out"),
    Target("intercom_talk", "Intercom → participant", OUTPUT, "bedroom_out"),
    Target("intercom_listen", "Intercom ← participant", OUTPUT, "", optional=True),
    Target("report_in", "Dream-report mic", INPUT, "bedroom_mic"),
    # The room monitor (#37) defaults to the bedroom mic so the cue meter works out
    # of the box; route it to the dedicated monitor mic for a more sensitive check.
    Target("monitor_in", "Room monitor", INPUT, "bedroom_mic", optional=True),
    Target("visual_out", "Visual (BlinkStick)", VISUAL, "blinkstick"),
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


# Pre-roles studies stored one device per panel; map each onto a role. Outputs all
# seed the bedroom output (cue/noise/intercom usually shared one speaker), so the
# first non-empty one wins; the control-room output starts unbound.
_LEGACY_DEVICE_KEYS: tuple[tuple[str, str], ...] = (
    ("cue_device", "bedroom_out"),
    ("noise_device", "bedroom_out"),
    ("intercom_output_device", "bedroom_out"),
    ("recording_device", "bedroom_mic"),
    ("blink_device", "blinkstick"),
)


def migrate_legacy(settings: dict) -> DeviceConfig:
    """Seed a DeviceConfig from a pre-roles study's per-panel device keys.

    Best-effort: the old keys are per-modality, not per-role, so the first
    non-empty output device becomes the bedroom output, the recorder's mic becomes
    the bedroom mic, and the BlinkStick its own role. Anything can be re-pointed in
    the Devices panel afterward.
    """
    cfg = default_config()
    for legacy_key, role_key in _LEGACY_DEVICE_KEYS:
        device = settings.get(legacy_key)
        if isinstance(device, str) and device and role_key not in cfg.bindings:
            cfg.bindings[role_key] = device
    return cfg


def load(settings: dict) -> DeviceConfig:
    """Build the device config for a loaded settings dict.

    Uses the ``devices`` block when present, else migrates the legacy per-panel
    device keys so an older study keeps its routing on first load.
    """
    if isinstance(settings.get("devices"), dict):
        return from_dict(settings["devices"])
    return migrate_legacy(settings)
