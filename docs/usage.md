# Usage

SMACC presents a single clickable window for running sleep-related experiments.
This page walks through the main features.

<!-- Add an annotated screenshot of the main window here once available, e.g.:
![SMACC main window](assets/screenshot-main.png) -->

## Audio cues

Place sound files in `~/SMACC/cues` (`.wav`, `.mp3`, `.flac`, `.ogg`, and
`.aiff` are supported) and trigger them from the cue controls. SMACC ships a few
`demo-*` cues so there is always something to test with.

## Dream reports

Use the **Record Dream Report** button to record from the selected input device.
Choose the device from **Audio &rsaquo; Input device &rsaquo; [choose device]**.
Recordings are saved into the current session folder.

Surveys (e.g. a dream-report questionnaire on Qualtrics or REDCap) open in your
browser. Manage your saved surveys with the **Manage…** button next to the survey
dropdown — each has a name and URL and is stored in your settings YAML. Select one
in the dropdown to open it automatically when recording starts, or open any saved
survey on its own from **File &rsaquo; Surveys** (each open is logged as a
`SurveyOpened` event).

## EEG portcodes

SMACC marks experiment events — a cue played, a dream report, observed REM, the
lights toggled — by sending a numeric **portcode** to its marker stream and writing a
matching line to the session log, keeping cue delivery and your neural data in sync.

### Configuring codes

Open **File &rsaquo; Event codes…** to see every event in one table. For each event you
can set:

- **Code** — the 8-bit portcode (1–255) sent when the event triggers.
- **Trigger** — whether the event is sent to the marker stream at all.
- **Log** — whether the event is written to the session log. A *triggered* event is
  always logged (so a sent marker is never untraceable), so this only matters for
  events you don't trigger.
- **Increment** — for **dream reports**, give each report a unique, increasing code
  (201, 202, 203, …) so individual reports are findable in the trigger channel. Turn
  it off to use one fixed code for every report.

**Safe max code** raises a soft warning for codes above it — handy when your trigger
hardware only accepts a limited range (some older systems do). Codes must be unique
among triggered events and within 1–255; the editor blocks anything else.

The editor stays available throughout a session. If you change a code mid-study, the
change is written to the log with a timestamp, so the code-to-event mapping for that
session is always recoverable.

Beyond portcodes, SMACC logs the important interactions too — volume, color, device,
and fade changes — as plain log lines (no portcode), so the session record is complete.

### Where codes live

Your codes are saved in the study `.smacc` file (so they travel with the study) and
written into every session `.log` (both the initial and final settings blocks), so any
session is self-documenting: you can decode its markers later even if the codes changed
mid-study.

## Event log

Every run writes a detailed `.log` to its own timestamped folder under
`~/SMACC/sessions/`, capturing the events and settings for that session.

## Study config (`.smacc`)

A **study** captures your reusable setup — cue files, volumes, noise, BlinkStick
color, survey presets, event codes — in a single portable `.smacc` file (plain YAML you
can read and edit). Save it with **File &rsaquo; Export study (.smacc)…** and reload it with
**File &rsaquo; Load study (.smacc)…**. You can also pull the initial or final setup
back out of a session `.log` with **File &rsaquo; Load study from log…**.

Cue/noise files are *referenced*, never copied. When a referenced sound sits in the
same folder as the `.smacc` file, its path is stored **relative**, so a study folder
(the `.smacc` plus its WAVs) stays valid if you move or share it. Sounds elsewhere
(e.g. the shared `~/SMACC/cues`) are stored as absolute paths.

### Opening a study

On the Windows build you can **double-click a `.smacc` file** to launch SMACC with
that study already loaded — the first launch offers to set up this association, and
you can (re)enable it any time from **File &rsaquo; Associate .smacc files
(Windows)**. From a terminal, `SMACC path/to/study.smacc` does the same.

## Preferences

SMACC remembers operator/machine choices — window size and position, light/dark
theme, always-on-top, and which log levels show in the preview — in
`~/SMACC/preferences.yaml`, restored on the next launch. These are separate from a
portable study; they stay with this machine.
