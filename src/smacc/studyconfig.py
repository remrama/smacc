"""StudyConfig: the in-memory model of a study's configuration (a ``.smacc``).

Pure and Qt-free — no widgets, no I/O, no YAML. A domain-grouped dataclass tree
that is the single source of truth for a study's settings, with a flat-wire
projection that round-trips the ``.smacc`` *settings* mapping.

The tree groups settings by domain (cueing, markers, surveys, interface) for
authoring, but :meth:`StudyConfig.to_settings_dict` /
:meth:`StudyConfig.from_settings_dict` speak the historical *flat* layout that
:mod:`smacc.settings` reads and writes, emitting keys in the exact order
``SmaccWindow.gather_settings`` produces them. The four existing pure models
(:class:`smacc.devices.DeviceConfig`, :class:`smacc.triggers.TriggerConfig`,
:class:`smacc.hue.HueConfig`, and the :mod:`smacc.events` registry) are reused as
sub-models, never reinvented, and each block is serialized through its owning
module's emitter.

Two fields use a ``None`` sentinel to mean *unspecified*: ``biocals.rows`` and the
two chat-preset lists. A study that omits them keeps the panels' seeded defaults
on load (matching today's ``apply_state``), so the model preserves the absence
rather than inventing a value; a real list (even empty) is honored verbatim.

Metadata (subject/session/notes) is deliberately *not* part of a StudyConfig: it
rides at the settings *envelope* level (see :func:`smacc.settings.build_payload`),
so one configuration re-runs under a new subject.

Paths stay plain ``str`` at every layer: :mod:`smacc.settings` relativizes and
resolves the three path-bearing slots (``cues[*].file``, ``noise_file``,
``data_directory``) on the flat dict, before/after this model ever sees it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from . import biocals, devices, events, triggers

# ---------------------------------------------------------------------------
# Lenient coercion helpers (mirror each panel's apply_state tolerance)
# ---------------------------------------------------------------------------


def _coerce_float(value: object, default: float) -> float:
    """Best-effort float; ``default`` on a bool or anything unparseable."""
    if isinstance(value, bool):  # bool is an int subclass; never a real scalar here
        return default
    try:
        return float(value)  # type: ignore[arg-type]  # guarded by except
    except (TypeError, ValueError):
        return default


def _coerce_int(value: object, default: int) -> int:
    """Best-effort int; ``default`` on a bool or anything unparseable."""
    if isinstance(value, bool):
        return default
    try:
        return int(value)  # type: ignore[call-overload]  # guarded by except
    except (TypeError, ValueError):
        return default


def _as_list(value: object) -> list:
    """Return ``value`` if it is a list, else an empty list."""
    return value if isinstance(value, list) else []


def _presets_from(settings: dict, key: str) -> list[str] | None:
    """Read a chat-preset list: present -> list of str, absent -> ``None`` sentinel."""
    if key not in settings:
        return None
    value = settings[key]
    if not isinstance(value, list):
        return []  # present but malformed reads as a deliberate clear
    return [str(item) for item in value]


# ---------------------------------------------------------------------------
# Cueing leaves
# ---------------------------------------------------------------------------


@dataclass
class AudioCue:
    """One audio-cue slot (an entry of the flat ``cues`` list)."""

    name: str = ""
    file: str = ""  # path-bearing; relativized by smacc.settings, kept as str
    volume: float = 0.2
    loop: bool = False


@dataclass
class VisualCue:
    """One visual-cue slot (an entry of the flat ``visual_cues`` list)."""

    name: str = ""
    color: str = "#ff0000"
    brightness: float = 1.0
    pattern: str = "steady"
    rate: float = 1.0
    length: float = 1.0
    loop: bool = False


def cue_to_dict(cue: AudioCue) -> dict[str, Any]:
    """Serialize one audio cue to its ``cues`` wire dict (shared with the panel)."""
    return {
        "name": cue.name,
        "file": cue.file,
        "volume": cue.volume,
        "loop": cue.loop,
    }


def cue_from_dict(data: dict) -> AudioCue:
    """Build an :class:`AudioCue` from a ``cues`` wire dict (lenient)."""
    return AudioCue(
        name=str(data.get("name", "")),
        file=str(data.get("file", "")),
        volume=_coerce_float(data.get("volume"), 0.2),
        loop=bool(data.get("loop", False)),
    )


def visual_cue_to_dict(cue: VisualCue) -> dict[str, Any]:
    """Serialize one visual cue to its ``visual_cues`` wire dict (shared with panel)."""
    return {
        "name": cue.name,
        "color": cue.color,
        "brightness": cue.brightness,
        "pattern": cue.pattern,
        "rate": cue.rate,
        "length": cue.length,
        "loop": cue.loop,
    }


def visual_cue_from_dict(data: dict) -> VisualCue:
    """Build a :class:`VisualCue` from a ``visual_cues`` wire dict (lenient)."""
    return VisualCue(
        name=str(data.get("name", "")),
        color=str(data.get("color", "#ff0000")),
        brightness=_coerce_float(data.get("brightness"), 1.0),
        pattern=str(data.get("pattern", "steady")),
        rate=_coerce_float(data.get("rate"), 1.0),
        length=_coerce_float(data.get("length"), 1.0),
        loop=bool(data.get("loop", False)),
    )


# ---------------------------------------------------------------------------
# Cueing sections
# ---------------------------------------------------------------------------


@dataclass
class AudioConfig:
    cues: list[AudioCue] = field(default_factory=list)
    attack: float = 0.0  # wire: cue_attack
    release: float = 0.0  # wire: cue_release


@dataclass
class VisualConfig:
    cues: list[VisualCue] = field(default_factory=list)
    attack: float = 0.0  # wire: visual_attack
    release: float = 0.0  # wire: visual_release


@dataclass
class NoiseConfig:
    volume: float = 0.2  # wire: noise_volume
    color: str = "white"  # wire: noise_color
    source: str = "builtin"  # wire: noise_source ("builtin" | "file")
    file: str = ""  # wire: noise_file (path-bearing, str)


@dataclass
class BiocalsConfig:
    voice_volume: float = 0.5
    # None == "unspecified": emit only voice_volume (matching a trimmed file) and,
    # on apply, keep the panel's default stack. A real (possibly empty) list is
    # honored verbatim through biocals.rows_to_list / rows_from_list.
    rows: list[biocals.BiocalRow] | None = None


@dataclass
class CueingConfig:
    audio: AudioConfig = field(default_factory=AudioConfig)
    visual: VisualConfig = field(default_factory=VisualConfig)
    noise: NoiseConfig = field(default_factory=NoiseConfig)
    biocals: BiocalsConfig = field(default_factory=BiocalsConfig)


# ---------------------------------------------------------------------------
# Markers domain (registry + hardware trigger)
# ---------------------------------------------------------------------------


@dataclass
class MarkersConfig:
    # The registry is held as typed EventDefs; events_to_list / merge_event_codes
    # convert both directions, giving a future validator typed access to the
    # safety-critical port-code block.
    event_codes: list[events.EventDef] = field(default_factory=events.default_events)
    event_code_safe_max: int = events.DEFAULT_SAFE_MAX
    # Trigger machine fields (port/baud/address) vs behavior fields are already
    # separable inside TriggerConfig, pre-staging the study/rig carve (#300).
    trigger: triggers.TriggerConfig = field(default_factory=triggers.TriggerConfig)


# ---------------------------------------------------------------------------
# Surveys domain
# ---------------------------------------------------------------------------


@dataclass
class SurveysConfig:
    url: str = ""  # wire: survey_url
    options: dict[str, str] = field(default_factory=dict)  # wire: survey_options


# ---------------------------------------------------------------------------
# Interface domain (UI choices that travel with the study)
# ---------------------------------------------------------------------------


@dataclass
class InterfaceConfig:
    # None == "unspecified": keep the panels' seeded presets on apply, omit on emit.
    chat_experimenter_presets: list[str] | None = None
    chat_participant_presets: list[str] | None = None
    chat_font_size: int = 18  # FONT_DEFAULT; clamped to [8, 72]
    chat_red_text: bool = False
    volume_cap: float = 1.0
    output_latency: str = "high"  # "high" | "low"
    preview_levels: list[str] = field(
        default_factory=lambda: ["INFO", "WARNING", "ERROR", "CRITICAL"]
    )
    always_on_top: bool = False
    tool_always_on_top: dict[str, bool] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Root
# ---------------------------------------------------------------------------


@dataclass
class StudyConfig:
    """The whole configuration of one study (the contents of a ``.smacc``)."""

    cueing: CueingConfig = field(default_factory=CueingConfig)
    markers: MarkersConfig = field(default_factory=MarkersConfig)
    surveys: SurveysConfig = field(default_factory=SurveysConfig)
    interface: InterfaceConfig = field(default_factory=InterfaceConfig)
    # The reused device model. Only its routing is portable; the equipment->device
    # bindings are machine-local (the rig profile, #300) and dropped on emit. The
    # Hue credential and the trigger's port/baud/address are rig-local too — Hue has
    # no portable half, so it is not a study field at all.
    devices: devices.DeviceConfig = field(default_factory=devices.default_config)
    data_directory: str = "data"  # path-bearing, str

    def to_settings_dict(self) -> dict[str, Any]:
        """Project the tree to the flat ``settings`` mapping, in gather order.

        Keys are emitted by explicit sequential statements in the exact order
        ``SmaccWindow.gather_settings`` produces them (panel registration order,
        then the window-level blocks), so a model-written file matches one the
        live session writes. Every block is delegated to its owning module's
        emitter; nothing is re-rolled here except via the shared cue helpers.
        """
        out: dict[str, Any] = {}

        # --- panels, in registration order (events emits nothing) ---
        biocals_block: dict[str, Any] = {
            "voice_volume": self.cueing.biocals.voice_volume
        }
        if self.cueing.biocals.rows is not None:
            biocals_block["rows"] = biocals.rows_to_list(self.cueing.biocals.rows)
        out["biocals"] = biocals_block

        out["visual_cues"] = [visual_cue_to_dict(c) for c in self.cueing.visual.cues]
        out["visual_attack"] = self.cueing.visual.attack
        out["visual_release"] = self.cueing.visual.release

        out["cues"] = [cue_to_dict(c) for c in self.cueing.audio.cues]
        out["cue_attack"] = self.cueing.audio.attack
        out["cue_release"] = self.cueing.audio.release

        out["noise_volume"] = self.cueing.noise.volume
        out["noise_color"] = self.cueing.noise.color
        out["noise_source"] = self.cueing.noise.source
        out["noise_file"] = self.cueing.noise.file

        out["survey_url"] = self.surveys.url
        out["survey_options"] = dict(self.surveys.options)

        if self.interface.chat_experimenter_presets is not None:
            out["chat_experimenter_presets"] = list(
                self.interface.chat_experimenter_presets
            )
        if self.interface.chat_participant_presets is not None:
            out["chat_participant_presets"] = list(
                self.interface.chat_participant_presets
            )

        out["chat_font_size"] = self.interface.chat_font_size
        out["chat_red_text"] = self.interface.chat_red_text

        # (devices and markers panels emit nothing; their state is window-level)
        out["volume_cap"] = self.interface.volume_cap
        out["output_latency"] = self.interface.output_latency

        # --- window-level blocks, in gather_settings order ---
        # Devices: routing only (bindings are rig-local, #300). Trigger: behavior
        # only (port/baud/address are rig-local). No hue block — the bridge
        # credential is entirely rig-local.
        out["devices"] = self.devices.to_study_dict()
        out["event_codes"] = events.events_to_list(self.markers.event_codes)
        out["event_code_safe_max"] = self.markers.event_code_safe_max
        out["trigger_output"] = self.markers.trigger.to_study_dict()
        out["data_directory"] = self.data_directory
        out["preview_levels"] = list(self.interface.preview_levels)
        out["always_on_top"] = self.interface.always_on_top
        out["tool_always_on_top"] = dict(self.interface.tool_always_on_top)
        return out

    @classmethod
    def from_settings_dict(cls, settings: object) -> StudyConfig:
        """Build a StudyConfig from a flat ``settings`` mapping (lenient inverse).

        Each block is read with ``.get`` and parsed by its module's tolerant
        parser; a missing block falls back to that sub-model's default, and a
        malformed value falls back field-by-field, never raising — mirroring how
        each panel's ``apply_state`` ignores junk today.
        """
        s = settings if isinstance(settings, dict) else {}

        biocals_block = s.get("biocals")
        if not isinstance(biocals_block, dict):
            biocals_block = {}
        cueing = CueingConfig(
            audio=AudioConfig(
                cues=[
                    cue_from_dict(c)
                    for c in _as_list(s.get("cues"))
                    if isinstance(c, dict)
                ],
                attack=_coerce_float(s.get("cue_attack"), 0.0),
                release=_coerce_float(s.get("cue_release"), 0.0),
            ),
            visual=VisualConfig(
                cues=[
                    visual_cue_from_dict(c)
                    for c in _as_list(s.get("visual_cues"))
                    if isinstance(c, dict)
                ],
                attack=_coerce_float(s.get("visual_attack"), 0.0),
                release=_coerce_float(s.get("visual_release"), 0.0),
            ),
            noise=NoiseConfig(
                volume=_coerce_float(s.get("noise_volume"), 0.2),
                color=str(s.get("noise_color") or "white"),
                source=(
                    src
                    if (src := s.get("noise_source")) in ("builtin", "file")
                    else "builtin"
                ),
                file=str(s.get("noise_file") or ""),
            ),
            biocals=BiocalsConfig(
                voice_volume=_coerce_float(biocals_block.get("voice_volume"), 0.5),
                rows=biocals.rows_from_list(biocals_block.get("rows")),
            ),
        )

        markers = MarkersConfig(
            event_codes=events.merge_event_codes(s.get("event_codes")),
            event_code_safe_max=_coerce_int(
                s.get("event_code_safe_max"), events.DEFAULT_SAFE_MAX
            ),
            trigger=triggers.from_dict(s.get("trigger_output")),
        )

        survey_options = s.get("survey_options")
        surveys = SurveysConfig(
            url=str(s.get("survey_url") or ""),
            options=(
                {str(k): str(v) for k, v in survey_options.items()}
                if isinstance(survey_options, dict)
                else {}
            ),
        )

        tool_aot = s.get("tool_always_on_top")
        interface = InterfaceConfig(
            chat_experimenter_presets=_presets_from(s, "chat_experimenter_presets"),
            chat_participant_presets=_presets_from(s, "chat_participant_presets"),
            chat_font_size=max(8, min(72, _coerce_int(s.get("chat_font_size"), 18))),
            chat_red_text=bool(s.get("chat_red_text", False)),
            volume_cap=_coerce_float(s.get("volume_cap"), 1.0),
            output_latency=(
                lat if (lat := s.get("output_latency")) in ("high", "low") else "high"
            ),
            preview_levels=(
                [str(x) for x in s["preview_levels"]]
                if isinstance(s.get("preview_levels"), list)
                else ["INFO", "WARNING", "ERROR", "CRITICAL"]
            ),
            always_on_top=bool(s.get("always_on_top", False)),
            tool_always_on_top=(
                {str(k): bool(v) for k, v in tool_aot.items()}
                if isinstance(tool_aot, dict)
                else {}
            ),
        )

        return cls(
            cueing=cueing,
            markers=markers,
            surveys=surveys,
            interface=interface,
            devices=devices.from_dict(s.get("devices")),
            data_directory=str(s.get("data_directory") or "data"),
        )
