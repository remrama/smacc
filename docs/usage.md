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

SMACC can trigger EEG portcodes to mark events in your recording, keeping cue
delivery and your neural data in sync.

## Event log

Every run writes a detailed `.log` to its own timestamped folder under
`~/SMACC/sessions/`, capturing the events and settings for that session.

## Settings (YAML)

Save the current setup with **File &rsaquo; Export settings (YAML)…** and reload
it later with **File &rsaquo; Load settings (YAML)…**. You can also pull the
initial/final settings back out of a `.log` with
**File &rsaquo; Load settings from log…**.
