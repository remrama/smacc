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

* There is a `Record Dream Report` button that will start to record from whatever external recording device is selected from the SMACC menubar. There is also an option to have it pop open a website URL. I use this to open up a dream report survey I have set up on Qualtrics. If you want it to open something, update the `SURVEY_URL` variable in `config.py`. If planning to record dreams, choose sound device for recording audio from the menubar (`Audio > Input device > [choose device]`).

## Development

This project uses [uv](https://docs.astral.sh/uv/) for environment management.

```sh
uv sync --extra dev        # create the environment with dev tools
uv run python entry.py     # launch the app
uv run pytest              # run the test suite
uv run ruff check .        # lint
uv run ruff format .       # format
uv run mypy                # type-check
pre-commit install         # enable the lint/format/type-check git hooks
```

Build the standalone Windows executable:

```sh
uv run pyinstaller entry.py --name SMACC --onefile --noconsole \
  --icon src/smacc/assets/icon.ico \
  --add-data "src/smacc/assets/icon.png:smacc/assets" \
  --add-data "src/smacc/assets/cues:smacc/assets/cues"
```

Releases are built automatically: pushing a `v*` tag (e.g. `v0.0.7`) triggers the
[release workflow](.github/workflows/release.yaml), which builds `SMACC.exe` and
attaches it to the GitHub Release.
