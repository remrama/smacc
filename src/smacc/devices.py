"""Equipment and routing: which physical device each action uses.

A small, pure model (no Qt, no I/O — unit-testable) that decouples *device
selection* from the tool windows. A handful of **equipment** entries name the
physical endpoints of a rig (the bedroom speaker, the control-room speaker,
the bedroom mics, the lights); each is bound to a device once. Every
**action** SMACC performs (play a cue, record a dream report, …) is then
routed to a piece of equipment, so several actions can share one device and
re-pointing it is a single change.

The config persists in a settings file's ``devices`` block::

    devices:
      bindings: {bedroom_speaker: "Speakers (Realtek …)", bedroom_mic_1: "Microphone …"}
      routing:  {play_audio_cue: bedroom_speaker, record_dream_report: bedroom_mic_1}

A settings dict with no ``devices`` block loads the default config (each action on
its default equipment, with no devices bound yet).
"""

from __future__ import annotations

from dataclasses import dataclass, field

# Equipment kinds (an action may only route to equipment of its own kind).
OUTPUT = "output"
INPUT = "input"
VISUAL = "visual"

# The PortAudio host API SMACC enumerates (and pins streams to); bindings store
# the bare device name without this host-API name appended.
WASAPI_HOST_API = "Windows WASAPI"


@dataclass(frozen=True)
class Equipment:
    """A named physical endpoint a device is bound to (e.g. the bedroom speaker).

    Equipment is named by *place*, never by purpose — purpose lives in the
    routing (a mic named "monitor mic" becomes a lie the moment a lab routes
    the dream report to it). ``description`` is the full-sentence tooltip
    shown in the Devices window.
    """

    key: str
    label: str
    kind: str
    description: str = ""


# The fixed equipment set. Two speakers and three mics cover the issue's rig;
# the two light technologies are separate visual entries (#53: a BlinkStick binds one USB
# stick, a Hue binds one bridge light/group — the visual cue routes to whichever
# is in use). Bedroom mic 2 (#37) is optional, e.g. a dedicated, sensitive mic
# for verifying cues without relying on the (often cheaper) dream-report mic;
# the control-room mic (#160) picks up the experimenter's voice for the
# Chat window's Talk. Kept small on purpose — more can be added later.
EQUIPMENT: tuple[Equipment, ...] = (
    Equipment(
        "bedroom_speaker",
        "Bedroom speaker",
        OUTPUT,
        "The speaker in the bedroom: out of the box it plays the cues, the "
        "noise, and your voice to the participant.",
    ),
    Equipment(
        "control_speaker",
        "Control-room speaker",
        OUTPUT,
        "A speaker (or headphones) in the control room, so you can hear the "
        "cues and the participant yourself.",
    ),
    Equipment(
        "bedroom_mic_1",
        "Bedroom mic 1",
        INPUT,
        "The main microphone in the bedroom: out of the box it records dream "
        "reports and feeds the Chat window's Listen direction.",
    ),
    Equipment(
        "bedroom_mic_2",
        "Bedroom mic 2",
        INPUT,
        "An optional second microphone in the bedroom — for example a more "
        "sensitive one for verifying that cues are audible, independent of the "
        "dream-report mic.",
    ),
    Equipment(
        "control_mic",
        "Control-room mic",
        INPUT,
        "The microphone in the control room that picks up your voice for the "
        "Chat window's Talk direction.",
    ),
    Equipment(
        "blinkstick_light",
        "BlinkStick light",
        VISUAL,
        "A BlinkStick USB light — one of the two devices that can play visual cues.",
    ),
    Equipment(
        "philips_hue_light",
        "Philips Hue light",
        VISUAL,
        "A Philips Hue light or group, reached through its bridge — the "
        "room-scale alternative for visual cues.",
    ),
)


