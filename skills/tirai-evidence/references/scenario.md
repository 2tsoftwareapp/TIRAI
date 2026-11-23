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
| `tab` | yes | Tab name from `tabs:` |
| `title` | yes | Header bar text and report row |
| `subtitle` | no | Burned-in subtitle (defaults to `title`); a `{en: ..., vi: ...}` map for several languages |
| `actions` | no | Executed in order |
| `expect` | yes | All must pass for the step to pass |
| `annotate` | no | Drawn after expectations are checked |
| `hold` | no | Seconds the step stays on screen (default 2.5 recorded, 0.3 dry-run) |
| `zoom` | no | Selector (or `{target, factor, at}`) the video eases in on during this step |
| `layout` | no | `split`: show the previous step (or `split_with: <id>`) beside this one |
| `once` | no | With `cases:`/`matrix:`, run this step only for the first case |
| `include` | — | Instead of a step: `include: file.yaml` (+ `with:` vars, `prefix:` for ids) |

## Actions

| Action | Example |
|---|---|
| `navigate` | `navigate: ${APP_URL}` |
| `fill` | `fill: { selector: "#email", value: "a@b.c" }` |
| `click` | `click: "button[type=submit]"` |
| `press` | `press: Enter` or `press: { key: "Ctrl+Enter", selector: ".cm-content" }` |
| `wait` | `wait: 500` (ms) |
| `wait_for` | `wait_for: "#welcome"` |
| `sql` | `sql: "SELECT ..."` (DBX tab: opens a query editor once, types, runs with Ctrl+Enter) |
| `dbx_login` | `dbx_login: "${DBX_PASSWORD}"` (tab `setup:` only; skipped if already logged in) |
| `select` | `select: { selector: "#country", value: VN }` (option `value`; a list for multi-select) |
| `hover` | `hover: "#menu"` |
| `scroll` | `scroll: "#footer"` (scrolls the element into view) |
| `upload` | `upload: { selector: "input[type=file]", file: fixtures/invoice.pdf }` (path relative to the scenario; a list for several files) |
| `dialog` | `dialog: accept` or `dialog: dismiss` — put it before the action that opens `alert`/`confirm`/`prompt`; lasts until the page navigates |

## Expectations

| Expect | Example |
|---|---|
| `visible` | `visible: "#email"` |
| `text_contains` | `text_contains: { selector: ".error", text: "locked" }` (no selector = whole page) |
| `not_visible` | `not_visible: "#login-error"` (missing, zero-size, `display:none` or `visibility:hidden`) |
| `text_matches` | `text_matches: { selector: "#total", pattern: "^\\d+ items$", flags: i }` (JavaScript RegExp) |
| `url_contains` | `url_contains: "/dashboard"` |
| `value` | `value: { selector: "#email", equals: "a@b.c" }` (form field value) |
| `attribute` | `attribute: { selector: "#save", name: disabled, equals: "" }` |
| `count` | `count: { selector: "table tbody tr", equals: 3 }` |
| `request` | `request: { url_contains: "/api/orders", status: 201 }` (any page or XHR/fetch request seen by the page; `status` optional) |
| `no_console_errors` | `no_console_errors: {}` or `{ ignore: ["favicon"] }` (console errors/exceptions raised during this step) |
| `db` | `db: { sql: "SELECT status FROM users WHERE id=2", columns: [status], rows: [{status: LOCKED}] }` |

DOM checks retry for up to 6 s. `db` runs read-only against `databases.<name>.dsn` (default `default`),
independently of what the DBX tab shows: DBX draws its result grid on a canvas, so its cells are not DOM text.

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
- `save: { name, selector, attribute?, pattern? }` stores an element's value/text (first regex group if
  `pattern` has one). Values saved in one action are visible to the next action or check of the same step.
- A placeholder that is the whole value keeps its type (`equals: "{{count}}"` stays a number). An undefined
  variable at run time is an error.

## Video options

| Option | Where | Effect |
|---|---|---|
| Chapters | automatic | `final.mp4` has one chapter per step (title card included) |
| `zoom: "#email"` | step | eases in (≈0.6 s) on the element and holds; factor defaults to 1.8, capped so the target fits |
| `layout: split` | step | left: last frame of the previous step (or `split_with`), right: this step; useful for UI → DB proof |
| `--lang vi` | `tirai record` / `compose` | burns that subtitle language; every language is also written as `subtitles.<lang>.srt` |

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
while the DOM changes. Masking is re-applied after every navigation, click and action. Set `privacy: false` on a
tab to skip it. Limitations: text drawn on a canvas (e.g. DBX result cells) is not scanned — cover those with an
`annotate: blur` grid target — and values in step titles, subtitles or `save`d variables are not rewritten.
