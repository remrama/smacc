"""Built-in and user-built surveys: definitions, loading, and response payloads.

SMACC ships standard dream questionnaires (LuCiD, DLQ, LUSK; #114) as YAML
definition files under ``assets/surveys/`` and renders them in an in-app window
(:mod:`smacc.panels.survey`), so responses are collected locally — next to the
dream report they accompany — instead of through a hosted form. A lab can add its
own surveys in the same format (built with the in-app builder, or written by
hand) to the SMACC root's ``surveys`` folder.

The on-disk shape (a survey file is YAML with a ``kind`` discriminator, like the
``.smacc`` settings format)::

    kind: smacc/survey
    schema_version: 2
    key: dlq                # stable id; also names response files
    name: DLQ               # short label (dropdown, File menu)
    title: Dream Lucidity Questionnaire (DLQ)
    version: "1.0"          # content version, recorded in every response
    citation: "..."
    instructions: "..."
    scale: {min: 0, max: 4, anchors: [..., one per scale point, ...]}
    items:
      - a bare string               # a Likert item on the shared scale (above)
      - text: Age                   # or a typed item (schema_version 2+):
        type: number                #   likert | select | number | text | heading
        min: 0
        max: 99
        unit: years
      - text: How often do you recall dreams?
        type: select                # a dropdown with its own ordered levels
        help: "shown under the item"
        levels: {0: never, 1: rarely, 2: often}

A plain-string item is a Likert item on the survey's shared scale — the original
(and still most common) shape, so the bundled single-scale instruments need no
``type`` and stay ``schema_version: 1``. Typed items (anything but a bare-string
Likert) require ``schema_version: 2``; an older SMACC then rejects the file with a
clear version error instead of mis-reading it. Responses are written as one JSON
file per administration (see :func:`response_payload` / :func:`response_filename`),
carrying the survey key *and* content version so an analysis can always tell which
wording a given night used.

In the survey dropdown and the saved ``survey_url`` setting, an in-app survey is
addressed by the pseudo-URL ``smacc://survey/<key>``; everything else is treated
as a web URL and opened in the browser as before. Only web URLs persist in
``survey_options`` — in-app surveys come from their definition files.

Pure data and helpers, no Qt — directly unit-testable.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import yaml

from .config import VERSION
from .utils import format_elapsed

# Discriminators for the two YAML/JSON shapes this module owns.
KIND = "smacc/survey"
RESPONSE_KIND = "smacc/survey-response"
SCHEMA_VERSION = 2

# Pseudo-URL scheme addressing an in-app survey in the dropdown / File menu /
# saved ``survey_url``; anything else is a web URL for the browser.
URL_PREFIX = "smacc://survey/"

# Keep a hand-typed Likert scale sane: 2..21 points covers every Likert in the wild.
_MAX_SCALE_POINTS = 21

# Item response types. ``likert`` rates against the survey's shared scale (a radio
# matrix); ``select`` is a dropdown with its own ordered levels; ``number`` and
# ``text`` are free entry; ``heading`` is a display-only section title (no answer).
LIKERT = "likert"
SELECT = "select"
NUMBER = "number"
TEXT = "text"
HEADING = "heading"
ITEM_TYPES = (LIKERT, SELECT, NUMBER, TEXT, HEADING)
# Types that collect an answer (everything but a heading) — used when aligning the
# window's collected values to the items and when building the response payload.
_RESPONSE_TYPES = (LIKERT, SELECT, NUMBER, TEXT)


@dataclass(frozen=True)
class SurveyItem:
    """One survey item: its text, response type, and any per-type extras.

    A ``likert`` item rates against the survey-level scale (``SurveyDef.scale_*``
    / ``anchors``); ``select`` carries its own ordered ``levels``; ``number``
    carries optional bounds and a ``unit``; ``text`` is free entry; ``heading`` is
    a display-only separator that collects no response.
    """

    text: str
    type: str = LIKERT
    help: str = ""
    levels: tuple[tuple[int, str], ...] = ()  # (value, label), select only
    number_min: int | None = None
    number_max: int | None = None
    unit: str = ""

    @property
    def collects_response(self) -> bool:
        """True for everything but a display-only heading."""
        return self.type in _RESPONSE_TYPES

    def level_label(self, value: int | None) -> str:
        """The chosen level's label for a ``select`` item ("" if not found)."""
        for level_value, label in self.levels:
            if level_value == value:
                return label
        return ""


