# Installation

[Download SMACC](https://github.com/remrama/smacc/releases/latest/download/SMACC-Setup.exe){ .md-button .md-button--primary }

The button above always downloads the installer for the **latest** version —
double-click `SMACC-Setup.exe` and click through. The installer:

- installs SMACC **per-user** — no administrator rights or IT involvement needed;
- adds a **Start menu** entry (and, if you opt in, a desktop shortcut);
- associates **`.smacc` files**, so double-clicking a SMACC file opens a session
  with it;
- optionally installs the **EEG Review Tools** — the post-hoc
  [EEG viewer/annotator](eeg-review.md). Off by default (it carries the
  heavyweight MNE library); choose **Full installation** to include it, or
  re-run the installer later to add it;
- registers an uninstaller — remove SMACC from **Settings › Apps** like any other
  program. Uninstalling never touches your data: SMACC files, recordings, and
  logs under `~/SMACC` (or your data directories) all stay put.

Installing a newer version over an existing one upgrades it in place, keeping
whichever components you had chosen.

To get an older or specific version, browse the
[releases page](https://github.com/remrama/smacc/releases): pick the release you
want, open its _Assets_ dropdown, and download from there. (The version switcher
on this documentation site switches the *docs* only — older copies of SMACC
itself come from the releases page.)

!!! note "System requirements"
    SMACC runs on 64-bit Windows 10 or later.

!!! warning "Windows SmartScreen — “Windows protected your PC”"
    SMACC isn't code-signed yet, so when you run the installer Windows SmartScreen
    may show a blue **“Windows protected your PC”** box. This is expected for any
    new, unsigned program. To proceed anyway, click **More info**, then
    **Run anyway**.

!!! note "Administrator privileges and the UAC prompt"
    For some features you will need to open SMACC with Administrator privileges
    (right-click the Start menu entry and select **Run as administrator**). Windows
    then shows a **User Account Control (UAC)** prompt asking whether to allow the
    app to make changes — click **Yes** to continue. For everyday use (audio cues,
    dream reports, LSL markers) you can run SMACC normally, without administrator
    rights.

## Portable SMACC.exe (no install)

Every release also ships the same app as a single portable `SMACC.exe` — download
it, double-click it, no installation. This suits USB-stick deployment, machines
where nothing may be installed, and quick tests. The portable build skips the
installer's conveniences (Start menu entry, uninstaller); it offers to associate
`.smacc` files itself the first time it runs (see below). The
[EEG review tool](eeg-review.md) is likewise available portable as
`SMACC-EEG.exe` — put it **next to** `SMACC.exe` and the Launcher's *Review
EEG* button lights up (it also runs standalone).

!!! note "For IT departments"
    The default install is per-user (under `%LOCALAPPDATA%\Programs\SMACC`, no
    elevation). On managed machines where per-user installs are blocked — e.g.
    AppLocker policies on `%LOCALAPPDATA%` — run the same installer machine-wide
    instead: `SMACC-Setup.exe /ALLUSERS` (elevates, installs to Program Files).

## Updating SMACC

From the Launcher, **File &rsaquo; Check for updates…** asks GitHub whether a
newer release exists and, if one does, offers to open the download page in your
browser — run the new installer and it upgrades the existing install in place.
SMACC never checks on its own: lab machines are often offline, and studies
usually pin one version for their whole run, so checking is always an explicit
click. If you use the portable `SMACC.exe`, download the new one and replace
your old copy.

## Optional setup

### Data directory

By default SMACC stores everything under `~/SMACC`. To use a different location,
set an environment variable called `SMACC_DIRECTORY` to whatever directory you
want. SMACC will create it and all of the subfolders (if not already present).

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
[SMACC files](smacc-files.md)). The installer associates `.smacc` files so you can
**double-click one to open SMACC and run a session with it**. The portable
`SMACC.exe` offers the same association the first time it runs; you can also
(re)enable it any time from **File &rsaquo; Associate .smacc files (Windows)** in
the Launcher.

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

If you plan to record dreams, bind your mic to **Bedroom mic 1** in the
**Devices** window (in the *Tools* column); the dream-report recorder uses it.
