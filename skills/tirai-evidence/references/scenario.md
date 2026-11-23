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
| `subtitle` | no | Burned-in subtitle (defaults to `title`) |
| `actions` | no | Executed in order |
| `expect` | yes | All must pass for the step to pass |
| `annotate` | no | Drawn after expectations are checked |
| `hold` | no | Seconds the step stays on screen (default 2.5 recorded, 0.3 dry-run) |

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

## Expectations

| Expect | Example |
|---|---|
| `visible` | `visible: "#email"` |
| `text_contains` | `text_contains: { selector: ".error", text: "locked" }` (no selector = whole page) |
| `url_contains` | `url_contains: "/dashboard"` |
| `db` | `db: { sql: "SELECT status FROM users WHERE id=2", columns: [status], rows: [{status: LOCKED}] }` |

DOM checks retry for up to 6 s. `db` runs read-only against `databases.<name>.dsn` (default `default`),
independently of what the DBX tab shows: DBX draws its result grid on a canvas, so its cells are not DOM text.

## Recording model

BrowserSkill records one tab at a time (max 10 min per recording, no audio). TIRAI starts a new
segment whenever the active tab changes, stores per-step start/end offsets in `timeline.json`, and
`tirai compose` cuts each step out of its segment and joins them in scenario order.
