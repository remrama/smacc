# BIDS export (`events.tsv` + sidecar) {#chap-reference-bids-export}

SMACC can convert a session [log](session-log.md#chap-reference-session-log) into a
[BIDS](https://bids.neuroimaging.io/) events file — a tab-separated `events.tsv` plus
a JSON sidecar describing its columns. Export one from the **Analyzer** with its
**Export events (BIDS)…** button. Only event-marker lines (`" - portcode N"`) become
rows.

## `events.tsv`

Tab-separated, one header row plus one row per marker:

```text
onset	duration	trial_type	value
5.5	n/a	Lights off	47
1810.25	n/a	REM detected	41
```

| Column       | Type             | Meaning                                                                |
| ------------ | ---------------- | ---------------------------------------------------------------------- |
| `onset`      | seconds          | Time from the **first** parseable log line (the onset origin).         |
| `duration`   | seconds or `n/a` | `n/a` for instantaneous markers (all SMACC markers are instantaneous). |
| `trial_type` | string           | The event label, exactly as logged.                                    |
| `value`      | integer          | The event's port code (1–255).                                         |

## JSON sidecar

Written alongside as `<name>.json`, describing each column. `value` points back to the
log's [`event_codes`](settings-file.md#event_codes) block for the full code-to-event
map of that session:

```json
{
  "onset": {
    "Description": "Event onset relative to the first log entry.",
    "Units": "second"
  },
  "duration": {
    "Description": "Event duration; 'n/a' for instantaneous markers.",
    "Units": "second"
  },
  "trial_type": {
    "Description": "Event label as logged by SMACC."
  },
  "value": {
    "Description": "SMACC event-marker port code. The full code-to-event map for the session is recorded in its .log settings block (under event_codes)."
  }
}
```