@dataclass(frozen=True)
class SurveyDef:
    """One survey: identity, version, a shared Likert scale, and its items.

    ``scale_min``/``scale_max``/``anchors`` define the default scale that
    ``likert`` items rate against; other item types carry their own scale (or
    none). ``items`` is a tuple of :class:`SurveyItem`.
    """

    key: str
    name: str  # short label (dropdown / File menu), e.g. "DLQ"
    title: str  # full display title
    version: str = "1.0"  # content version, recorded in every response
    citation: str = ""
    instructions: str = ""
    scale_min: int = 0
    scale_max: int = 4
    anchors: tuple[str, ...] = ()  # one label per scale point ("" allowed)
    items: tuple[SurveyItem, ...] = ()
    builtin: bool = True  # False for user-built surveys (editable/removable)
    path: Path | None = None  # source file (None for unsaved builder drafts)

    @property
    def url(self) -> str:
        """The pseudo-URL addressing this survey (``smacc://survey/<key>``)."""
        return URL_PREFIX + self.key

    @property
    def n_points(self) -> int:
        """Number of points on the shared Likert scale."""
        return self.scale_max - self.scale_min + 1

    @property
    def is_simple_likert(self) -> bool:
        """True if every item is a plain Likert item with no help text.

        Such a survey round-trips losslessly through the simple builder dialog;
        anything richer (typed items, help, headings) must be edited as a file.
        """
        return all(it.type == LIKERT and not it.help for it in self.items)

    @property
    def response_items(self) -> tuple[SurveyItem, ...]:
        """The items that collect a response (headings excluded)."""
        return tuple(it for it in self.items if it.collects_response)

    def anchor_for(self, value: int) -> str:
        """The shared-scale anchor label for ``value`` ("" when absent)."""
        index = value - self.scale_min
        if 0 <= index < len(self.anchors):
            return self.anchors[index]
        return ""


def survey_key_from_url(url: str) -> str | None:
    """Return the survey key a ``smacc://survey/<key>`` URL addresses, else None."""
    if isinstance(url, str) and url.startswith(URL_PREFIX):
        return url[len(URL_PREFIX) :] or None
    return None


def slugify_key(name: str) -> str:
    """Derive a filename-safe survey key from a display name (builder dialog)."""
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return slug or "survey"


def _require_str(mapping: dict, field_name: str, *, required: bool = True) -> str:
    value = mapping.get(field_name, "")
    if value is None:
        value = ""
    if not isinstance(value, str):
        raise ValueError(f"Survey field {field_name!r} must be text.")
    value = value.strip()
    if required and not value:
        raise ValueError(f"Survey field {field_name!r} is required.")
    return value


def _parse_levels(raw: Any) -> tuple[tuple[int, str], ...]:
    """Parse a ``select`` item's ``levels`` mapping into ordered (value, label)s."""
    if not isinstance(raw, dict) or not raw:
        raise ValueError("A 'select' item needs a non-empty 'levels' mapping.")
    levels: list[tuple[int, str]] = []
    for key, label in raw.items():
        if isinstance(key, bool):
            raise ValueError("Select level keys must be whole numbers.")
        try:
            value = int(key)
        except (TypeError, ValueError):
            raise ValueError(
                f"Select level key {key!r} must be a whole number."
            ) from None
        if not isinstance(label, str) or not label.strip():
            raise ValueError("Each 'select' level needs a non-empty text label.")
        levels.append((value, label.strip()))
    if len(levels) < 2:
        raise ValueError("A 'select' item needs at least two levels.")
    levels.sort(key=lambda pair: pair[0])
    return tuple(levels)


def _parse_bound(raw: dict, field_name: str) -> int | None:
    """Parse an optional whole-number bound for a ``number`` item (None if absent)."""
    value = raw.get(field_name)
    if value is None:
        return None
    if isinstance(value, bool):
        raise ValueError(f"Number item {field_name!r} must be a whole number.")
    try:
        return int(value)
    except (TypeError, ValueError):
        raise ValueError(
            f"Number item {field_name!r} must be a whole number."
        ) from None


