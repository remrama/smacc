#!/usr/bin/env bash
# lint-on-stop.sh
# Run ruff check+format only when Python files have changed.
cd "$CLAUDE_PROJECT_DIR"

if (git diff --name-only; git ls-files --others --exclude-standard) | grep -q '\.py$'; then
    uv run ruff check --fix src/ tests/ --quiet || true
    uv run ruff format src/ tests/ --quiet || true
fi

exit 0