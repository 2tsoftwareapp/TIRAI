---
name: tirai-evidence
description: Record test evidence videos from a written test scenario. Drives a real browser with Tencent BrowserSkill (bsk), checks the database through DBX web in a second tab, draws Snagit-style boxes/arrows/labels on the page, and composes one MP4 with subtitles and a step report using ffmpeg. Use when the user wants an evidence video, a recorded test run, "quay evidence", or step-by-step proof of a UI + DB behaviour.
---

# TIRAI evidence recording

Workflow: **scenario → dry-run → record → compose**. Never record before the dry-run passes.

## 0. Check the environment (once per machine)

```bash
tirai doctor            # if tirai is missing or a check fails: see references/setup.md
tirai setup --yes       # installs ffmpeg, BrowserSkill CLI and skills for this OS
```

All required checks must be `ok`. Works on macOS, Linux and Windows; follow
[references/setup.md](references/setup.md). The user installs the browser extension themselves;
never use `sudo` without asking.

## 1. Write the scenario with the user

Start from `tirai init scenarios/<name>.yaml` and fill it in. One step = one thing to prove:

```yaml
- id: S2
  tab: app                       # which browser tab (declared under tabs:)
  title: Invalid email format
  subtitle: "Step 2: enter a malformed email -> validation error"
  actions:                       # what to do
    - fill: { selector: "#email", value: "alice-at-demo.local" }
    - click: "button[type=submit]"
  expect:                        # what must be true (required)
    - text_contains: { selector: ".error", text: "Email format is invalid." }
  annotate:                      # what to draw once expectations are checked
    - box: { target: "#email" }
    - arrow: { target: ".error", from: right, label: "Validation error" }
```

- Full vocabulary (actions, expect, DB tabs, databases): [references/scenario.md](references/scenario.md).
- Annotation shapes, targets and animation: [references/annotations.md](references/annotations.md).
- Find selectors with `bsk open <url>` / `bsk snapshot` before writing them; do not guess. Or let the user click
  the flow once: `tirai capture <url> -o <file>` writes the scenario from a `bsk record` trace.
- Repeated flows: `include:` shared steps, `cases:`/`matrix:` for data, `save:` to reuse on-screen values as `{{name}}`.
- Video: `zoom: <selector>` on a step, `layout: split` to show UI and DB side by side; `subtitle: {en, vi}` + `--lang`.
- Real data on screen: add `privacy: { mask: [email, phone, card, token] }` (and `keep:` for the record under test).
- Secrets go in `${ENV_VAR}` only. Put values in a git-ignored `.env` next to the scenario
  (loaded automatically, or pass `--env-file`); never write values into the scenario.
- DB checks must use a **read-only** database user.

Then `tirai validate <file>` and fix every reported problem.

## 2. Dry-run (no video)

```bash
tirai run <file> --dry-run
```

Read the failing step's `expect ... -> actual ...` line and `evidence/dry-run/step-<id>.png`.
Fix the scenario (selector, wait, data) or report the product bug to the user. Repeat until all steps pass.

## 3. Record + compose

```bash
tirai record <file>            # dry-run again, record, then compose
```

Outputs in `evidence/record/`: `final.mp4`, `subtitles.srt`, `report.md`, `report.html`, `report.xlsx`,
`timeline.final.json`, `manifest.sha256`, per-tab `seg-*.mp4` and `step-*.png`. To document a bug, record the
failing run with `tirai record <file> --record-failures` (stops after the first failing step, FAIL in the header). Re-compose without re-recording: `tirai compose evidence/record/timeline.json`.

## 4. Hand over

Give the user `final.mp4`, `report.html` (or `report.xlsx`) and `manifest.sha256`; `tirai verify` proves the files are unchanged. Check a few frames first
(`ffmpeg -ss <t> -i final.mp4 -frames:v 1 frame.png`) to confirm annotations and subtitles are visible.

## Ad-hoc annotation (outside a scenario)

`tirai annotate-js` prints the path of `annotate.js`. Inject it with
`bsk evaluate "$(cat <path>);__ann.arrow('#email',{label:'here'})" --unverified`, clear with `__ann.clear()`.
