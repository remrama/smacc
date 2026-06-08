# Sleep Manipulation And Communication Clickything

[![CI](https://github.com/remrama/smacc/actions/workflows/ci.yaml/badge.svg)](https://github.com/remrama/smacc/actions/workflows/ci.yaml)
[![Release](https://github.com/remrama/smacc/actions/workflows/release.yaml/badge.svg)](https://github.com/remrama/smacc/actions/workflows/release.yaml)
[![Python](https://img.shields.io/badge/python-3.12-blue.svg)](https://www.python.org/)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)

A clickable interface for running sleep-related experiments.

* Trigger audio cues
* Collect dream reports
* Trigger EEG portcodes
* Save a detailed event log
* and more!

## Installation

To install SMACC, go to the [releases page](https://github.com/remrama/smacc/releases), click the _Assets_ dropdown for the latest release, and download the _SMACC.exe_ file. Once downloaded, double-clicking this file will run SMACC.

SMACC requires 64-bit Windows 8.1 or later.

Note that for some features, you will need to open SMACC with Administrator privileges (Right-click to open and select `Run as administrator`).

## Optional setup

* If you don't want to use the default `~/SMACC` folder, you can change this by setting a new environment variable called `SMACC_DATA_DIRECTORY` equal to whatever directory you want to use. SMACC will create it and all the subfolders (if not already present).

* SMACC seeds a few `demo-*` cue files into `~/SMACC/cues` on first launch (restored if you delete them), so there's always something to test with. You can also place your own sound files there (`.wav`, `.mp3`, `.flac`, `.ogg`, and `.aiff` are all supported).

* Each run gets its own timestamped folder under `~/SMACC/sessions/` (e.g. `smacc-20260607-223015/`) holding that run's `.log`, dream-report recordings, and any exports. Subject/session are now optional metadata (set from `File > Session info…`) recorded inside the log/exports rather than in filenames. Any older `~/SMACC/logs` and `~/SMACC/dreams` folders are left untouched. You can save the current setup with `File > Export settings (YAML)…` and reload it later with `File > Load settings (YAML)…` (or pull the initial/final settings back out of a `.log` with `File > Load settings from log…`).

* There is a `Record Dream Report` button that will start to record from whatever external recording device is selected from the SMACC menubar. It can also pop open a survey URL — I use this to open a dream report survey I have set up on Qualtrics. Add your surveys with the `Manage…` button next to the survey dropdown (each has a name and URL, saved to your settings YAML); pick one to open automatically when recording starts, or open any saved survey on its own from `File > Surveys`. If planning to record dreams, choose sound device for recording audio from the menubar (`Audio > Input device > [choose device]`).

## Documentation

Full user and developer documentation is published at
<https://remrama.github.io/smacc/>.

## Development

This project uses [uv](https://docs.astral.sh/uv/) for environment management.
See the [Contributing guide](docs/contributing.md) for environment setup, running
the app, tests, linting, building the executable, and building the docs locally.
