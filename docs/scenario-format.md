# Scenario reference

```yaml
name: "Login validation + DB verification"   # title card + report heading
tabs:                                         # first tab opens a fresh bsk session, others open as new tabs
  app: { url: "${APP_URL}", label: "WEB APP" }
  db:
    url: "${DBX_URL}"
    label: "DATABASE (DBX)"
    kind: dbx                                 # enables `sql:`
    setup:                                    # runs before recording starts
      - dbx_login: "${DBX_PASSWORD}"
databases:                                    # used by `expect: db`
  default: { dsn: "${EV_DB_DSN}" }            # postgresql:// | mysql:// | sqlite:///path
steps: [...]
```

## Step fields

| Field | Required | Meaning |
|---|---|---|
| `id` | yes | Unique step id (`S1`, `S2`, ...) |
| `tab` | yes | Tab name from `tabs:` (a tab with `popup: true` follows a window the page opened) |
| `title` | yes | Header bar text and report row |
| `subtitle` | no | Burned-in subtitle (defaults to `title`); a `{en: ..., vi: ...}` map for several languages |
| `actions` | no | Executed in order |
| `expect` | yes | All must pass for the step to pass (optional when an action is an inline `expect:`) |
| `annotate` | no | Drawn after expectations are checked |
| `hold` | no | Seconds the step stays on screen (default 2.5 recorded, 0.3 dry-run) |
| `zoom` | no | Selector (or `{target, factor, at}`) the video eases in on during this step |
| `layout` | no | `split`: show the previous step (or `split_with: <id>`) beside this one |
| `once` | no | With `cases:`/`matrix:`, run this step only for the first case (`once: last`: only after the last case) |
| `for_each` | no | Repeat this step once per item of a list (or the name of a list in `vars:`/the case); see [Loops](#loops-and-steps-that-run-once) |
| `save` | no | `{ name, selector, attribute?, pattern? }` (or a list): store a value after the actions, before `expect` |
| `writes` | no | `true` or a short text (`creates an order`): this step changes data; see [Steps that write data](#steps-that-write-data) |
| `include` | — | Instead of a step: `include: file.yaml` (+ `with:` vars, `prefix:` for ids) |

## Targets (`@name`)

Name each element once under `targets:` and use `@name` wherever a selector goes: actions, `expect`,
`annotate`, `zoom` and `privacy.selectors`. Each target lists locators tried in order. The first one that
matches **exactly one** element (visible elements win over hidden ones) is tagged in the page with
`data-tirai-id`, and the step addresses it through that attribute.

```yaml
targets:
  email: "#email"                          # the site's own id/test id when it has one
  password: label=Password
  submit:                                  # fallbacks, tried top to bottom
    - testid=login-submit
    - "#submit"
    - role=button[name="Sign in"]
  bob_row: { any: ["text*=bob@demo.local"], within: "#users", nth: 0 }
steps:
  - id: S1
    tab: app
    title: Log in
    actions:
      - fill: { selector: "@email", value: "${EMAIL}" }
      - click: "@submit"
    expect:
      - visible: "@bob_row"
    annotate:
      - box: "@submit"
```

| Locator | Matches |
|---|---|
| `#id`, `.class`, any CSS (or `css=…`) | `document.querySelectorAll` |
| `testid=x` | `data-testid`, `data-test-id`, `data-test`, `data-qa`, `data-cy` equal to `x` |
| `role=button[name="Save"]` | role (`textbox`, `button`, `link`, `combobox`, `checkbox`, `radio`, `heading`, `tab`, `menuitem`, `option`, `cell`, `row`, `dialog`, `img`, or any ARIA role) + exact accessible name; `role=dialog` alone = any |
| `label=Email` | form field whose label (`<label>`, `aria-label`, `aria-labelledby`) is exactly `Email` |
| `placeholder=Search` | element with that placeholder |
| `text=Total` / `text*=Total` | innermost element whose text equals / contains the value |

- `within: <css>` limits the search to one container; `nth: <n>` picks the n-th match (0-based) on purpose.
- A locator can also be written inline: `click: role=button[name="Sign in"]` works without a `targets:` entry.
- **No guessing:** 0 or 2+ matches for every locator fails the step and lists what each locator matched,
  for example `target @save: no locator matched exactly one element (role=button[name="Save"]: 2 [button in form#a, button in form#b])`.
- **Fallback used:** when an earlier locator stops matching and a later one finds the element, the step still
  passes, prints `warning: target @submit: #submit: 0 -> used 'role=button[name="Sign in"]'; update the target`,
  and stores it under `warnings` in `timeline.json`.
- Tags are kept in sync while the page re-renders (SPA) and are re-applied after navigation. The page only gains
  the `data-tirai-id` attribute; nothing visible changes.
- A selector that matches nothing (plain CSS or a target) ends with `; nearby: #email (textbox "Email")`
  suggestions taken from the current page.
- Browser tabs only; desktop (`app:`) tabs keep their agent-desktop selectors.

`tirai inspect <scenario>` dry-runs the flow and, after every step, writes `<out>/inspect/<step>.md` (each
element's role, name and unique locators, preferred first) and one `<out>/inspect/targets.yaml` with a
ready-to-paste `targets:` block for every page reached, including pages after login. It prefers test ids and
stable ids/names, skips ids that look generated, and leaves out elements with no unique locator.
`tirai inspect <url>` does the same for a single page.

## Actions

| Action | Example |
|---|---|
| `navigate` | `navigate: ${APP_URL}` |
| `fill` | `fill: { selector: "#email", value: "a@b.c" }` |
| `click` | `click: "button[type=submit]"` |
| `press` | `press: Enter` or `press: { key: "Ctrl+Enter", selector: ".cm-content" }` |
| `wait` | `wait: 500` (ms) |
| `wait_for` | `wait_for: "#welcome"`, `wait_for: { selector: "#menu [role=treeitem]", timeout: 15000 }`, or `wait_for: { idle: true, timeout: 15000 }` (document loaded and no new request for 1 s; warns and continues on timeout) |
| `sql` | `sql: "SELECT ..."` (DBX tab: opens a query editor once, types, runs with Ctrl+Enter) |
| `dbx_login` | `dbx_login: "${DBX_PASSWORD}"` (tab `setup:` only; skipped if already logged in) |
| `select` | `select: { selector: "#country", value: VN }` (option `value`; a list for multi-select) |
| `hover` | `hover: "#menu"` |
| `scroll` | `scroll: "#footer"` (scrolls the element into view) |
| `upload` | `upload: { selector: "input[type=file]", file: fixtures/invoice.pdf }` (path relative to the scenario; a list for several files) |
| `eval` | `eval: "localStorage.setItem('token', '${TOKEN}')"` — run JS in the page (seed cookies/localStorage, flags); fails if it throws or returns `false`; prefer real actions for anything the video should show |
| `dialog` | `dialog: accept` or `dialog: dismiss` — put it before the action that opens `alert`/`confirm`/`prompt`; lasts until the page navigates |
| `clear` | `clear: "#date"` — select-all + Backspace; clears masked inputs (date pickers) that keep their value on `fill: ""` |
| `download` | `download: { selector: "button#print", path: report.pdf, append: true }` (agent-browser only) — clicks the element, waits for the file and keeps it in `<out>/downloads/`; the file's own `download` name is used when `path` is omitted; `append: true` adds the PDF's pages to the end of `final.mp4` |
| `expect` | `expect: { value: { selector: "#ctrl", equals: X9 } }` (or a list) — a check between actions, e.g. before a tab switch unmounts the field; a failure stops the step |

Before `click`, `fill`, `select`, `hover`, `upload` and `press` (with a selector), TIRAI scrolls the element into
view when it is outside the viewport (`settings.auto_scroll: false` turns it off).

Selectors are CSS (native `:has()` works, e.g. `button:has(svg.add)`) or the locators under
[Targets](#targets-name). Playwright-only syntax (`:has-text()`, `:text-is()`, `>>`, `:visible`) never matches in
agent-browser/bsk, so `tirai validate` rejects it and suggests a locator. A CSS list (`"a, b"`) takes the first
match in page order, not list order; `validate` warns and suggests `targets:` fallbacks.

## Expectations

| Expect | Example |
|---|---|
| `visible` | `visible: "#email"` |
| `text_contains` | `text_contains: { selector: ".error", text: "locked" }` (no selector = whole page) |
| `not_visible` | `not_visible: "#login-error"` (missing, zero-size, `display:none` or `visibility:hidden`) |
| `text_matches` | `text_matches: { selector: "#total", pattern: "^\\d+ items$", flags: i }` (JavaScript RegExp, like `save.pattern`) |
| `url_contains` | `url_contains: "/dashboard"` |
| `value` | `value: { selector: "#email", equals: "a@b.c" }` (form field value) |
| `attribute` | `attribute: { selector: "#save", name: disabled, equals: "" }` |
| `count` | `count: { selector: "table tbody tr", equals: 3 }` |
| `request` | `request: { url_contains: "/api/orders", status: 201 }` (any page or XHR/fetch request seen by the page; `status` optional) |
| `no_console_errors` | `no_console_errors: {}` or `{ ignore: ["favicon"] }` (console errors/exceptions raised during this step) |
| `pdf` | `pdf: { path: report.pdf, pages: 2 }` or `pages: [1, 3]` (range), optional `contains: "text"` (or a list) — checks the downloaded PDF; `path` resolves against the scenario dir, then `<out>/downloads/` |
| `xlsx` | `xlsx: { path: report.xlsx, sheets: [Orders], contains: "A-1" }` — checks sheet names and cell text of the downloaded workbook |
| `db` | `db: { sql: "SELECT status FROM users WHERE id=2", rows: [{status: LOCKED}] }` (`columns:` defaults to the keys of the first expected row, in SELECT order) — numbers compare by value, so `204000` matches `"204000.00000"` from PostgreSQL `numeric` |

DOM checks retry for up to 6 s (`settings.expect_timeout: 15` for slow SPAs). `db` runs read-only against `databases.<name>.dsn` (default `default`),
independently of what the DBX tab shows: DBX draws its result grid on a canvas, so its cells are not DOM text.

Every step also notes failed requests (HTTP 4xx/5xx seen by the page, e.g. a silent `401` from an expired
session) and console errors raised while it ran. They are printed, stored in `timeline.json` and listed in the
report even when the step passes. `settings.strict_network: true` fails the step instead;
`settings.ignore_requests: ["/healthz"]` drops URLs you expect to fail.

## Steps that write data

A dry-run runs the real actions (it only skips the video), so a step that saves an order creates one every time.
Mark such steps with `writes:`; `sql:` actions with `INSERT`/`UPDATE`/`DELETE`/DDL count automatically.

```yaml
steps:
  - id: SAVE
    tab: app
    title: Save the order
    writes: creates an order (受注)
    actions: [{ click: "@save" }]
    save: { name: orderNo, selector: "#orderNo" }
    expect: [{ text_contains: { text: "saved" } }]
cleanup:                                   # after the run; not recorded; only when a write step ran
  - tab: db
    actions:
      - sql: "DELETE FROM orders WHERE order_no = '{{orderNo}}'"
```

- `tirai validate` lists the steps that write data.
- `tirai run --dry-run` stops before the first write step and reports the steps before it; `--allow-writes` runs
  everything. `tirai record` dry-runs up to the first write step, then records the whole flow once.
- `--until <step>` stops a dry-run after that step (or the last step expanded from it).
- The report has a "Data written" table with each write step and the values it saved, so test data can be
  cleaned up by hand when there is no `cleanup:`.

## Iterating on a long flow

```bash
tirai run flow.yaml --dry-run --keep-session            # prints: session kept: tirai-1234
tirai run flow.yaml --dry-run --session tirai-1234 --from-step S14
```

`--from-step` continues on the pages the kept session has open (no new tab, no tab `setup:`), with the values
saved by the previous run in the same `--out` folder. `--fresh` clears cookies and storage before tab setup, so
the run starts logged out instead of reusing an old session (bsk cannot clear HttpOnly cookies).

## Popup windows

```yaml
tabs:
  app: { url: "${APP_URL}" }
  order: { popup: true, match: "/AB03001" }   # adopted when a step first uses it
```

A `popup: true` tab has no URL: the first step on it binds to the newest browser tab the page opened
(`window.open`, `target=_blank`) whose URL contains `match`, waiting up to `expect_timeout`. If that window
closes and a new one opens, the next step binds again.

## Viewport

`settings.viewport: { width: 1600, height: 900 }` sets the page size on agent-browser (each tab and popup).
bsk uses the size of your browser window.

## Recording model

BrowserSkill records one tab at a time (max 10 min per recording, no audio). TIRAI starts a new
segment whenever the active tab changes, stores per-step start/end offsets in `timeline.json`, and
`tirai compose` cuts each step out of its segment and joins them in scenario order.

## Data-driven scenarios

```yaml
vars: { base: "${APP_URL}" }                  # scenario-wide values for {{name}}
cases:                                        # or matrix: {browser: [a, b], locale: [en, vi]} (cartesian product)
  - { name: Alice, email: alice@demo.local, status: ACTIVE }
  - { name: Bob,   email: bob@demo.local,   status: LOCKED }
steps:
  - id: OPEN
    once: true                                # first case only
    tab: app
    title: App is reachable
    actions: [{ navigate: "{{base}}" }]
    expect: [{ visible: "#email" }]
  - include: common/login.yaml                # list of steps, or a mapping with steps:
    with: { password_env: APP_PASSWORD }
  - id: DB
    tab: app
    title: "DB status is {{status}} (screen said: {{message}})"
    expect:
      - db:
          sql: "SELECT status FROM users WHERE email = '{{email}}'"
          rows: [{ status: "{{status}}" }]
          save: { db_status: status }         # column -> variable for later steps
```

- `{{name}}` comes from `vars:`, the current case, or a value saved earlier; `${NAME}` stays an environment variable.
- Steps repeat once per case with ids `LOGIN-1`, `LOGIN-2`, … and titles prefixed `[Alice]`.
- `save: { name, selector, attribute?, pattern?, flags?, timeout?, allow_empty? }` stores an element's
  value/text (first group of the JavaScript RegExp `pattern` if it has one), as an action or as a step key. It
  polls until the value is non-empty and matches (up to `timeout` seconds, default `expect_timeout`), so async
  forms need no `eval:` poll; `allow_empty: true` stores empty values. Values saved in one action are visible
  to the next action or check of the same step. `db: { save: { variable: column } }` stores a column of the first
  row; a missing column or an empty result is an error.

### Loops and steps that run once

```yaml
vars:
  lines: [{ code: A01, qty: 2 }, { code: B07, qty: 1 }]
steps:
  - id: LINE
    for_each: lines                           # or an inline list; scalars are {{item}} (rename with as:)
    tab: app
    title: "Line {{index}}: {{code}}"
    actions:
      - click: "@add_row"
      - fill: { selector: "#lines tr:last-child .code", value: "{{code}}" }
    expect: [{ value: { selector: "#lines tr:last-child .code", equals: "{{code}}" } }]
  - id: SAVE                                  # runs once, after every line
    ...
```

`for_each` repeats one step per item (`LINE-1`, `LINE-2`, …; `{{index}}` counts from 1). With `cases:`, use
`once: last` for a step that must run once after the last case (`once: true` = first case only).
- A placeholder that is the whole value keeps its type (`equals: "{{count}}"` stays a number). An undefined
  variable at run time is an error.

## Video options

| Option | Where | Effect |
|---|---|---|
| Chapters | automatic | `final.mp4` has one chapter per step (title card included) |
| `zoom: "#email"` | step | eases in (≈0.6 s) on the element and holds; factor defaults to 1.8, capped so the target fits |
| `layout: split` | step | left: last frame of the previous step (or `split_with`), right: this step; useful for UI → DB proof |
| `--lang vi` | `tirai record` / `compose` | burns that subtitle language; every language is also written as `subtitles.<lang>.srt` |
| `zoom: follow` | step | zooms in and pans from one action target (click, fill, select…) to the next |
| `camera: follow` | `settings:` | `zoom: follow` for every step without its own `zoom:`; `camera_factor` (default 1.6) sets the zoom |
| `--trim-still` | `tirai record` / `compose` (or `settings.trim_still: true`) | stretches of 2 s or more where the screen does not change play at 8× with a badge; each step's start and closing `hold` stay at normal speed |
| `fast_forward: 4` | `settings:` | `wait`/`wait_for` longer than 1.5 s play at 4× with a "4x" badge (default 4; `0` turns it off) |
| `single_tab: true` | `settings:` | apps that open child screens with `window.open`/`target=_blank` navigate the same tab, so the screencast never freezes on the opener page (agent-browser; declare `popup: true` tabs instead when you need both pages) |
| `--voice` | `tirai compose` | reads each subtitle aloud (macOS `say`, Windows SAPI, Linux `espeak-ng`, or `$TIRAI_TTS_CMD` with `{text}` `{out}` `{lang}`); a clip is held until its speech ends |

## Desktop apps (agent-desktop)

A tab with `app:` instead of `url:` drives a native app through the OS accessibility tree
([agent-desktop](https://github.com/vercel-labs/agent-desktop): macOS AX, Windows UI Automation, Linux AT-SPI) and
records the screen around its window with ffmpeg. Browser and desktop tabs can be mixed in one scenario.

```yaml
tabs:
  calc: { app: gnome-calculator, label: Calculator }   # name: overrides the name used to find the app
steps:
  - id: S1
    tab: calc
    title: 7 + 8 = 15
    actions:
      - click: "button:7"                              # role:name (exact name) or a bare accessible name
      - click: "button:+"
      - click: "button:8"
      - click: "button:="
    expect:
      - text_contains: { selector: { role: textfield }, text: "15" }   # mapping = agent-desktop find filters
```

Actions: `click`, `fill` (set-value, falls back to clear + type), `press`, `select`, `hover`, `scroll`, `wait`,
`wait_for`. Expectations: `visible`, `not_visible`, `text_contains`, `text_matches`, `value`. `annotate:` and
`privacy:` masking are browser-only (use `privacy.ocr` to scan the final video). Install with
`tirai setup --only agent-desktop`. Needs: Linux X11 with AT-SPI (agent-desktop supports Ubuntu 24.04+) and a
window manager; macOS Accessibility + Screen Recording permission for the terminal; Windows desktop session.

## Subtitles in several languages

```yaml
lang: en                                      # default burned language (override with --lang)
steps:
  - id: S2
    subtitle:
      en: "Step 2: malformed email -> validation error"
      vi: "Bước 2: email sai định dạng -> báo lỗi"
```

Missing languages fall back to the first one given for that step.

## Privacy: automatic PII masking

```yaml
privacy:
  mask: [email, phone, card, token]           # built-in rules
  patterns: ['ACC-\d{6}']                     # extra regexes (JavaScript syntax)
  selectors: [".api-key"]                     # always covered
  keep: ["bob@demo.local"]                    # exact strings that stay visible (e.g. the record under test)
  inputs: true                                # also cover matching input/textarea values (default)
```

Matches are covered with an opaque box in the page (so screenshots and video both hide them) and stay covered
while the DOM changes. With agent-browser the mask is registered as a page init script, so it is active before the page's own scripts on every load; it is also re-applied after every navigation, click and action. Set `privacy: false` on a
tab to skip it. Limitations: text drawn on a canvas (e.g. DBX result cells) is not scanned — cover those with an
`annotate: blur` grid target, or let the OCR pass below catch them — and values in step titles, subtitles or
`save`d variables are not rewritten.

### OCR pass over the final video

```yaml
privacy:
  mask: [email, phone]
  ocr: fix          # off (default) | warn | fix (pixelate hits and rewrite final.mp4) | fail (exit non-zero)
```

After composing, frames are sampled (1/s) and read with tesseract (`tirai setup --only ocr`), so text drawn on a
canvas (DBX grids, images, desktop apps) is checked against the same rules; `keep:` still applies. Hits are
reported masked with time and box. On demand: `tirai scan-pii evidence/record [--rules email phone] [--fix]`.
OCR can misread UI text as an email-like string, so review `warn` hits before relying on them.
