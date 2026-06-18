# Installation

[Download SMACC](https://github.com/remrama/smacc/releases/latest/download/SMACC-Setup.exe){.btn .btn-primary role="button"}

The button above always downloads the installer for the **latest** version —
double-click `SMACC-Setup.exe` and click through. The installer:

- installs SMACC **per-user** — no administrator rights or IT involvement needed;
- adds a **Start menu** entry (and, if you opt in, a desktop shortcut);
- associates **`.smacc` files**, so double-clicking one opens the **Start a session**
  dialog with it preselected;
- includes the **EEG Annotator** — the post-hoc
  [EEG viewer/annotator](eeg-annotator.md), opened from the Launcher;
- registers an uninstaller — remove SMACC from **Settings › Apps** like any other
  program. Uninstalling never touches your data: SMACC files, recordings, and
  logs under `~/SMACC` (or your data directories) all stay put. The
  uninstaller reminds you of this (and of the folder's location) when it
  finishes, so finding the folder afterwards is expected — delete it manually
  if you no longer need the data.

Installing a newer version over an existing one upgrades it in place.

To get an older or specific version, browse the
[releases page](https://github.com/remrama/smacc/releases): pick the release you
want, open its _Assets_ dropdown, and download from there.

::: {.callout-note title="System requirements"}

SMACC runs on 64-bit Windows 10 or later.

:::

::: {.callout-warning title="Windows SmartScreen — “Windows protected your PC”"}

SMACC isn't code-signed yet, so when you run the installer Windows SmartScreen
may show a blue **“Windows protected your PC”** box. This is expected for any
new, unsigned program. To proceed anyway, click **More info**, then
**Run anyway**.

:::

::: {.callout-note title="Administrator privileges and the UAC prompt"}

For some features you will need to open SMACC with Administrator privileges
(right-click the Start menu entry and select **Run as administrator**). Windows
then shows a **User Account Control (UAC)** prompt asking whether to allow the
app to make changes — click **Yes** to continue. For everyday use (audio cues,
dream reports, LSL markers) you can run SMACC normally, without administrator
rights.

:::

::: {.callout-note title="For IT departments"}

The default install is per-user (under `%LOCALAPPDATA%\Programs\SMACC`, no
elevation). On managed machines where per-user installs are blocked — e.g.
AppLocker policies on `%LOCALAPPDATA%` — run the same installer machine-wide
instead: `SMACC-Setup.exe /ALLUSERS` (elevates, installs to Program Files).

:::

## Updating SMACC

From the Launcher, **File › Check for updates…** asks GitHub whether a
newer release exists and, if one does, offers to open the download page in your
browser — run the new installer and it upgrades the existing install in place.
SMACC never checks on its own: lab machines are often offline, and studies
usually pin one version for their whole run, so checking is always an explicit
click.

## Development build (experimental)

Every code change merged to `main` is rebuilt and published as a single rolling
**development build**, so you can try an unreleased fix or feature before the next
stable release.

[Download the development build](https://github.com/remrama/smacc/releases/download/dev/SMACC-dev.zip){.btn .btn-secondary role="button"}

Unzip it and run `SMACC.exe` from the extracted `SMACC` folder. It's portable, so it
runs without installing and leaves any installed copy of SMACC untouched.

::: {.callout-warning title="For testing only"}

The development build is unsigned, unreleased, and **not tested**, and it is
overwritten every time `main` changes — so it's a moving target, not a fixed
version. Don't use it to run a study; pin a stable release for that. The
**Download SMACC** button at the top of this page and the in-app **File › Check
for updates…** always point at the latest *stable* release, never this build.

:::

## After installing

By default SMACC stores everything under `~/SMACC`. To use a different location, set
the environment variable `SMACC_DIRECTORY` to the directory you want; SMACC creates
it and its subfolders on first run.

The rest of setup is covered on the relevant pages:

- **Your study configuration** lives in a portable [SMACC file](smacc-files.md).
  SMACC seeds a `default.smacc` and opens it when you don't pick another, so it
  works out of the box. The installer associates `.smacc` files; enable or repair
  the association any time from **File › Associate .smacc files (Windows)** in the
  Launcher.
- **Audio cues** go in the data directory's `cues/` folder, alongside the seeded
  `demo-*` cues — see [Audio cues](audio-cues.md).
- **Dream-report surveys** are managed from the Dream recording panel — see
  [Dream reports & surveys](surveys.md).
- **A recording mic:** to record dreams, bind your mic to **Bedroom mic 1** in the
  **Devices** window (the **Panels** column) — see [Audio routing](audio.md).
