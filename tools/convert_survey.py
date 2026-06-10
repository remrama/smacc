"""Convert legacy questionnaire files into SMACC survey YAML (#114).

The lab's old survey collection exists in two shapes, and this tool converts
either into the bundled-survey format documented in docs/surveys.md:

* **HTML radio matrices** — a ``<h3>`` title and one ``<table>`` whose header row
  holds the anchor labels (the first ``<th>`` optionally a shared item stem,
  kept as the survey's instructions) and whose body rows hold one item plus its
  radio buttons (the radio ``value``s define the scale range).
* **BIDS-style JSON sidecars** — a ``MeasurementToolMetadata`` block (title,
  optional ``PublicationDOI`` kept as the citation) plus one entry per item with
  a ``Description`` and a ``Levels`` mapping (a ``-99``/blank level means
  "unanswered" and is dropped: SMACC records unanswered items as ``null``).

Only fixed single-scale Likert questionnaires convert; anything with per-item
scales or non-radio inputs (free text, dropdowns, checkboxes) is rejected so it
can't be silently mangled.

Usage (writes ``<key>.yaml`` per input into the output directory)::

    uv run python tools/convert_survey.py TEMP/DLQ.json TEMP/LUSK.html \
        --out src/smacc/assets/surveys
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from html.parser import HTMLParser
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import yaml  # noqa: E402

from smacc import surveys  # noqa: E402

# Bundled files open with the same self-identifying comment style as default.smacc.
_FILE_HEADER = "# SMACC built-in survey — YAML (see docs/surveys.md).\n"


def _clean(text: str) -> str:
    """Collapse whitespace runs (HTML line breaks arrive as spaces)."""
    return re.sub(r"\s+", " ", text).strip()


class _MatrixParser(HTMLParser):
    """Pull title, header anchors, and item rows out of a radio-matrix table."""

    def __init__(self) -> None:
        super().__init__()
        self.title = ""
        self.stem = ""  # the first <th>: a shared item stem, if any
        self.anchors: list[str] = []
        self.items: list[tuple[str, list[int]]] = []  # (text, radio values)
        self.rejected: list[str] = []  # non-radio inputs found (unconvertible)
        self._in_title = False
        self._cell: list[str] | None = None  # collects text inside th/td
        self._row_cells: list[str] = []
        self._row_values: list[int] = []
        self._row_is_header = False

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "h3":
            self._in_title = True
        elif tag == "tr":
            self._row_cells = []
            self._row_values = []
            self._row_is_header = False
        elif tag in ("th", "td"):
            self._cell = []
            if tag == "th":
                self._row_is_header = True
        elif tag == "br" and self._cell is not None:
            self._cell.append(" ")
        elif tag == "input":
            if attrs.get("type") == "radio":
                self._row_values.append(int(attrs.get("value", "0")))
            else:
                self.rejected.append(f"<input type={attrs.get('type')!r}>")
        elif tag in ("select", "textarea"):
            self.rejected.append(f"<{tag}>")

    def handle_endtag(self, tag):
        if tag == "h3":
            self._in_title = False
        elif tag in ("th", "td") and self._cell is not None:
            self._row_cells.append(_clean("".join(self._cell)))
            self._cell = None
        elif tag == "tr":
            if self._row_is_header and not self.anchors:
                self.stem, *self.anchors = self._row_cells or [""]
            elif self._row_values:
                self.items.append((self._row_cells[0], self._row_values))

    def handle_data(self, data):
        if self._in_title:
            self.title += data
        elif self._cell is not None:
            self._cell.append(data)


def _from_html(path: Path) -> dict:
    """Convert one HTML radio matrix to the survey-mapping fields it defines."""
    parser = _MatrixParser()
    parser.feed(path.read_text(encoding="utf-8"))
    if parser.rejected:
        raise ValueError(
            f"contains non-radio inputs ({', '.join(sorted(set(parser.rejected)))}); "
            "only fixed-scale Likert matrices convert"
        )
    if not parser.items:
        raise ValueError("no radio-matrix rows found")
    values = sorted({v for _, row in parser.items for v in row})
    expected = list(range(values[0], values[-1] + 1))
    if values != expected or any(sorted(row) != expected for _, row in parser.items):
        raise ValueError("items use differing scales; one shared scale is required")
    anchors = parser.anchors
    # An all-blank anchor row (or a trailing n/a column) carries no labels.
    anchors = anchors[: len(expected)]
    if not any(anchors):
        anchors = []
    elif len(anchors) < len(expected):
        anchors += [""] * (len(expected) - len(anchors))
    return {
        "title": _clean(parser.title),
        "instructions": parser.stem,
        "scale": {"min": expected[0], "max": expected[-1], "anchors": anchors},
        "items": [text for text, _ in parser.items],
    }


def _anchor_from_level(value: int, label: str) -> str:
    """A level's anchor text: drop bare numbers and ``N - `` label prefixes."""
    label = _clean(label)
    if label == str(value):
        return ""
    return re.sub(rf"^{value}\s*-\s*", "", label)


