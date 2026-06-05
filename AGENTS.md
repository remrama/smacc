# Agent & contributor instructions

This is the canonical instruction file for both human contributors and AI coding
assistants working on SMACC.

## Conventions

- Always use `uv` when running Python scripts or installing dependencies. Never
  `pip install` or run naked `python`.
- Prefer shell commands over PowerShell commands.

## Development

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
uv run pyinstaller entry.py --name SMACC --onefile --noconsole
```

## Project notes

- `src/` layout: the package lives in `src/smacc/`.
- The single source of truth for the version is `__version__` in
  `src/smacc/__init__.py`; `config.py` and the packaging metadata both read from it.
- See the [README](./README.md) for user-facing project information.
