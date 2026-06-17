"""Completeness check for the single-file PDF manual.

Guards against the failure mode that motivated #250: a wide table (or any element)
that a renderer can't lay out silently dropping that page and everything after it,
leaving a truncated manual that still "builds" green. Run in CI after the PDF build:

    uv run --extra docs python pdf/check_manual.py site/pdf/smacc-manual.pdf

Exits non-zero (with a clear message) if the manual is short or is missing content
from its later sections. The tripwire strings are distinctive tokens that live in
the second half of the manual — past the table that used to truncate it.
"""

import sys

from pypdf import PdfReader

# Generous floor; the manual is ~88 pages. Truncation collapsed it to ~29.
MIN_PAGES = 50

# One distinctive token from each of several late sections. If the manual truncates
# at the wide event-codes table (the old failure), every one of these disappears.
REQUIRED = [
    "inpoutx64",  # Markers & port codes (right after the wide tables)
    "WASAPI",  # Audio routing
    "BlinkStick",  # Visual cues / Compatible devices
    "hypnogram",  # EEG Annotator
    "Conventional",  # Contributing (commit style)
]


def main(path: str) -> int:
    reader = PdfReader(path)
    pages = len(reader.pages)
    text = "\n".join(page.extract_text() or "" for page in reader.pages)

    problems = []
    if pages < MIN_PAGES:
        problems.append(
            f"only {pages} pages (expected >= {MIN_PAGES}) — manual looks truncated"
        )
    missing = [token for token in REQUIRED if token not in text]
    if missing:
        problems.append(f"missing expected content: {', '.join(missing)}")

    if problems:
        print(f"FAIL: {path}")
        for problem in problems:
            print(f"  - {problem}")
        return 1

    print(f"OK: {path} ({pages} pages, all tripwire content present)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "site/pdf/smacc-manual.pdf"))
