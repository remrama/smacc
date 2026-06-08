# Installation

To install SMACC, go to the [releases page](https://github.com/remrama/smacc/releases),
click the _Assets_ dropdown for the latest release, and download the _SMACC.exe_
file. Once downloaded, double-clicking this file will run SMACC.

!!! note "System requirements"
    SMACC runs on 64-bit Windows 8.1 or later.

!!! note "Administrator privileges"
    For some features you will need to open SMACC with Administrator privileges
    (right-click the file and select **Run as administrator**).

## Optional setup

### Data directory

By default SMACC stores everything under `~/SMACC`. To use a different location,
set an environment variable called `SMACC_DIRECTORY` to whatever directory you
want (the older `SMACC_DATA_DIRECTORY` is still honored as a fallback). SMACC
will create it and all of the subfolders (if not already present).

SMACC organizes work into **studies**, each its own folder under
`~/SMACC/studies/` holding that study's `study.smacc` config, its `cues/` sounds,
and its `sessions/` runs. Unless you open a specific study (by double-clicking its
`.smacc`), SMACC uses an auto-managed `default` study, so it works out of the box.

Each run gets its own timestamped folder under its study's `sessions/`
(e.g. `smacc-20260607-223015/`) holding that run's `.log`, dream-report
recordings, and any exports. Subject/session are optional metadata (set from
**File &rsaquo; Session info…**) recorded inside the log/exports rather than in
filenames. Window/theme/log-preview choices are machine-level and remembered
globally in `~/SMACC/preferences.yaml`, separate from any study.

### Study files (`.smacc`)

A reusable setup can be saved to a portable `.smacc` study file (see
[Usage](usage.md#study-config-smacc)). On the Windows build, the first launch
offers to associate `.smacc` files so you can **double-click one to open SMACC with
that study loaded**; you can also (re)enable this from
**File &rsaquo; Associate .smacc files (Windows)**.

### Audio cues

SMACC seeds a few `demo-*` cue files into each study's `cues/` folder (restored
if you delete them), so there is always something to test with. You can also
place your own sound files there — `.wav`, `.mp3`, `.flac`, `.ogg`, and `.aiff`
are all supported.

### Dream report survey

The **Record Dream Report** button can optionally pop open a survey URL — for
example a dream-report survey hosted on Qualtrics or REDCap. Add surveys from the
Dream-recording panel's **Manage…** button (each has a name and a URL); they are
saved to your settings YAML and restored next session. Pick one from the survey
dropdown to open it automatically when recording starts, or open any saved survey
on its own from **File &rsaquo; Surveys**.

### Recording device

If you plan to record dreams, choose the input device from the SMACC menubar:
**Audio &rsaquo; Input device &rsaquo; [choose device]**.