@dataclass(frozen=True)
class Action:
    """An action's device need, routed to equipment of the matching ``kind``.

    The label is an action verb naming exactly what SMACC *does* with the
    device, and the verb predicts the equipment kind the route can offer (Play →
    speakers/lights, Record/Monitor → mics). ``description`` is the
    full-sentence tooltip enumerating everything the device will be used for.
    """

    key: str
    label: str
    kind: str
    default_equipment: str  # equipment key used out of the box ("" == off)
    optional: bool = False  # may be routed to "none" (an off-by-default extra route)
    description: str = ""


# Every device an action needs, with its default equipment, ordered as the Devices
# window shows them: the participant-facing Play block, the Talk/Listen pair, then
# the mic routes. The optional ones are the monitoring routes (the cue fan-out
# and the Listen return).
ACTIONS: tuple[Action, ...] = (
    Action(
        "play_audio_cue",
        "Play audio cue",
        OUTPUT,
        "bedroom_speaker",
        description="Plays the audio cues — and the spoken biocal "
        "instructions — to the participant.",
    ),
    Action(
        "listen_audio_cue",
        "Listen to audio cue",
        OUTPUT,
        "",
        optional=True,
        description="Optional: also plays each cue and biocal instruction to "
        "you, at the same time, so you hear what the participant hears.",
    ),
    Action(
        "play_noise",
        "Play noise",
        OUTPUT,
        "bedroom_speaker",
        description="Plays the Noise machine's continuous background noise in "
        "the bedroom.",
    ),
    Action(
        "play_visual_cue",
        "Play visual cue",
        VISUAL,
        "blinkstick_light",
        description="Plays the visual cues — a light turning on, pulsing, or flashing.",
    ),
    Action(
        "speak_to_participant",
        "Speak to participant",
        OUTPUT,
        "bedroom_speaker",
        description="Plays your voice in the bedroom while Talk "
        "is held; your voice is picked up by the Control-room mic. Marked in "
        "the EEG record.",
    ),
    Action(
        "listen_to_participant",
        "Listen to participant",
        OUTPUT,
        "",
        optional=True,
        description="Optional: relays the participant's voice (from Bedroom "
        "mic 1) to you while Listen is on. Not marked.",
    ),
    Action(
        "record_dream_report",
        "Record dream report",
        INPUT,
        "bedroom_mic_1",
        description="Records the participant's spoken dream reports to WAV "
        "files, and drives the input-level meter in the Dream recording "
        "window.",
    ),
    # The room monitor (#37) defaults to bedroom mic 1 so the cue meter works
    # out of the box; route it to bedroom mic 2 for a more sensitive check.
    Action(
        "monitor_bedroom_noise",
        "Monitor bedroom noise",
        INPUT,
        "bedroom_mic_1",
        optional=True,
        description="Shows a live level meter in the Audio cue window — with "
        "the rise over the room's resting level — so you can confirm cues are "
        "actually audible in the bedroom.",
    ),
)

EQUIPMENT_BY_KEY: dict[str, Equipment] = {r.key: r for r in EQUIPMENT}
ACTIONS_BY_KEY: dict[str, Action] = {t.key: t for t in ACTIONS}

# Source equipment for the "listen" path (participant mic -> control room) and
# any other input monitor: the same mic the dream report uses.
LISTEN_SOURCE = "bedroom_mic_1"
# Source equipment for the "talk" path (#160): the mic that picks up the
# experimenter's voice. Equipment (not a routable action) on purpose — routing the
# talk source to a bedroom mic would loop the bedroom's own sound back out its
# speakers at a sleeping participant.
TALK_SOURCE = "control_mic"

