# Preferences file (`preferences.yaml`)

`preferences.yaml` holds **per-machine operator preferences** — where each window was
last placed and the launcher's recent-files list. It is the machine layer, kept
separate from a portable [`.smacc` study](settings-file.md) (which a researcher shares
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
  association_prompted: true
  recent_settings:
    - C:\Users\you\SMACC\peter.smacc
    - C:\Users\you\SMACC\paul.smacc
  last_settings: C:\Users\you\SMACC\peter.smacc
```

## Fields

| Key | Type | Meaning |
|---|---|---|
| `kind` | string | Always `smacc/preferences`; a file with a different `kind` is ignored (defaults are used). |
| `schema_version` | integer | The preferences schema version (currently **1**). |
| `preferences` | mapping | The preferences themselves (below). |

### `preferences`

| Key | Type | Meaning |
|---|---|---|
| `windows` | mapping | Per-window geometry, keyed by a stable window id → `{x, y, w, h}`. Ids include `launcher`, `main` (the session window), the analyze window, and each tool window. An absent/`null` `x`/`y` means "no saved position — open at a default". |
| `association_prompted` | boolean | Whether the first-run "associate `.smacc` files (Windows)?" prompt has already been shown. |
| `recent_settings` | list of paths | Recently opened `.smacc` files, most-recent first, de-duplicated and capped at 8. |
| `last_settings` | path or `null` | The last `.smacc` opened, so the launcher can preselect it. |

!!! note "Partial files are fine"
    Loading merges a file's keys over the defaults, so a file missing some keys still
    yields every key. There is no cross-version migration; only `schema_version: 1`
    is current.

## Version history

| Version | Changes |
|---|---|
| 1 | First stable schema: `windows`, `association_prompted`, `recent_settings`, `last_settings`. |
