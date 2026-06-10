# Installation

[Download SMACC](https://github.com/remrama/smacc/releases/latest/download/SMACC.exe){ .md-button .md-button--primary }

The button above always downloads the **latest** version. To get an older or
specific version, browse the
[releases page](https://github.com/remrama/smacc/releases): pick the release you
want, open its _Assets_ dropdown, and download SMACC from there. Every version is
the same kind of single portable file: once downloaded, double-click it to run.
There is no installer. (The version switcher on this documentation site switches
the *docs* only — older copies of SMACC itself come from the releases page.)

!!! note "System requirements"
    SMACC runs on 64-bit Windows 10 or later.

!!! warning "Windows SmartScreen — “Windows protected your PC”"
    SMACC isn't code-signed, so the first time you run it Windows SmartScreen may show
    a blue **“Windows protected your PC”** box. This is expected for any new,
    unsigned program. To run SMACC anyway, click **More info**, then **Run anyway**.
    Windows usually stops warning after the first launch.

!!! note "Administrator privileges and the UAC prompt"
    For some features you will need to open SMACC with Administrator privileges
    (right-click the file and select **Run as administrator**). Windows then shows a
    **User Account Control (UAC)** prompt asking whether to allow the app to make
    changes — click **Yes** to continue. For everyday use (audio cues, dream reports,
    LSL markers) you can run SMACC normally, without administrator rights.

## Optional setup

### Data directory

By default SMACC stores everything under `~/SMACC`. To use a different location,
set an environment variable called `SMACC_DIRECTORY` to whatever directory you
want (the older `SMACC_DATA_DIRECTORY` is still honored as a fallback). SMACC
will create it and all of the subfolders (if not already present).

Your reusable setup lives in a **SMACC file** (`.smacc`): cue files, volumes,
event codes, and the **data directory** where its runs are written. SMACC seeds a
`default.smacc` in the SMACC directory (with data directory `~/SMACC/data`) and
opens it when you don't pick another, so it works out of the box. You can keep your
own SMACC files anywhere. See [SMACC files](smacc-files.md).

Each run gets its own timestamped folder under the SMACC file's data directory
(e.g. `smacc-20260607-223015/`) holding that run's `.log`, dream-report recordings,
and any exports. Subject/session are optional metadata (set from **File &rsaquo;
Session info…**) recorded inside the log/exports rather than in filenames. Display
choices that apply to a session — **always-on-top** and which **log-preview** levels
show — are stored in the SMACC file too, so they travel with the study. The machine
itself remembers window positions and sizes and your recent files in
`~/SMACC/preferences.yaml`, restored on the next launch.

### SMACC files (`.smacc`)

Your reusable setup is saved to a portable SMACC file (see
[SMACC files](smacc-files.md)). On the Windows build, the first launch
offers to associate `.smacc` files so you can **double-click one to open SMACC and
run a session with it**; you can also (re)enable this from
**File &rsaquo; Associate .smacc files (Windows)** in the Launcher.

### Audio cues

SMACC seeds a few `demo-*` cue files into the default data directory's `cues/`
folder (restored if you delete them, and refreshed when you upgrade SMACC), so
there is always something to test with. You can also place your own sound files
there — `.wav`, `.mp3`, `.flac`, `.ogg`, and `.aiff` are all supported; only the
`demo-` files are managed by SMACC, so your own are never touched.

### Dream report survey

The **Record Dream Report** button can optionally pop open a survey — one of the
built-in dream questionnaires (opened in a SMACC window, responses saved into the
run folder) or a survey URL hosted on e.g. Qualtrics or REDCap (opened in the
browser). Manage them from the Dream-recording panel's **Manage…** button; saved
URLs persist in your SMACC file. Pick one from the survey dropdown to open it
automatically when recording starts, or open any survey on its own from
**File &rsaquo; Surveys**. See [Surveys](surveys.md).

### Recording device

If you plan to record dreams, bind your mic to the **Bedroom mic** role in the
**Devices** window (in the *Tools* column); the dream-report recorder uses it.
