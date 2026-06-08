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
Recordings are saved into the current session folder. If a survey URL is
configured (see [Installation](installation.md#dream-report-survey)), the button
can also open that survey in your browser.

## EEG portcodes

SMACC can trigger EEG portcodes to mark events in your recording, keeping cue
delivery and your neural data in sync.

## Event log

Every run writes a detailed `.log` to its own timestamped folder under
`~/SMACC/sessions/`, capturing the events and settings for that session.

## Study config (`.smacc`)

A **study** captures your reusable setup — cue files, volumes, noise, BlinkStick
color, survey presets — in a single portable `.smacc` file (plain YAML you can read
and edit). Save it with **File &rsaquo; Export study (.smacc)…** and reload it with
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
