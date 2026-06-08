# Sleep Manipulation And Communication Clickything

[![CI](https://github.com/remrama/smacc/actions/workflows/ci.yaml/badge.svg)](https://github.com/remrama/smacc/actions/workflows/ci.yaml)
[![Release](https://github.com/remrama/smacc/actions/workflows/release.yaml/badge.svg)](https://github.com/remrama/smacc/actions/workflows/release.yaml)
[![Python](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)

A clickable interface for running sleep-related experiments.

* Trigger audio cues
* Collect dream reports
* Trigger EEG portcodes
* Save a detailed event log
* and more!

## Installation

To install SMACC, go to the [releases page](https://github.com/remrama/smacc/releases), click the _Assets_ dropdown for the latest release, and download the _SMACC.exe_ file. Once downloaded, double-clicking this file will run SMACC.

Note that for some features, you will need to open SMACC with Administrator privileges (Right-click to open and select `Run as administrator`).

## Optional setup

* If you don't want to use the default `~/SMACC` folder, you can change this by setting a new environment variable called `SMACC_DATA_DIRECTORY` equal to whatever directory you want to use. SMACC will create it and all the subfolders (if not already present).

* SMACC seeds a few `demo-*` cue files into `~/SMACC/cues` on first launch (restored if you delete them), so there's always something to test with. You can also place your own sound files there (`.wav`, `.mp3`, `.flac`, `.ogg`, and `.aiff` are all supported).

* Each run gets its own timestamped folder under `~/SMACC/sessions/` (e.g. `smacc-20260607-223015/`) holding that run's `.log`, dream-report recordings, and any exports. Subject/session are now optional metadata (set from `File > Session info…`) recorded inside the log/exports rather than in filenames. Any older `~/SMACC/logs` and `~/SMACC/dreams` folders are left untouched.

* You can save a reusable setup to a portable `.smacc` study file with `File > Export study (.smacc)…` and reload it with `File > Load study (.smacc)…` (or pull the initial/final setup back out of a `.log` with `File > Load study from log…`). Cue files are referenced (not copied), stored relative to the `.smacc` when they sit beside it so a study folder is portable. On Windows you can double-click a `.smacc` to open it. Operator/machine choices (window size/position, theme, always-on-top, log-preview levels) are remembered in `~/SMACC/preferences.yaml`.

* There is a `Record Dream Report` button that will start to record from whatever external recording device is selected from the SMACC menubar. There is also an option to have it pop open a website URL. I use this to open up a dream report survey I have set up on Qualtrics. If you want it to open something, update the `SURVEY_URL` variable in `config.py`. If planning to record dreams, choose sound device for recording audio from the menubar (`Audio > Input device > [choose device]`).

## Documentation

Full user and developer documentation is published at
<https://remrama.github.io/smacc/>.

## Development

This project uses [uv](https://docs.astral.sh/uv/) for environment management.
See the [Contributing guide](docs/contributing.md) for environment setup, running
the app, tests, linting, building the executable, and building the docs locally.