def _parse_item(raw: Any) -> SurveyItem:
    """Parse one item entry (a bare string == a Likert item on the shared scale)."""
    if isinstance(raw, str):
        text = raw.strip()
        if not text:
            raise ValueError("Every survey item must be non-empty text.")
        return SurveyItem(text=text, type=LIKERT)
    if not isinstance(raw, dict):
        raise ValueError("A survey item must be text or a mapping.")
    text = _require_str(raw, "text")
    item_type = raw.get("type") or LIKERT
    if item_type not in ITEM_TYPES:
        raise ValueError(
            f"Unknown survey item type {item_type!r} "
            f"(expected one of {', '.join(ITEM_TYPES)})."
        )
    help_text = _require_str(raw, "help", required=False)
    if item_type == SELECT:
        return SurveyItem(
            text=text,
            type=SELECT,
            help=help_text,
            levels=_parse_levels(raw.get("levels")),
        )
    if item_type == NUMBER:
        number_min = _parse_bound(raw, "min")
        number_max = _parse_bound(raw, "max")
        if (
            number_min is not None
            and number_max is not None
            and number_max <= number_min
        ):
            raise ValueError("Number item 'max' must be greater than 'min'.")
        return SurveyItem(
            text=text,
            type=NUMBER,
            help=help_text,
            number_min=number_min,
            number_max=number_max,
            unit=_require_str(raw, "unit", required=False),
        )
    return SurveyItem(
        text=text, type=item_type, help=help_text
    )  # likert / text / heading


def parse_survey_mapping(
    payload: Any, *, builtin: bool = False, path: Path | None = None
) -> SurveyDef:
    """Validate a loaded survey mapping and return its :class:`SurveyDef`.

    Raises:
        ValueError: if ``payload`` isn't a compatible SMACC survey mapping.
    """
    if not isinstance(payload, dict):
        raise ValueError("Not a SMACC survey file (expected a mapping).")
    kind = payload.get("kind")
    if kind != KIND:
        raise ValueError(f"Not a SMACC survey file (kind={kind!r}).")
    version = payload.get("schema_version")
    if isinstance(version, bool) or not isinstance(version, int):
        raise ValueError(f"Unsupported survey schema version {version!r}.")
    if not (1 <= version <= SCHEMA_VERSION):
        raise ValueError(
            f"Unsupported survey schema version {version!r} "
            f"(expected 1..{SCHEMA_VERSION})."
        )
    key = _require_str(payload, "key").lower()
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]*", key):
        raise ValueError(
            f"Survey key {key!r} must be lowercase letters/digits/hyphens "
            "(it names response files)."
        )
    name = _require_str(payload, "name")
    title = _require_str(payload, "title", required=False) or name
    content_version = payload.get("version", "")
    if isinstance(content_version, (int, float)):
        content_version = str(content_version)
    if not isinstance(content_version, str):
        raise ValueError("Survey field 'version' must be text.")

    items_raw = payload.get("items")
    if not isinstance(items_raw, list) or not items_raw:
        raise ValueError("Survey needs a non-empty 'items' list.")
    # Typed items (anything but a bare-string Likert) are a v2 feature; reject them
    # in a v1 file so the version cleanly signals the capability a reader needs.
    if version < 2 and any(not isinstance(item, str) for item in items_raw):
        raise ValueError("Typed survey items require schema_version 2.")
    items = tuple(_parse_item(item) for item in items_raw)
    if not any(it.collects_response for it in items):
        raise ValueError("Survey needs at least one item that collects a response.")

    # A shared Likert scale is required only when a Likert item actually uses it.
    needs_scale = any(it.type == LIKERT for it in items)
    scale = payload.get("scale")
    scale_min, scale_max, anchors = 0, 4, ()
    if scale is not None or needs_scale:
        if not isinstance(scale, dict):
            raise ValueError("Survey field 'scale' must be a mapping with min/max.")
        try:
            scale_min = int(scale["min"])
            scale_max = int(scale["max"])
        except (KeyError, TypeError, ValueError):
            raise ValueError(
                "Survey scale needs whole-number 'min' and 'max'."
            ) from None
        if scale_max <= scale_min:
            raise ValueError("Survey scale 'max' must be greater than 'min'.")
        n_points = scale_max - scale_min + 1
        if n_points > _MAX_SCALE_POINTS:
            raise ValueError(
                f"Survey scale has {n_points} points (max {_MAX_SCALE_POINTS})."
            )
        anchors_raw = scale.get("anchors") or []
        if not isinstance(anchors_raw, list) or not all(
            isinstance(a, str) for a in anchors_raw
        ):
            raise ValueError("Survey scale 'anchors' must be a list of text labels.")
        if anchors_raw and len(anchors_raw) != n_points:
            raise ValueError(
                f"Survey has {len(anchors_raw)} anchors for a {n_points}-point scale "
                "(give one per point, or none)."
            )
        anchors = tuple(a.strip() for a in anchors_raw)

    return SurveyDef(
        key=key,
        name=name,
        title=title,
        version=content_version.strip(),
        citation=_require_str(payload, "citation", required=False),
        instructions=_require_str(payload, "instructions", required=False),
        scale_min=scale_min,
        scale_max=scale_max,
        anchors=anchors,
        items=items,
        builtin=builtin,
        path=path,
    )


