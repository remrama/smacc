# Settings file (`.smacc`)

A `.smacc` file is a **portable study configuration**: it lets a researcher set
SMACC up once — cue sounds and volumes, noise, the visual cue, surveys, event codes,
device routing, optional hardware triggers — and reload it each session so the setup
stays consistent across nights and researchers. It is plain YAML you can read and
edit. The user-facing extension is `.smacc`, but the `kind` stays `smacc/settings`.

See [Usage › Settings files](../usage.md#settings-files-smacc) for the task-level
guide (creating, editing, sharing). This page is the field reference.

## On-disk shape

```yaml
# SMACC settings — YAML (.smacc). Edit with care.
kind: smacc/settings
schema_version: 2
smacc_version: "0.0.7"
metadata:
  subject: "001"
  session: "1"
  notes: ""
  created: "2026-06-09T22:14:00"
settings:
  # --- Audio cues ------------------------------------------------------------
  cues:
    - {name: "Piano cue", file: "cues/piano.wav", volume: 0.4, loop: false}
  cue_attack: 0.0
  cue_release: 0.0
  # --- Background noise ------------------------------------------------------
  noise_volume: 0.2
  noise_color: white
  noise_source: builtin
  noise_file: ""
  # --- Visual cues (BlinkStick) ------------------------------------------------
  visual_cues:
    - {name: "Light 1", color: "#ff0000", brightness: 1.0, pattern: steady, rate: 1.0, length: 1.0, loop: false}
  visual_attack: 0.0
  visual_release: 0.0
  # --- Survey ----------------------------------------------------------------
  survey_url: ""
  survey_options: {}
  # --- Biocals ---------------------------------------------------------------
  biocals:
    voice_volume: 0.5
    rows:
      - {biocal: eyes_open, sequence: true, voice: true, duration: 30}
  # --- Output safety cap -----------------------------------------------------
  volume_cap: 1.0
  # --- Device roles + routing ------------------------------------------------
  devices:
    bindings: {}
    routing:
      cue_out: bedroom_out
      noise_out: bedroom_out
      report_in: bedroom_mic
      visual_out: blinkstick
  # --- Event-marker registry -------------------------------------------------
  event_codes:
    - {key: REMDetected, code: 41, trigger: true, preview: true, increment: false}
  event_code_safe_max: 255
  # --- Optional hardware trigger output --------------------------------------
  trigger_output:
    enabled: false
    transport: serial
    port: ""
    baud: 115200
    address: "0x378"
    mode: pulsed
    pulse_ms: 10
  # --- Data directory + interface --------------------------------------------
  data_directory: data
  preview_levels: [INFO, WARNING, ERROR, CRITICAL]
  always_on_top: false
  tool_always_on_top: {}
```

## Envelope

| Key | Type | Meaning |
|---|---|---|
| `kind` | string | Always `smacc/settings`; a file with a different `kind` is rejected. |
| `schema_version` | integer | The settings schema version — currently **2**. Older versions are upgraded on load (see [Version history](#version-history)). |
| `smacc_version` | string | The SMACC version that wrote the file (informational). |
| `metadata` | mapping | Optional run metadata: `subject`, `session`, `notes`, and `created` (ISO timestamp). Blank by default; recorded in the log, not baked into filenames. |
| `settings` | mapping | The configuration itself (below). |

## `settings`

Every panel contributes its own keys; a few window-level blocks travel alongside.
Any key may be omitted — each falls back to its default.

### Audio, noise, visual, survey, volume

| Key | Type | Meaning |
|---|---|---|
| `cues` | list | One entry per cue slot: `name` (string), `file` (WAV path), `volume` (0–1), `loop` (bool). |
| `cue_attack` | seconds | Fade-in applied to a starting cue. |
| `cue_release` | seconds | Fade-out applied to a stopping cue. |
| `noise_volume` | 0–1 | Background-noise level. |
| `noise_color` | string | Selected noise colour (as offered in the Noise panel, e.g. `white`). |
| `noise_source` | `builtin` \| `file` | Generated noise, or a WAV file. |
| `noise_file` | path | The noise WAV when `noise_source: file`. |
| `visual_cues` | list | One entry per light slot: `name` (string), `color` (`#rrggbb`), `brightness` (0–1), `pattern` (`steady` \| `pulse` \| `flash`), `rate` (Hz, the pulse/flash speed), `length` (seconds; ignored while `loop`), `loop` (bool). |
| `visual_attack` | seconds | Brightness fade-in applied to a starting visual cue. |
| `visual_release` | seconds | Brightness fade-out applied to a stopping visual cue. |
| `survey_url` | string | The selected survey URL. |
| `survey_options` | mapping | Named survey presets: label → URL. |
| `volume_cap` | 0–1 | Master output safety cap multiplied into every stimulus (`1.0` = no cap). |

### `biocals`

The Biocals window's stack (see [Usage › Biocals](../usage.md#biocals)):
`voice_volume` (0–1, the shared instruction volume) plus one `rows` entry per
stack row, in display order. Rows may repeat a biocal (e.g. eyes-closed twice in
the played sequence). A missing block — or a block without `rows` — loads the
default stack; an empty `rows` list is respected as a deliberately cleared one.

| Field | Type | Meaning |
|---|---|---|
| `biocal` | string | Stable biocal id (e.g. `eyes_open`); unknown ids are dropped. |
| `sequence` | boolean | Include this row when the sequence is played. |
| `voice` | boolean | Speak the pre-recorded instruction when the biocal starts. |
| `duration` | integer | Task-window length in seconds (1–600); the countdown and the completion marker run on it. |

### Window-level

| Key | Type | Meaning |
|---|---|---|
| `data_directory` | path | Where this study's runs are written (relative to the `.smacc`, or absolute). |
| `preview_levels` | list | Log levels shown in the live preview, e.g. `[INFO, WARNING, ERROR, CRITICAL]`. |
| `always_on_top` | boolean | Whether the main session window floats on top. |
| `tool_always_on_top` | mapping | Per-tool always-on-top, keyed by panel key. |

### `event_codes`

The editable event-marker registry: a list of overrides applied over the
[built-in registry](../triggers.md#default-event-codes). A study that omits it uses
the built-ins; one that overrides a few codes keeps the rest.

| Field | Type | Meaning |
|---|---|---|
| `key` | string | Stable event id (e.g. `REMDetected`). |
| `code` | integer | Port code, 1–255. |
| `trigger` | boolean | Whether the event pushes a marker. |
| `preview` | boolean | Whether it shows in the live preview (the file always records it). |
| `increment` | boolean | Whether successive firings advance the code (e.g. dream reports). |

A built-in entry persists only those fields. A **custom** event also carries
`label`, `category`, `tooltip`, and `builtin: false` so it can be reconstructed on
load. `event_code_safe_max` (integer, default 255) sets the soft upper-bound warning.

### `devices`

Role → device bindings plus target → role routing (see [Audio & routing](../audio.md)
and [Devices](../devices.md)).

| Key | Type | Meaning |
|---|---|---|
| `bindings` | mapping | Role key → device name. Roles: `bedroom_out`, `control_out`, `bedroom_mic`, `monitor_mic`, `blinkstick`. |
| `routing` | mapping | Target key → role key (`""` = off). Targets: `cue_out`, `cue_monitor`, `noise_out`, `intercom_talk`, `intercom_listen`, `report_in`, `monitor_in`, `visual_out`. |

A missing `devices` block loads the defaults (each target on its default role, with
no devices bound).

### `trigger_output`

Optional hardware TTL trigger output, mirrored alongside the always-on LSL stream
(see [Triggers & port codes](../triggers.md)).

| Field | Type | Meaning |
|---|---|---|
| `enabled` | boolean | Whether the hardware path is on (LSL is always on regardless). |
| `transport` | `serial` \| `parallel` | USB trigger box, or parallel (LPT) port. |
| `port` | string | Serial COM port, e.g. `COM3`. |
| `baud` | integer | Serial baud rate (default 115200). |
| `address` | string | Parallel-port base address as hex, e.g. `0x378`. |
| `mode` | `pulsed` \| `hold` | Pulse the code then drop, or set-and-hold until the next event. |
| `pulse_ms` | integer | Pulse width in ms when `mode: pulsed` (default 10). |

## Paths and portability

Cue/noise WAVs and `data_directory` are stored **relative** to the `.smacc` when they
sit beside it (POSIX separators) and **absolute** otherwise, so a self-contained study
folder stays valid when moved, copied, or zipped.

## Version history

| Version | Changes |
|---|---|
| 1 | First stable schema. Envelope (`kind` / `schema_version` / `smacc_version` / `metadata` / `settings`); panel state; the `biocals`, `devices`, `event_codes` + `event_code_safe_max`, `trigger_output`, `data_directory`, `preview_levels`, `always_on_top`, and `tool_always_on_top` blocks. |
| 2 | The single visual cue (`blink_color` / `blink_length`) became the multi-slot `visual_cues` list with the shared `visual_attack` / `visual_release` fades. A v1 file's blink keys load into the first slot. |