# Equipment SMACC binds automatically when left unbound (live sessions only):
# the default equipment of every required audio action, plus the Talk/Listen
# source mics, so a fresh study has a definite device for the paths that
# play/record out of the box. Equipment only optional routes point at (the
# control-room speaker, bedroom mic 2) implies hardware a rig may not have,
# so it is never auto-bound.
AUTOBIND_EQUIPMENT: tuple[str, ...] = tuple(
    dict.fromkeys(
        [
            t.default_equipment
            for t in ACTIONS
            if not t.optional and t.kind in (OUTPUT, INPUT) and t.default_equipment
        ]
        + [LISTEN_SOURCE, TALK_SOURCE]
    )
)


@dataclass
class DeviceConfig:
    """Equipment->device bindings plus action->equipment routing for one settings file."""

    bindings: dict[str, str] = field(default_factory=dict)  # equipment -> device
    routing: dict[str, str] = field(default_factory=dict)  # action -> equipment

    def equipment_for(self, action_key: str) -> str:
        """The equipment an action is routed to (its default when unset; "" == off)."""
        if action_key in self.routing:
            return self.routing[action_key]
        action = ACTIONS_BY_KEY.get(action_key)
        return action.default_equipment if action else ""

    def device_for(self, action_key: str) -> str:
        """The device key an action resolves to ("" when its equipment is unbound/off)."""
        equipment = self.equipment_for(action_key)
        return self.bindings.get(equipment, "") if equipment else ""

    def device_for_equipment(self, equipment_key: str) -> str:
        """The device bound to a piece of equipment ("" when unbound)."""
        return self.bindings.get(equipment_key, "")

    def to_dict(self) -> dict:
        """Serialize to the persisted ``devices`` mapping."""
        return {"bindings": dict(self.bindings), "routing": dict(self.routing)}


def default_config() -> DeviceConfig:
    """A config with each action on its default equipment and no devices bound yet."""
    return DeviceConfig(routing={t.key: t.default_equipment for t in ACTIONS})


def from_dict(data: object) -> DeviceConfig:
    """Parse a persisted ``devices`` mapping (lenient; unknown/invalid keys dropped)."""
    cfg = default_config()
    if not isinstance(data, dict):
        return cfg
    bindings = data.get("bindings")
    if isinstance(bindings, dict):
        for equipment_key, device in bindings.items():
            if equipment_key in EQUIPMENT_BY_KEY and isinstance(device, str):
                cfg.bindings[equipment_key] = device
    routing = data.get("routing")
    if isinstance(routing, dict):
        for action_key, equipment_key in routing.items():
            valid = isinstance(equipment_key, str) and (
                equipment_key == "" or equipment_key in EQUIPMENT_BY_KEY
            )
            if action_key in ACTIONS_BY_KEY and valid:
                cfg.routing[action_key] = equipment_key
    return cfg


def load(settings: dict) -> DeviceConfig:
    """Build the device config from a settings dict's ``devices`` block.

    A missing block yields the default config (each action on its default
    equipment, with no devices bound); :func:`from_dict` tolerates a malformed
    block the same way.
    """
    return from_dict(settings.get("devices"))


def autobind(
    cfg: DeviceConfig, defaults: dict[str, str]
) -> list[tuple[Equipment, str]]:
    """Bind unbound :data:`AUTOBIND_EQUIPMENT` entries to their kind's default.

    ``defaults`` maps an equipment kind (:data:`OUTPUT`/:data:`INPUT`) to the device that
    is currently the Windows default ("" when there is none). There is deliberately
    no "system default" pseudo-selection (#139): the current default is written into
    the binding *by name*, so a later change of the Windows default never re-routes
    a study. Existing bindings — including ones whose device is unplugged — are
    never overwritten. Returns the (equipment, device) pairs filled, for logging.
    """
    filled: list[tuple[Equipment, str]] = []
    for equipment_key in AUTOBIND_EQUIPMENT:
        if cfg.bindings.get(equipment_key):
            continue
        equipment = EQUIPMENT_BY_KEY[equipment_key]
        device = defaults.get(equipment.kind, "")
        if device:
            cfg.bindings[equipment_key] = device
            filled.append((equipment, device))
    return filled
