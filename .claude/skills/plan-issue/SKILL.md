---
name: plan-issue
description: Plan a GitHub issue before any code. Fetches the issue and all comments, reads the relevant code, pulls in the matching domain skill, and produces a careful implementation plan with your own expert opinions and open questions — for the user to evaluate, not to implement immediately. Use when the user runs /plan-issue <number> or asks to review an issue and make a plan.
argument-hint: "[issue-number]"
---

# Plan a GitHub issue

Turn a GitHub issue into a careful, opinionated implementation plan the user can
evaluate — **without writing code yet**. The argument is the issue number (e.g.
`/plan-issue 28`).

## Steps

1. **Read the whole issue.** Use the `gh` skill:

   ```sh
   gh issue view <N> --json number,title,body,labels,milestone,comments
   ```

   Read the body *and every comment* — in this repo the owner's follow-up comments
   usually carry the real constraints (which hardware is required, pulsed vs held,
   …), not just the original post.

1. **Understand the code.** Find and **read** the modules the change touches; trace
   the integration points and existing contracts (data shapes, persisted settings,
   tests). Don't plan against a guess — open the files.

1. **Load the domain context.** Pull in the relevant skill so the plan reflects
   reality, not just the ticket:

   - **portcodes** — triggers, markers, `events.py`, trigger hardware.
   - **audio-routing** — devices, routing, streams, volume.
   - **dream-engineering** — the research use-case, timing, night-time UX.

1. **Write the plan.** Structure it:

   - **Problem** — what's actually being asked, in your own words.
   - **Approach** — the recommended design, plus alternatives you considered and
     rejected (and why).
   - **Changes** — concrete and file-by-file: what's added/edited, new
     settings/contracts, migrations.
   - **Risks & trade-offs** — what could break; compatibility with existing
     data/markers; performance and timing.
   - **Your opinions** — add genuine expertise: what you'd do differently, what the
     issue under- or over-specifies, what to cut. Don't just restate the issue.
   - **Open questions** — anything needing the user's or the lab's input *before*
     building (hardware specifics, protocol choices). Surface these clearly.
   - **Verification** — how it'll be tested, including what can only be validated on
     real hardware.

1. **Present for evaluation. Do not start implementing.** Wait for the user to react.

## Conventions

- Use `uv` for any commands you run (never naked `python`/`pip`).
- When work is later approved, follow the repo's commit and PR style in
  `docs/contributing.md` ("Commit and pull-request style"): one-line
  Conventional-Commits subjects, brief PR bodies, no AI attribution.
- This repo asks contributors to open an issue before building, so planning *from*
  an issue fits the flow.
