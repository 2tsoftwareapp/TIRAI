---
name: tirai-evidence
description: Record test evidence videos from a written test scenario. Drives Chrome with vercel-labs agent-browser (default) or Tencent BrowserSkill (bsk), checks the database through DBX web in a second tab, draws Snagit-style boxes/arrows/labels on the page, and composes one MP4 with subtitles and a step report using ffmpeg. Use when the user wants an evidence video, a recorded test run, "quay evidence", or step-by-step proof of a UI + DB behaviour.
---

# TIRAI evidence recording

Workflow: **scenario → dry-run → record → compose**. Never record before the dry-run passes.

## 0. Check the environment (once per machine)

```bash
tirai doctor            # if tirai is missing or a check fails: see references/setup.md
tirai setup --yes       # installs ffmpeg >= 6, agent-browser, DBX web, BrowserSkill CLI, skills
tirai dbx -d            # start DBX web (http://127.0.0.1:4224) when the scenario has a db tab
```

All required checks must be `ok`. Works on macOS, Linux and Windows; follow
[references/setup.md](references/setup.md). The default driver needs no extension; only `driver: bsk` needs the user to install the BrowserSkill extension;
never use `sudo` without asking.

## 1. Plan & write the scenario (Step-by-Step Evidence Methodology)

### 1a. Test Plan & YAML Completeness Standard (Never skip steps or fields)

Before writing YAML, produce a **complete, step-by-step Test Plan** and get user approval — then map it **1-to-1** into the scenario YAML with zero silent omissions:

1. **Full upstream → target → downstream chain:** cover the real user journey end-to-end (e.g., upstream input/creation screen → processing/update screen → print/export/search screen → DB verification), instead of skipping upstream creation or assuming magic pre-existing data.
2. **Field-by-field & case-by-case matrix:** explicitly list **every** input field, filter/search criterion, business state/branch, boundary/validation/edge case, and **every** output field (UI columns, DB columns, PDF/Excel/CSV cells, totals, pagination/page breaks) that must be verified. Never summarize as "fill form" or "check result".
3. **Detailed step breakdown in the plan:** for every video/scenario, list numbered steps with:
   `Step ID | Screen / Tab | Exact Input Data | Atomic User Actions | Exact Expected Assertions (UI / DB / File)`.
4. **1-to-1 YAML expansion (no collapsed steps or spot-check-only assertions):**
   - Every navigation click, modal open/fill/confirm, search, edit, toast/dialog check, download, and DB check must be an explicit step/action in the YAML.
   - Every interactive field gets its own action (`clear`/`fill`/`select`/`click`/`press`) with a clear `label:`.
   - Every planned field/column/cell/state gets its own `expect:` entry with a clear `label:` (UI `text_contains`/`value`/`visible`, DB `db_assert`/DBX query, and downloaded file checks) so the live `EXPECTATIONS` HUD proves 100% of the plan.
   - If a planned check cannot be automated or is out of scope, state it explicitly to the user before dry-run — never silently drop it from the YAML.

### 1b. Scenario Authoring (Visual Narration & Locators)

Start from `tirai init scenarios/<name>.yaml` and fill it in. Follow the **step-by-step action + per-expect evidence standard**:

1. **Always turn on step-by-step visual narration in `settings:`** so the viewer sees *every* click, edit, keypress, and verification live:
   - `pace: human` — smooth 60fps virtual cursor glide, click ripples, and progressive typing.
   - `camera: action` — automatically zooms in and pans smoothly from each action target (`click`, `fill`, `clear`, `select`, `press`, `download`) to the next, then eases back out to full view when expectations & results appear (pure verification/DB steps with `annotate:` still zoom into their annotations).
   - `action_annotate: true` — draws a live callout pill + highlight box on **every** interactive action so the viewer knows exactly what is being clicked, cleared, typed, or submitted.
   - `show_expects: true` — renders a live **EXPECTATIONS** checklist HUD card in the corner (`✓` PASS / `✗` FAIL + actual value on failure) and highlights each checked DOM target in green/red as each `expect:` runs one by one.
   - `spotlight: true` — subtly dims the surrounding page during callouts and final annotations.
