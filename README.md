# TIRAI — test evidence recorder for AI agents

Write a test scenario (steps, actions, expected results). TIRAI runs it in a real browser, checks the
database in a second tab, draws boxes, arrows and labels on screen, records it, and composes one
MP4 with subtitles plus a step report.

Install it as a skill for **Claude Code, Codex, Antigravity, Cursor or Devin**.

```text
scenario.yaml → dry-run (find failing steps) → record (per tab) → compose → final.mp4 + report.md
```

| Piece | Tool |
|---|---|
| Browser control and recording | [Tencent BrowserSkill](https://github.com/Tencent/BrowserSkill) (`bsk`) |
| Database in the browser | [DBX web](https://github.com/t8y2/dbx) |
| Scenario runner, checks, annotations, composition | TIRAI (Python + ffmpeg + `annotate.js`) |

## Install

One command installs the `tirai` CLI (isolated virtualenv in `~/.tirai`), then `tirai setup` installs
ffmpeg, the BrowserSkill CLI and the skill for every agent it detects.

| OS | Command |
|---|---|
| macOS / Linux | `curl -fsSL https://raw.githubusercontent.com/2tsoftwareapp/TIRAI/main/install.sh \| sh` |
| Windows (PowerShell) | `irm https://raw.githubusercontent.com/2tsoftwareapp/TIRAI/main/install.ps1 \| iex` |

Then install the **BrowserSkill browser extension** (Chrome Web Store / Edge Add-ons, manual) and run `tirai doctor`.

- Requires Python 3.10+; everything else is installed by `tirai setup` (brew, apt/dnf/pacman/zypper/apk, winget/choco/scoop).
- Non-interactive: `... | sh -s -- --yes --agent claude` (Windows: `$env:TIRAI_SETUP_ARGS="--yes --agent claude"`).
- Already have the CLI? `pipx install "tirai[postgres] @ git+https://github.com/2tsoftwareapp/TIRAI"` then `tirai setup`.

Claude Code can also install the skill as a plugin: `/plugin marketplace add 2tsoftwareapp/TIRAI`, then
`/plugin install tirai-evidence@tirai`. Per-agent details: [docs/agents.md](docs/agents.md).
All paths and tools can be overridden: [docs/configuration.md](docs/configuration.md).

## Usage

Ask your agent: *"Record evidence for login validation: invalid email, locked user, DB status check."*
The skill walks it through the same commands you can run yourself:

```bash
tirai init scenarios/login.yaml        # template
tirai validate scenarios/login.yaml    # structure + required env vars
tirai run scenarios/login.yaml --dry-run
tirai record scenarios/login.yaml      # evidence/record/final.mp4, subtitles.srt, report.md
```

A step:

```yaml
- id: S3
  tab: app
  title: Locked account is rejected
  subtitle: "Step 3: log in as bob@demo.local (locked) -> rejected"
  actions:
    - fill: { selector: "#email", value: "bob@demo.local" }
    - fill: { selector: "#password", value: "${APP_PASSWORD}" }
    - click: "button[type=submit]"
  expect:
    - text_contains: { selector: ".error", text: "This account is locked" }
  annotate:
    - circle: { target: ".error" }
    - arrow: { target: ".error", from: bottom, label: "Account locked" }
    - blur: { target: "#password" }
```

Try the full demo (web app + PostgreSQL + DBX): [docs/getting-started.md](docs/getting-started.md).

## Docs

- [Getting started](docs/getting-started.md)
- [Configuration](docs/configuration.md)
- [Scenario format](docs/scenario-format.md)
- [Annotations](docs/annotations.md)
- [Agent installation](docs/agents.md)
- [Architecture](docs/architecture.md)
- [Troubleshooting](docs/troubleshooting.md)

## Security

- Secrets only through `${ENV_VAR}`; they are never written to timelines or reports.
- Use a read-only database user for DBX and `expect: db`.
- Mask sensitive fields with `blur` (rendered instantly, before the frame is recorded).
- BrowserSkill drives a real browser profile: use a dedicated profile or Agent Window.

## Previous version

The spec-to-test platform (TIRAI v1, TypeScript) is archived on branch
[`archive/tirai-v1`](https://github.com/2tsoftwareapp/TIRAI/tree/archive/tirai-v1).

## License

MIT
