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
set an environment variable called `SMACC_DATA_DIRECTORY` to whatever directory
you want. SMACC will create it and all of the subfolders (if not already present).

Each run gets its own timestamped folder under `~/SMACC/sessions/`
(e.g. `smacc-20260607-223015/`) holding that run's `.log`, dream-report
recordings, and any exports. Subject/session are optional metadata (set from
**File &rsaquo; Session info…**) recorded inside the log/exports rather than in
filenames.

### Audio cues

SMACC seeds a few `demo-*` cue files into `~/SMACC/cues` on first launch
(restored if you delete them), so there is always something to test with. You can
also place your own sound files there — `.wav`, `.mp3`, `.flac`, `.ogg`, and
`.aiff` are all supported.

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