2. **Write short, explicit `label:` on key actions and every `expect:`** in the user's language (e.g. Vietnamese/English) so the callout pills and per-expect checklist read like a real QA walkthrough rather than raw CSS selectors.
   - **Separate `subtitle:` (on-screen notes) from `voice:` (spoken narration):** keep `subtitle:` concise with exact screen IDs, field names, codes, and expected values (e.g. `AB03001 → AC03001: 得意先=010001`), and put natural, conversational spoken narration in a separate `voice:` field (100% in the viewer's language without raw kanji/symbols or repeating `subtitle:` word-for-word). `tirai compose --voice` speaks `voice:` when present and falls back to `subtitle:` if omitted.
3. **One step = one logical milestone** with explicit `expect:` checks AND final `annotate:` callouts on the resulting UI/DB/PDF/Excel state:

```yaml
settings:
  pace: human
  camera: action
  camera_factor: 1.35              # keep gentle (1.25–1.40) so form context stays readable
  action_annotate: true
  show_expects: true
  spotlight: true
  viewport: { width: 1600, height: 900 }

steps:
  - id: S2
    tab: app                       # which browser tab (declared under tabs:)
    title: Invalid email format
    subtitle: "Step 2: enter a malformed email -> validation error"
    actions:                       # each action gets live callout + smooth zoom
      - clear: { selector: "@email", label: "Clear old email" }
      - fill: { selector: "@email", value: "alice-at-demo.local", label: "Type invalid email" }
      - click: { selector: "@submit", label: "Click Submit" }
    expect:                        # each expect ticks off live in the EXPECTATIONS HUD
      - text_contains: { selector: "@error", text: "Email format is invalid.", label: "Validation error shown" }
      - attribute: { selector: "@email", name: "aria-invalid", equals: "true", label: "Email marked invalid" }
    annotate:                      # final result callouts (HUD stays visible alongside them)
      - box: { target: "@email", label: "Invalid input", color: "#dc2626" }
      - arrow: { target: "@error", from: right, label: "Error message", color: "#dc2626" }
```

- **Semantic color standard (never use red for passing/normal callouts):**
  - `#2563eb` (**Blue**, default `accent`): neutral focus, interactive actions, field pointers, document/sheet IDs.
  - `#16a34a` (**Green**, `pass_color`): verified results, confirmed values, PASS checks (`color: "#16a34a"` on success callouts).
  - `#d97706` (**Amber**): warnings, edge cases, notices (e.g., no-data warning, async queued notice).
  - `#dc2626` (**Red**, `fail_color`): **ONLY** for validation errors, product defects, failed expectations, or `--record-failures` bug evidence — never set `theme.accent` to red.

- Override per action when needed: `{ selector: "@x", label: "...", annotate: false, zoom: 1.8 }` (or `zoom: false` to skip zooming on a minor action).
- Override per step when needed: `action_annotate: false` or `show_expects: false` on dense setup/login steps.
- Full vocabulary (actions, expect, DB tabs, databases): [references/scenario.md](references/scenario.md).
- Annotation shapes, targets and animation: [references/annotations.md](references/annotations.md).
- Name elements once under `targets:` and use `@name` in actions/expect/annotate/zoom.
- **Locator priority & Preflight `id` / `data-testid` rule (for speed and stability):**
  1. **Prefer `data-testid` (`testid=...`) or stable `#id` first** — O(1) lookup, immune to label/language changes, and avoids slow full-DOM `role=`/`text=` scans. **During Preflight, if you have access to the app's source code (dev/staging), check key controls (action buttons, inputs, grid checkboxes/row edit buttons, modals, toasts) and recommend/ask the user to add stable `data-testid` or `id` attributes** if they are missing.
  2. **Second choice:** stable form names (`input[name=...]`, `select[name=...]`).
  3. **Last-resort fallback (production / black-box targets without source access):** run `tirai inspect <file>` (or `tirai inspect <url>`) to discover `role=`, `label=`, `text=` locators; never guess selectors.
  Or let the user click the flow once: `tirai capture <url> -o <file>` opens a browser; the user clicks the flow
  and closes the window.
- A failure ending in `nearby: …` lists the page's closest elements: fix the target from it. A `warning: target
  @x … used …` means a fallback locator was needed: update that target.
- Database tab: `dbx.connect: {name: ..., host: ...}` on the DBX tab creates the connection from `databases.default`
  (or run `tirai dbx-connect --dsn-env EV_DB_DSN --name <name>`); no manual DBX setup.
- Repeated flows: `include:` shared steps, `cases:`/`matrix:` for data, `for_each:` to repeat one step per item
  (N order lines), `once: last` for a step after the last case, `save:` to reuse on-screen values as `{{name}}`.
- Mark steps that create/change data with `writes: <what>` and undo them under `cleanup:`; a dry-run stops before
  them unless `--allow-writes`. Never dry-run writes repeatedly on a shared tenant without asking the user.
- Popups (`window.open`): declare a tab `{popup: true, match: "/path"}` and use it in the next step.
- Check a field before an action unmounts it with an inline `- expect: {...}` among the actions.
- Slow SPAs: `settings.expect_timeout: 15` or `wait_for: {idle: true}` instead of fixed `wait:`;
  `settings.viewport: {width: 1600, height: 900}` when forms do not fit.
- Selectors are CSS or TIRAI locators; Playwright syntax (`:has-text`, `>>`) does not work. Quote values that start
  with `${...}` or `{{...}}` inside `{ }`.
- Video: `camera: action` (or `zoom: <selector>` / `zoom: annotate`) on steps; `subtitle: {en, vi}` + `--lang`. **Do NOT use `layout: split`** (side-by-side UI + DB shrinks both panes and makes text unreadable; always record UI and DBX as separate full-screen steps with zoom + annotations).
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
`network:`/`console:` lines (e.g. a 401) mean the page had errors even if the step passed: check them, and use
`--fresh` to start without an old login.

Long flow: `--keep-session` once, then `--session <name> --from-step <id>` to rerun only the tail; `--until <id>`
stops early.

## 3. Record + compose

```bash
tirai record <file>            # dry-run again, record, then compose
```

Outputs in `evidence/record/`: `final.mp4`, `subtitles.srt`, `report.md`, `report.html`, `report.xlsx`,
`timeline.final.json`, `manifest.sha256`, per-tab `seg-*.mp4` and `step-*.png`. To document a bug, record the
failing run with `tirai record <file> --record-failures` (stops after the first failing step, FAIL in the header).
`--trim-still` fast-forwards long stretches where nothing changes. Re-compose without re-recording: `tirai compose evidence/record/timeline.json`.

Optional extras: `tirai compose evidence/record/timeline.json --voice` (spoken subtitles),
`tirai scan-pii evidence/record --fix` (OCR pass for PII drawn on canvas), `tirai sign evidence/record --key
~/.ssh/id_ed25519 [--tsa]` then `tirai verify evidence/record --pubkey ~/.ssh/id_ed25519.pub`,
`tirai export evidence/record --format junit xray testrail` (import files only, nothing is uploaded),
`tirai index evidence/ -o evidence/index.html` (one page for many runs).

To start from a written spec: `tirai from-spec login.feature --url <app url>` drafts the YAML (Gherkin, Markdown
or CSV tables); review every `TODO(...)` selector and the "not converted" lines with the user before recording.
Desktop apps: use a tab with `app:` (see docs/scenario-format.md, "Desktop apps").

## 4. Hand over

Give the user `final.mp4`, `report.html` (or `report.xlsx`) and `manifest.sha256`; `tirai verify` proves the files are unchanged. Check a few frames first
(`ffmpeg -ss <t> -i final.mp4 -frames:v 1 frame.png`) to confirm annotations and subtitles are visible.

## Ad-hoc annotation (outside a scenario)

`tirai annotate-js` prints the path of `annotate.js`. Inject it with
`agent-browser eval --stdin < <path>` then `agent-browser eval "__ann.arrow('#email',{label:'here'})"` (bsk: `bsk evaluate "$(cat <path>);..." --unverified`), clear with `__ann.clear()`.
