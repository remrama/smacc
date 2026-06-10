# Surveys

After an awakening, a dream report is often followed by a questionnaire — how
lucid was the dream, what did it contain, how confident is the participant. SMACC
handles these two ways:

* **In-app surveys** render in a SMACC window and save their responses straight
  into the run folder, next to the dream-report WAV they accompany. SMACC ships
  the standard lucid-dreaming instruments, and you can build your own.
* **Web surveys** (e.g. a questionnaire hosted on Qualtrics or REDCap) open in
  the browser, exactly as before — add them by URL.

In-app surveys exist because the night shift is a bad place for a hosted form:
sleep labs are often offline, response data belongs with the night's recording
(not in a third-party account), and overnight questionnaires are frequently
administered *verbally over the intercom* — the participant stays in bed, in the
dark, while the experimenter reads the items and records the answers. The survey
window is non-modal for the same reason: the intercom stays reachable while it is
open.

## Built-in surveys

SMACC bundles standard instruments from the dream and mindfulness literatures
(where a survey's definition carries a citation, it is shown at the top of its
window):

**Dreaming & lucidity**

| Survey | Full name |
|---|---|
| **DLQ** | Dream Lucidity Questionnaire |
| **LuCiD** | Lucidity and Consciousness in Dreams scale |
| **LUSK** | Lucid Dreaming Skills Questionnaire |
| **MUSK** | Morning Lucid Dreaming Skills Questionnaire |
| **BLA** | Baseline Lucidity Assessment |
| **MLA** | Morning Lucidity Assessment |

**Mindfulness**

| Survey | Full name |
|---|---|
| **CAMSR** | Cognitive and Affective Mindfulness Scale - Revised |
| **FFMQ** | Five Facet Mindfulness Questionnaire |
| **FMI** | Freiburg Mindfulness Inventory |
| **KIMS** | Kentucky Inventory of Mindfulness Skills |
| **MAAS** | Mindfulness Attention Awareness Scale |
| **MACE** | Metacognition, Affect, Cognitive Experiences Questionnaire |
| **PHLMS** | Philadelphia Mindfulness Scale |
| **SMAAS** | State Mindfulness Attention Awareness Scale |
| **SMS** | State Mindfulness Scale |
| **TMS** | Toronto Mindfulness Scale |

Built-ins ship with SMACC itself (they are not stored in your `.smacc` study
file), so updates reach every install. Each survey definition carries a content
`version` that is recorded in every response file — an analysis can always tell
which wording a given night used.

## Using a survey

The survey dropdown in the **Dream recording** panel lists the in-app surveys
first, then your saved web URLs. Pick one to open it automatically when a dream
report starts recording; that administration is *attached* to the report, and its
response file is named after it. Any survey can also be opened standalone from
**File › Surveys**.

Every open logs a `SurveyOpened` event. Submitting an in-app survey writes the
response file and logs a `SurveySubmitted` event (code 71) — log-only by default,
since the survey happens after the awakening; flip its **Trigger** checkbox in
the Event codes dialog if your protocol wants it in the trigger channel.

In the study designer (and the read-only previews in the Manage dialog) a survey
renders but cannot be submitted — there is no run folder to save into.

## Response files

One JSON file per administration, in the run folder:

* `report-02-survey-dlq.json` — auto-opened with dream report 2 (sorts beside
  `report-02.wav`).
* `survey-01-lusk.json` — opened standalone; standalone administrations are
  numbered in their own sequence.

The payload records the survey's key, title, and content version, the optional
subject/session metadata, opened/submitted timestamps, the time since the
**Start recording** marker (like the dream-report stamp), the linked report
number (or `null`), the scale with its anchors, one `{item, response, anchor}`
entry per item (unanswered items are `null`; submitting warns first), and any
free-text notes:

```json
{
  "kind": "smacc/survey-response",
  "survey": {"key": "dlq", "version": "1.0", "...": "..."},
  "report_number": 2,
  "time_since_recording_start": "02:14:09",
  "responses": [
    {"item": "…", "response": 3, "anchor": "…"}
  ]
}
```

Scoring is deliberately left to analysis: SMACC records raw per-item responses
only, so scoring conventions can never silently drift between studies.

## Building your own

The **Manage…** button next to the survey dropdown manages all three kinds of
entries: view a built-in, build/edit/remove your own, or add a web URL.

**Build survey…** creates a custom in-app survey: a name, optional
title/citation/instructions, one shared rating scale (its range plus an optional
anchor label per point), and the items, one per line. That single-scale shape is
deliberate — it matches the bundled instruments and keeps definitions simple.
Custom surveys are saved as YAML files in your SMACC folder's `surveys/`
directory (`~/SMACC/surveys/` by default) — *not* in the `.smacc` study file —
and load alongside the built-ins on every launch. Bump the **Version** field
whenever you change the items.

The files are hand-editable (same format as the bundled ones):

```yaml
kind: smacc/survey
schema_version: 1
key: my-survey          # stable id; names the response files
name: MySurvey          # short label shown in the dropdown
title: My Survey's Full Title
version: "1.0"          # recorded in every response
citation: ""
instructions: "Rate each statement about the dream you just reported."
scale:
  min: 0
  max: 4
  anchors: [Not at all, Just a little, Moderately, Pretty much, Very much]
items:
  - I was aware that I was dreaming.
  - ...
```

Web survey URLs, by contrast, are saved in the `.smacc` study file
(`survey_options`) and travel with the study — see the
[settings-file reference](reference/settings-file.md).
