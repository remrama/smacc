# Sleep Manipulation And Communication Clickything

[![CI](https://github.com/remrama/smacc/actions/workflows/ci.yaml/badge.svg)](https://github.com/remrama/smacc/actions/workflows/ci.yaml)
[![Release](https://github.com/remrama/smacc/actions/workflows/release.yaml/badge.svg)](https://github.com/remrama/smacc/actions/workflows/release.yaml)
[![Codecov](https://codecov.io/gh/remrama/smacc/graph/badge.svg)](https://codecov.io/gh/remrama/smacc)
[![Python](https://img.shields.io/badge/python-3.12-blue.svg)](https://www.python.org/)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)

A clickable interface for running sleep-related experiments.

Used for dream engineering by the [Paller Lab](https://sites.northwestern.edu/pallerlab/) at Northwestern University and the [DxE Lab](https://www.dreamengineeringlab.com/) at the Center for Advanced Research in Sleep Medicine.

* Trigger audio cues
* Collect dream reports
* Trigger EEG portcodes
* Save a detailed event log
* and more!

## Installation

To install SMACC, go to the [releases page](https://github.com/remrama/smacc/releases), click the _Assets_ dropdown for the latest release, and download the _SMACC.exe_ file. Once downloaded, double-clicking this file will run SMACC.

SMACC requires 64-bit Windows 10 or later.

Note that for some features, you will need to open SMACC with Administrator privileges (Right-click to open and select `Run as administrator`).

## Optional setup

* If you don't want to use the default `~/SMACC` folder, you can change this by setting an environment variable called `SMACC_DIRECTORY` equal to whatever directory you want to use (the older `SMACC_DATA_DIRECTORY` is still honored as a fallback). SMACC will create it and all the subfolders (if not already present).

* SMACC opens to a small **launcher** where you pick a **settings file** (`.smacc`) and then start a session, create/edit settings, or analyze a past run. A settings file holds your data-related setup (cues, volumes, event codes, …) plus the **data directory** where its runs are written. SMACC seeds a `default.smacc` in your SMACC directory (data directory `~/SMACC/data`) and opens it when you don't pick another, so it works out of the box. A few `demo-*` cue files are seeded into `~/SMACC/data/cues/` (restored if you delete them); you can also drop your own sound files there (`.wav`, `.mp3`, `.flac`, `.ogg`, and `.aiff` are all supported).

* Each run gets its own timestamped folder under the settings file's data directory (e.g. `smacc-20260607-223015/`) holding that run's `.log`, dream-report recordings, and any exports. Subject/session are optional metadata (set from `File > Session info…`) recorded inside the log/exports rather than in filenames. Any older flat `~/SMACC/cues`, `~/SMACC/sessions`, `~/SMACC/logs`, and `~/SMACC/dreams` folders from earlier versions are left untouched.

* Build a settings file in the **settings editor** (the launcher's `Create settings`, or `Edit…` for an existing one): configure the tools, set the data directory, and save the `.smacc` anywhere. Keep one per participant if you like — they can share a data directory. Cue/noise files and the data directory are stored relative to the `.smacc` when they sit beside it (so a self-contained folder is portable) and absolute otherwise. On Windows you can double-click a `.smacc` to open it. Interface choices (window size/position, theme, always-on-top, log-preview levels) are remembered in `~/SMACC/preferences.yaml`, edited from the launcher's `File > Preferences`.

* There is a `Record Dream Report` button that will start to record from whatever mic is routed to the **Dream-report mic** role (set in the **Devices** window). It can also pop open a survey URL — I use this to open a dream report survey I have set up on Qualtrics. Add your surveys with the `Manage…` button next to the survey dropdown (each has a name and URL, saved to your settings YAML); pick one to open automatically when recording starts, or open any saved survey on its own from `File > Surveys`. If planning to record dreams, bind your mic to the **Bedroom mic** role in the Devices window.

* All device selection lives in one **Devices** window (in the *Tools* column): bind each **role** — bedroom output, control-room output, bedroom mic, BlinkStick — to a device once, then route each modality to a role. Because cue, noise, and your voice can all share one speaker, re-pointing it is a single change. Optional routes add a **cue monitor** (the cue also plays in the control room) and an intercom **Listen** (hear the participant on the control-room output). The whole setup is saved in the `.smacc` file and restored on the next launch; a bound device that isn't connected is flagged. Plugging a device in is detected automatically, or use `File > Refresh devices` (`F5`) — audio devices rescan only while nothing is playing or recording.

## Documentation

Full user and developer documentation is published at
<https://remrama.github.io/smacc/>.

## Development

This project uses [uv](https://docs.astral.sh/uv/) for environment management.
See the [Contributing guide](docs/contributing.md) for environment setup, running
the app, tests, linting, building the executable, and building the docs locally.
