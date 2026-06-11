# File formats

SMACC reads and writes a handful of files. This section is the **reference** for
each one — its on-disk shape, every field, and how it is versioned — as distinct
from the task-oriented [Usage](../usage.md) guide.

| File                                            | What it is                             | Format     | Version              |
| ----------------------------------------------- | -------------------------------------- | ---------- | -------------------- |
| [SMACC file (`.smacc`)](settings-file.md)       | A portable study configuration         | YAML       | `schema_version: 1`  |
| [`preferences.yaml`](preferences-file.md)       | Per-machine operator preferences       | YAML       | `schema_version: 1`  |
| [Session `.log`](session-log.md)                | The per-run record (events + settings) | Text       | —                    |
| [BIDS export](bids-export.md)                   | `events.tsv` + JSON sidecar            | TSV / JSON | follows BIDS         |
| [Survey definition](../surveys.md)              | An in-app survey (built-in or custom)  | YAML       | `schema_version: 1`  |
| [Survey response](../surveys.md#response-files) | One administration's answers           | JSON       | —                    |
| [Annotations sidecar](annotations-file.md)      | EEG review marks (`*.annotations.tsv`) | TSV / JSON | follows BIDS columns |

## Where each file lives

- The **SMACC directory** (`$SMACC_DIRECTORY`, else `~/SMACC`) holds `preferences.yaml`,
    the seeded `default.smacc`, and the default data directory.
- A **`.smacc`** can live anywhere; it names the **data directory** its runs are
    written to.
- Each **run** gets its own timestamped folder (`smacc-YYYYmmdd-HHMMSS/`) under that
    data directory, holding the session `.log`, any dream-report audio, survey
    responses, and exports.
- **Custom survey definitions** live in the SMACC directory's `surveys/` folder;
    built-in ones ship inside SMACC itself.
- **Bundled assets refresh on upgrade.** `default.smacc` (a read-only template) and
    the `demo-` cues are re-seeded from the bundle when they change, so a newer
    SMACC's improvements reach an existing directory; your own files are untouched.
    Biocal voice recordings are read straight from the bundle, with the SMACC
    directory's `biocals/` folder as an optional per-recording override.

## Stability promise

`.smacc` and `preferences.yaml` each carry an integer `schema_version`, currently
**1** — the first stable release schema. SMACC loads only the current version; it
does **not** migrate older or unknown versions. Missing *optional* keys are always
tolerated (each falls back to a default), so a partial or hand-edited file still
loads.

The format will not change incompatibly without **bumping `schema_version`** and
adding a row to that file's version-history table. The `kind` discriminator
(`smacc/settings`, `smacc/preferences`) lets SMACC reject files that aren't its own.
