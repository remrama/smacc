# Preferences file (`preferences.yaml`)

`preferences.yaml` holds **per-machine operator preferences** — where each window was
last placed, the Launcher's recent-files list, the live log-preview options, and the
EEG Annotator's per-machine state (recent labels, last-used folders, rater id,
quick-mark palette). It is the machine layer, kept
separate from a portable [SMACC file](settings-file.md) (which a researcher shares
between rigs) and from a per-run [session log](session-log.md).

It lives in the SMACC directory (`$SMACC_DIRECTORY`, else `~/SMACC/preferences.yaml`),
is loaded at startup, and is written on quit. It must never break the app: a missing
or corrupt file falls back to the built-in defaults, and saving swallows errors.

## Example

```yaml
kind: smacc/preferences
schema_version: 1
preferences:
  windows:
    launcher: {x: 100, y: 100, w: 340, h: 360}
    main: {x: 120, y: 80, w: 900, h: 700}
  recent_settings:
    - C:\Users\you\SMACC\peter.smacc
    - C:\Users\you\SMACC\paul.smacc
  last_settings: C:\Users\you\SMACC\peter.smacc
  log_preview_max_lines: 1000
  log_preview_clock: 24h
  eeg_palette_labels: [LRLR, LRLRx2, LRLRx3, IEIE]
```

## Fields

| Key              | Type    | Meaning                                                                                    |
| ---------------- | ------- | ------------------------------------------------------------------------------------------ |
| `kind`           | string  | Always `smacc/preferences`; a file with a different `kind` is ignored (defaults are used). |
| `schema_version` | integer | The preferences schema version (currently **1**).                                          |
| `preferences`    | mapping | The preferences themselves (below).                                                        |

### `preferences`

| Key                     | Type           | Meaning                                                                                                                                                                                                                                                                                                                |
| ----------------------- | -------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `windows`               | mapping        | Per-window geometry, keyed by a stable window id → `{x, y, w, h}`. Ids include `launcher`, `main` (the Session window), `analyze` (the Analyzer), `eeg-annotator` (the EEG Annotator), and one entry per tool window (keyed by its panel key). An absent/`null` `x`/`y` means "no saved position — open at a default". |
| `recent_settings`       | list of paths  | Recently opened `.smacc` files, most-recent first, de-duplicated and capped at 8.                                                                                                                                                                                                                                      |
| `last_settings`         | path or `null` | The last `.smacc` opened, used to preselect it in the Session…/Editor… file picker.                                                                                                                                                                                                                                    |
| `log_preview_max_lines` | integer        | How many lines the Session window's live log preview keeps (default **1000**); the oldest lines are dropped first. The log *file* always records everything, so nothing is lost. Very large values cost GUI memory and repaint time over an overnight session.                                                         |
| `log_preview_clock`     | string         | How the live preview renders the time of day: `24h` (default, e.g. `22:14:01`) or `12h` (`10:14:01 PM`). Presentation only — the log *file* always keeps 24-hour timestamps with a UTC offset. Toggle it from the Session window's **File → 12-hour clock**; an unknown value falls back to `24h`.                     |

!!! note "Partial files are fine"

    Loading merges a file's keys over the defaults, so a file missing some keys still
    yields every key. There is no cross-version migration; only `schema_version: 1`
    is current.

### EEG Annotator keys

The [EEG Annotator](../eeg-annotator.md) runs as its own process but writes its
per-machine state into the same `preferences.yaml`:

| Key                    | Type             | Meaning                                                      |
| ---------------------- | ---------------- | ------------------------------------------------------------ |
| `eeg_recent_labels`    | list             | Recent annotation labels, seeding the label dialog.          |
| `eeg_rater_id`         | string or `null` | The active rater id for per-rater sidecars.                  |
| `eeg_palette_labels`   | list             | Quick-mark palette (default `[LRLR, LRLRx2, LRLRx3, IEIE]`). |
| `eeg_last_dir`         | path or `null`   | Last folder a recording was opened from.                     |
| `eeg_last_profile_dir` | path or `null`   | Last view-profile folder.                                    |
| `eeg_last_export_dir`  | path or `null`   | Last figure-export folder.                                   |
| `eeg_last_blind_dir`   | path or `null`   | Last blind-config folder.                                    |

## Version history

| Version | Changes                                                                                                                                                                                                                                                                                                                       |
| ------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1       | First (and current) stable schema, covering window geometry, recents/last-used, the log-preview options, and the EEG Annotator keys. (The pre-release `association_prompted` key was dropped along with the first-run association prompt — the installer owns the association now; a leftover key in an old file is ignored.) |
