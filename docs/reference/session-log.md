# Session log (`.log`)

Every live run writes one plain-text log to its own timestamped folder
(`smacc-YYYYmmdd-HHMMSS/`) under the study's data directory. It is the session's
record: every event marker, the soft interactions (volume / colour / device changes),
and two embedded snapshots of the full settings the run used. The study *designer*
(which records nothing) writes no log.

## Line format

Each line is three comma-separated fields:

```text
YYYY-MM-DD HH:MM:SS.mmm, LEVEL, message
```

- **timestamp** — local wall-clock, millisecond precision.
- **LEVEL** — a Python logging level: `DEBUG`, `INFO`, `WARNING`, `ERROR`, or
    `CRITICAL`. The file records every level; the live on-screen preview shows only a
    configurable subset.
- **message** — the log text. An **event-marker** line ends in `" - portcode N"`:

```text
2026-06-09 22:14:01.003, INFO, Opened SMACC v0.0.7
2026-06-09 22:14:05.221, INFO, Lights off - portcode 47
2026-06-09 22:18:30.880, INFO, Dream report started - portcode 201
2026-06-09 22:19:02.114, INFO, Cue volume set to 0.40
```

A marker line is `"{label} - portcode {code}"` when the event drives a trigger, or
just `"{label}"` when it does not. The code-to-event map is the study's
[`event_codes`](settings-file.md#event_codes) registry; see the
[default code catalog](../triggers.md#default-event-codes).

## Log levels

The file records **every** level — a level never decides whether something is
written, only whether it shows in the live preview (whose default gate starts at
`INFO`). SMACC assigns levels by one convention:

| Level      | What it carries                                                                                                                                                                              |
| ---------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `DEBUG`    | Housekeeping and high-frequency detail: settings loads/saves, device rescans, live volume edits, raw trigger instants, chat text. In the file for the record; out of the preview by default. |
| `INFO`     | **Event markers** and meaningful operator actions — the session's scientific narrative.                                                                                                      |
| `WARNING`  | Mid-session configuration changes (a port code or trigger transport edited during a run — loud so the code map stays traceable) and recoverable faults (a saved device not connected).       |
| `ERROR`    | Faults that cost something: a hardware trigger write failing, a stream that couldn't open.                                                                                                   |
| `CRITICAL` | Uncaught exceptions — the app is in an unknown state.                                                                                                                                        |

### Stimulus marker timing

Most markers are stamped when SMACC fires them. **Audio cue and noise** markers are
the exception: their timestamp — in the log line *and* the LSL stream — is the
*estimated onset* (the fire time plus the output stream's reported latency), so the
marker lines up with the sound rather than SMACC's buffer (see
[Latency](../latency.md)). The raw software-trigger instant rides alongside on a
`DEBUG` line:

```text
2026-06-09 22:18:30.858, DEBUG, Cue started: Piano cue: software trigger at 22:18:30.858, marker advanced +22.0 ms to estimated onset (output latency)
2026-06-09 22:18:30.880, INFO, Cue started: Piano cue - portcode 60
```

That `DEBUG` line is deliberately **not** a `" - portcode N"` line, so the
[BIDS export](bids-export.md) counts the event once, at its onset.

### Text-chat transcript

Each [text-chat](../usage.md#text-chat) message is written verbatim to a `DEBUG`
line, one per message — in the file for the record, out of the live preview and
the BIDS export by default:

```text
2026-06-09 23:41:12.402, DEBUG, Chat to participant: Are you comfortable?
2026-06-09 23:41:35.118, DEBUG, Chat from participant: yes
```

If a study flips the chat events' triggers on, the marker lines fire alongside —
bare (`Chat to participant - portcode 69`), without the message text, so the
trigger channel and the export stay legible.

## Embedded settings blocks

The log carries the **complete settings the run used**, so a session stays
self-documenting even if the study file later changes. The block is the same payload
as a [`.smacc` file](settings-file.md), but every line is prefixed with `#` and
fenced by sentinels, so log parsers skip it entirely:

```text
# --8<-- smacc/settings initial
# kind: smacc/settings
# schema_version: 1
# smacc_version: 0.0.7
# metadata:
#   subject: '001'
#   ...
# settings:
#   ...
# --8<-- end smacc/settings initial
```

Two snapshots are written: **`initial`** (at startup) and **`final`** (appended at
quit). The `final` block may be absent if a session crashed before quitting. Analyze
can recover a `.smacc` from either block.

!!! note "No separate version"

    The log itself isn't versioned; its embedded blocks carry the
    [settings `schema_version`](settings-file.md#version-history).