def _from_json(path: Path) -> dict:
    """Convert one BIDS-style JSON sidecar to the survey-mapping fields."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    meta = payload.pop("MeasurementToolMetadata", {})
    items: list[str] = []
    level_sets: list[dict[int, str]] = []
    for entry in payload.values():
        if entry.get("ResponseType", "radio") not in ("radio",):
            raise ValueError(
                f"item type {entry['ResponseType']!r} is not a fixed Likert scale"
            )
        items.append(_clean(entry["Description"]))
        levels = {
            int(value): label
            for value, label in entry.get("Levels", {}).items()
            if int(value) >= 0  # -99/blank == unanswered; SMACC stores null
        }
        level_sets.append(levels)
    if not items:
        raise ValueError("no items found")
    if any(set(levels) != set(level_sets[0]) for levels in level_sets):
        raise ValueError("items use differing scales; one shared scale is required")
    values = sorted(level_sets[0])
    if values != list(range(values[0], values[-1] + 1)):
        raise ValueError("scale values are not consecutive")
    anchors = [_anchor_from_level(v, level_sets[0][v]) for v in values]
    title = _clean(str(meta.get("Description", "")))
    # A trailing version suffix in the title ("… V1.3") becomes the version field.
    version = ""
    match = re.fullmatch(r"(.*?)\s+[Vv](\d[\w.]*)", title)
    if match:
        title, version = match.group(1), match.group(2)
    doi = _clean(str(meta.get("PublicationDOI", "")))
    return {
        "title": title,
        "version": version,
        "citation": f"doi:{doi}" if doi else "",
        "scale": {
            "min": values[0],
            "max": values[-1],
            "anchors": anchors if any(anchors) else [],
        },
        "items": items,
    }


def convert(path: Path) -> dict:
    """Build the full, validated survey mapping for one legacy file."""
    fields = (_from_json if path.suffix.lower() == ".json" else _from_html)(path)
    name = path.stem
    mapping = {
        "kind": surveys.KIND,
        "schema_version": surveys.SCHEMA_VERSION,
        "key": surveys.slugify_key(name),
        "name": name,
        "title": fields.get("title") or name,
        "version": fields.get("version") or "1.0",
        "citation": fields.get("citation", ""),
        "instructions": fields.get("instructions", ""),
        "scale": fields["scale"],
        "items": fields["items"],
    }
    surveys.parse_survey_mapping(mapping)  # the same gate SMACC loads through
    return mapping


def main(argv: list[str] | None = None) -> int:
    cli = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    cli.add_argument("sources", nargs="+", type=Path, help="HTML/JSON survey files")
    cli.add_argument("--out", type=Path, required=True, help="output directory")
    args = cli.parse_args(argv)
    args.out.mkdir(parents=True, exist_ok=True)
    failures = 0
    for source in args.sources:
        try:
            mapping = convert(source)
        except (ValueError, KeyError, json.JSONDecodeError) as exc:
            print(f"SKIP {source.name}: {exc}")
            failures += 1
            continue
        dest = args.out / f"{mapping['key']}.yaml"
        text = yaml.safe_dump(
            mapping, sort_keys=False, default_flow_style=False, allow_unicode=True
        )
        dest.write_text(_FILE_HEADER + text, encoding="utf-8")
        print(
            f"{source.name} -> {dest.name}: {len(mapping['items'])} items, "
            f"scale {mapping['scale']['min']}-{mapping['scale']['max']}"
        )
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
