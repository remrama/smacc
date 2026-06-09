# Contributing

!!! info "For both human and AI contributors"
    This page is the canonical development guide for SMACC. It is written for both
    human contributors and AI coding assistants — AI agents are pointed here from
    [`AGENTS.md`](https://github.com/remrama/smacc/blob/main/AGENTS.md), so the
    instructions live here once rather than being duplicated across files.

!!! info "Requesting a change? Open a GitHub issue"
    Human contributors should open a
    [GitHub issue](https://github.com/remrama/smacc/issues) for new feature
    requests or bug reports before starting work, so changes can be discussed
    first.

## Conventions

* Always use [uv](https://docs.astral.sh/uv/) to run Python scripts and install
  dependencies. Never `pip install` or run naked `python`.

## Development

```sh
uv sync --extra dev        # create the environment with dev tools
uv run python -m smacc     # launch the app
uv run pytest              # run the test suite
uv run ruff check .        # lint
uv run ruff format .       # format
uv run mypy                # type-check
pre-commit install         # enable the lint/format/type-check git hooks
```

`uv run smacc` also works once the environment is synced — it's the installed GUI
launcher and opens no console window, so prefer `python -m smacc` when you want
terminal output (e.g. tracebacks).

## Building the executable

Build the standalone Windows executable:

```sh
uv run pyinstaller entry.py --name SMACC --onefile --noconsole \
  --icon src/smacc/assets/icon.ico \
  --add-data "src/smacc/assets/icon.png:smacc/assets" \
  --add-data "src/smacc/assets/cues:smacc/assets/cues"
```

`--icon` sets the executable's file icon; `--add-data` bundles the runtime
window/taskbar icon, which SMACC resolves via `sys._MEIPASS`. On Windows the
`--add-data` separator is `;` rather than `:` (i.e. `...png;smacc/assets`).

PyYAML (settings export/import) is pure Python and is picked up automatically by
PyInstaller; if a frozen build ever fails to import `yaml`, add
`--hidden-import yaml`.

The `blinkstick` driver (BlinkStick visual cues) and its Windows backend
`pywinusb` are pure Python and bundle the same way. PyInstaller may warn that
`usb.core` is missing — that is BlinkStick's non-Windows backend, which SMACC
never uses, so the warning is harmless. If a frozen build ever fails to import
the driver, add `--hidden-import pywinusb`.

Releases are built automatically: pushing a `v*` tag (e.g. `v0.0.7`) triggers the
[release workflow](https://github.com/remrama/smacc/blob/main/.github/workflows/release.yaml),
which builds `SMACC.exe` and attaches it to the GitHub Release.

## Building the docs

The documentation site is built with [MkDocs](https://www.mkdocs.org/) +
[Material](https://squidfunk.github.io/mkdocs-material/) and versioned with
[mike](https://github.com/jimporter/mike). All pages are plain Markdown under
`docs/`.

```sh
uv run --extra docs mkdocs serve          # live-reload preview at http://localhost:8000
uv run --extra docs mkdocs build --strict # the exact build the PR CI runs
uv run --extra docs mike serve            # preview the versioned site
```

The [docs workflow](https://github.com/remrama/smacc/blob/main/.github/workflows/docs.yaml)
runs `mkdocs build --strict` on every pull request, deploys a `dev` version on
pushes to `main`, and publishes a numbered version (updating the `latest` alias)
on each `v*` release tag.

## Project notes

* `src/` layout: the package lives in `src/smacc/`.
* The single source of truth for the version is `__version__` in
  `src/smacc/__init__.py`; `config.py` and the packaging metadata both read from
  it.
* The build/runtime Python is pinned to **3.12** in `.python-version`. This is
  deliberate: 3.12 is the last Python line that supports Windows 8.1, so it keeps
  SMACC runnable on older lab machines. Bumping to 3.13+ would raise the minimum
  to Windows 10 — don't do it without accepting that trade-off.
* SMACC is distributed only as a frozen `SMACC.exe` (no PyPI), so CI tests what
  ships rather than a version range: the `test` job in `ci.yaml` runs on the same
  `windows-2022` + Python 3.12 + locked dependencies as the release build
  (`release.yaml`), in a single job rather than a multi-version matrix.