def load_survey(path: str | Path, *, builtin: bool = False) -> SurveyDef:
    """Load one survey definition file.

    Raises:
        ValueError: if the file is empty, unparseable, or not a SMACC survey.
        OSError: if the file can't be read.
    """
    path = Path(path)
    text = path.read_text(encoding="utf-8")
    try:
        payload = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ValueError(f"Could not parse YAML: {exc}") from exc
    if payload is None:
        raise ValueError("Empty file; not a SMACC survey file.")
    return parse_survey_mapping(payload, builtin=builtin, path=path)


def load_survey_dir(
    directory: str | Path, *, builtin: bool = False
) -> tuple[list[SurveyDef], list[str]]:
    """Load every ``*.yaml`` survey in ``directory`` (sorted by filename).

    Returns ``(surveys, problems)`` — a malformed or unreadable file becomes a
    one-line problem string instead of aborting the rest, so one bad hand-edited
    survey can't hide the others. A missing directory is simply empty.
    """
    surveys: list[SurveyDef] = []
    problems: list[str] = []
    directory = Path(directory)
    if not directory.is_dir():
        return surveys, problems
    for path in sorted(directory.glob("*.yaml")):
        try:
            surveys.append(load_survey(path, builtin=builtin))
        except (OSError, ValueError) as exc:
            problems.append(f"{path.name}: {exc}")
    return surveys, problems


def all_surveys(
    builtin_dir: str | Path, user_dir: str | Path
) -> tuple[dict[str, SurveyDef], list[str]]:
    """Return every available survey keyed by ``key``, built-ins first.

    A user survey whose key collides with a built-in (or an earlier user file)
    is skipped and reported in the problems list — keys name response files, so
    they must be unambiguous.
    """
    surveys: dict[str, SurveyDef] = {}
    loaded_builtin, problems = load_survey_dir(builtin_dir, builtin=True)
    for survey in loaded_builtin:
        surveys[survey.key] = survey
    loaded_user, user_problems = load_survey_dir(user_dir, builtin=False)
    problems.extend(user_problems)
    for survey in loaded_user:
        if survey.key in surveys:
            problems.append(
                f"{survey.path.name if survey.path else survey.key}: "
                f"key {survey.key!r} already used by another survey; skipped."
            )
            continue
        surveys[survey.key] = survey
    return surveys, problems


def _item_to_mapping(item: SurveyItem) -> str | dict[str, Any]:
    """Serialize one item, collapsing a plain Likert item back to a bare string."""
    if item.type == LIKERT and not item.help:
        return item.text
    out: dict[str, Any] = {"text": item.text, "type": item.type}
    if item.help:
        out["help"] = item.help
    if item.type == SELECT:
        out["levels"] = {value: label for value, label in item.levels}
    elif item.type == NUMBER:
        if item.number_min is not None:
            out["min"] = item.number_min
        if item.number_max is not None:
            out["max"] = item.number_max
        if item.unit:
            out["unit"] = item.unit
    return out


def survey_to_mapping(survey: SurveyDef) -> dict[str, Any]:
    """Serialize a definition for saving as a survey YAML (builder dialog).

    Writes the lowest schema version that fits: a survey of plain Likert items
    stays ``schema_version: 1`` (and emits bare-string items); anything with
    typed items, help, or headings is ``schema_version: 2``.
    """
    mapping: dict[str, Any] = {
        "kind": KIND,
        "schema_version": 1 if survey.is_simple_likert else 2,
        "key": survey.key,
        "name": survey.name,
        "title": survey.title,
        "version": survey.version,
        "citation": survey.citation,
        "instructions": survey.instructions,
    }
    if any(it.type == LIKERT for it in survey.items):
        mapping["scale"] = {
            "min": survey.scale_min,
            "max": survey.scale_max,
            "anchors": list(survey.anchors),
        }
    mapping["items"] = [_item_to_mapping(it) for it in survey.items]
    return mapping


