# Troubleshooting {#chap-troubleshooting}

When something goes wrong, start here. Most fixes live on the relevant tool's page;
this page collects the cross-cutting ones and points to the rest.

## Common problems

| Symptom                                                                     | Where to look                                                                                                      |
| --------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------ |
| Windows SmartScreen blocks the download or installer                        | [Installation](installation.md#chap-installation) — expected for the unsigned build; **More info → Run anyway**    |
| "No output/input device found", or a bound device shows **(not connected)** | [Audio routing](audio.md#no-system-default) — rebind in the Devices window and **Refresh devices (F5)**            |
| A cue plays in the control room but maybe not the bedroom                   | [Audio cues](audio-cues.md#is-the-cue-reaching-the-bedroom) — read the *Sending* and *Bedroom* meters              |
| The BlinkStick isn't listed, or a light won't fire or stays on              | [Visual cues](visual.md#troubleshooting)                                                                           |
| The Hue bridge stopped responding                                           | [Visual cues](visual.md#troubleshooting) — its IP probably changed                                                 |
| Triggers don't register on the amplifier                                    | [Markers & port codes](triggers.md#chap-triggers) — check the COM port, baud rate, and pulsed-vs-set-and-hold mode |
| A cue is too loud or too quiet                                              | [Volume & latency](latency.md#chap-latency) — the per-cue volume, the safety cap, and the OS stages                |

## If SMACC crashes

Separately from the per-run logs, SMACC keeps a permanent crash log at
`~/SMACC/logs/crash.log`. Uncaught errors, Qt's own fatal messages, and — via
Python's `faulthandler` — the stack of every thread at a hard crash (such as an
access violation inside Qt or an audio driver) are appended there, even when no
session is running. A hard-crash dump shows where the *Python* side was at that
moment, which is usually enough to identify the failing subsystem. Every launch and
every session start is also stamped in the file, so a crash can be matched to its
night and run folder.

The file is rotated at launch once it grows large (one older `crash.log.1`
generation is kept). When SMACC crashes it shows a dialog with an **Open logs
folder** button that takes you straight to it.

## Reporting a problem

Open an issue on the [SMACC issue tracker](https://github.com/remrama/smacc/issues)
with what you did, what happened, and the relevant files: `crash.log` together with
the affected run's folder, or a session [`.log`](reference/session-log.md#chap-reference-session-log).
