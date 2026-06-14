# Annotations sidecar

The [EEG Annotator](../eeg-annotator.md) saves annotations as a **TSV + JSON
sidecar pair** next to the source recording, which is never modified:

```
night1.edf
night1.annotations.tsv    ← the annotations
night1.annotations.json   ← column documentation + provenance
```

The pair is named by replacing the recording's extension with
`.annotations.tsv` / `.annotations.json`. It is deliberately **not** BIDS's
`_events.tsv` name: opening a recording that lives inside a BIDS dataset must
never clobber the dataset's own events file. The columns themselves follow the
BIDS/MNE convention, so downstream tooling reads them with no surprises.

## The TSV

Tab-separated, UTF-8, one header row, sorted by onset:

```
onset	duration	description
12.345	0.000	LRLR
80.500	22.000	Arousal
```

| Column        | Meaning                                                                                    |
| ------------- | ------------------------------------------------------------------------------------------ |
| `onset`       | Seconds from the start of the recording's **data** (not clock time), millisecond precision |
| `duration`    | Seconds; `0.000` marks an instantaneous event                                              |
| `description` | The label as entered by the reviewer                                                       |

Overlapping annotations are allowed (an arousal inside a REM period is two
rows). A label containing a double quote is csv-quoted (`"saw a ""light"""`);
tabs/newlines never appear inside fields — labels are whitespace-normalized
when created.

The file is hand-editable: the reader accepts Windows line endings and a
UTF-8 BOM (e.g. a Notepad re-save), but it is strict about the header and the
column count, so a corrupted file is reported instead of silently losing rows.

## The JSON

Documents each column (BIDS-style) and records provenance:

```json
{
  "onset": {"Description": "Annotation onset relative to the start of the recording's data.", "Units": "second"},
  "duration": {"Description": "Annotation duration; 0 for an instantaneous mark.", "Units": "second"},
  "description": {"Description": "Annotation label as entered by the reviewer."},
  "SourceFile": "night1.edf",
  "MeasurementDate": "2026-06-05T22:00:00+00:00",
  "Rater": null,
  "GeneratedBy": {"Name": "SMACC", "Version": "1.0.0"}
}
```

`MeasurementDate` is the recording's start as stored in the file — combined
with the data-relative onsets it reconstructs clock time. It is `null` when
the format or anonymization dropped it. `Rater` names the reviewer for a
per-rater sidecar (see below) and is `null` for an ordinary single-rater review.

## Multiple raters

Objective signal scoring often uses several reviewers. Give each a **rater id**
— from the Rater button, or by launching with `--rater <id>` — and that
reviewer's annotations save to a sidecar keyed by the id, so several raters can
score one recording without overwriting each other:

```
night1.annotations.tsv          ← single-rater review (no id)
night1.annotations.alice.tsv    ← rater "alice"
night1.annotations.bob.tsv      ← rater "bob"
```

Each rater writes a different path, so cross-rater clobbering is impossible and
the coordinator's marks in the plain `night1.annotations.tsv` stay untouched.
The id is reduced to a filesystem-safe token (letters, digits, dash,
underscore), and each rater gets their own crash-recovery autosave
(`night1.annotations.alice.autosave.tsv`). Downstream analysis attributes and
compares marks by reading the JSON `Rater` field.

## Precedence

When a recording is opened, an existing sidecar **wins**: it is loaded as-is,
and the events embedded inside the recording are *not* (re)imported — they
were already captured the first time the file was reviewed. Delete or rename
the sidecar to start a review from scratch.