def save_survey(survey: SurveyDef, directory: str | Path) -> Path:
    """Write ``survey`` to ``<directory>/<key>.yaml`` and return the path.

    Raises:
        OSError: if the directory or file can't be written.
    """
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{survey.key}.yaml"
    text = yaml.safe_dump(
        survey_to_mapping(survey),
        sort_keys=False,
        default_flow_style=False,
        allow_unicode=True,
    )
    path.write_text(text, encoding="utf-8")
    return path


def response_filename(
    key: str, *, report_number: int | None = None, ordinal: int = 1
) -> str:
    """The response-file stem for one administration (no uniquifying suffix).

    A survey auto-opened with a dream report is named after that report
    (``report-02-survey-dlq``) so it sorts beside its ``report-02.wav``;
    a standalone administration gets its own sequence (``survey-01-dlq``).
    """
    if report_number is not None:
        return f"report-{report_number:02d}-survey-{key}"
    return f"survey-{ordinal:02d}-{key}"


_STANDALONE_STEM_RE = re.compile(r"survey-(\d+)-")


def next_response_ordinal(directory: str | Path) -> int:
    """The next free standalone-survey number in a run folder.

    Derived from the files actually present (one past the highest
    ``survey-NN-…json``), so it needs no in-memory counter and stays correct
    across overlapping windows. A missing directory starts at 1.
    """
    highest = 0
    directory = Path(directory)
    if directory.is_dir():
        for path in directory.glob("survey-*.json"):
            match = _STANDALONE_STEM_RE.match(path.name)
            if match:
                highest = max(highest, int(match.group(1)))
    return highest + 1


def unique_response_path(directory: str | Path, stem: str) -> Path:
    """Return ``<directory>/<stem>.json``, suffixed ``-2``, ``-3``, … if taken.

    A report-attached stem repeats when the same survey is opened twice for one
    report (e.g. reopened after a mis-close); the suffix keeps both submissions.
    """
    directory = Path(directory)
    path = directory / f"{stem}.json"
    counter = 2
    while path.exists():
        path = directory / f"{stem}-{counter}.json"
        counter += 1
    return path


def _response_label(survey: SurveyDef, item: SurveyItem, value: Any) -> str:
    """The human label for a response value (the anchor / chosen option text)."""
    if value is None:
        return ""
    if item.type == LIKERT and isinstance(value, int):
        return survey.anchor_for(value)
    if item.type == SELECT and isinstance(value, int):
        return item.level_label(value)
    return ""


def response_payload(
    survey: SurveyDef,
    responses: list[Any],
    *,
    metadata: dict | None = None,
    opened: datetime | None = None,
    submitted: datetime | None = None,
    elapsed: timedelta | None = None,
    report_number: int | None = None,
    notes: str = "",
) -> dict[str, Any]:
    """Build the JSON-ready payload for one submitted administration.

    ``responses`` holds one value (or None for unanswered) per *responding* item
    — headings are display-only and excluded — in item order. Each entry records
    the item's text, ``type``, ``response`` value, and a human ``label`` (the
    Likert anchor or the chosen ``select`` option), so the file stands alone; the
    survey's content version and the report linkage are carried too so neither
    depends on the other.
    """
    metadata = metadata or {}
    return {
        "kind": RESPONSE_KIND,
        "smacc_version": VERSION,
        "survey": {
            "key": survey.key,
            "name": survey.name,
            "title": survey.title,
            "version": survey.version,
            "builtin": survey.builtin,
        },
        "subject": metadata.get("subject", ""),
        "session": metadata.get("session", ""),
        "report_number": report_number,
        "opened": opened.isoformat(timespec="seconds") if opened else None,
        "submitted": submitted.isoformat(timespec="seconds") if submitted else None,
        "time_since_recording_start": (
            format_elapsed(elapsed) if elapsed is not None else None
        ),
        "scale": {
            "min": survey.scale_min,
            "max": survey.scale_max,
            "anchors": list(survey.anchors),
        },
        "responses": [
            {
                "item": item.text,
                "type": item.type,
                "response": value,
                "label": _response_label(survey, item, value),
            }
            for item, value in zip(survey.response_items, responses, strict=True)
        ],
        "notes": notes.strip(),
    }
