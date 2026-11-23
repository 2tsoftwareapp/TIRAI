# Installing the skill for an agent

The skill is `skills/tirai-evidence/` (SKILL.md + references). Every agent uses the same `tirai` and `bsk` CLIs.

| Agent | Install | Skill location |
|---|---|---|
| Claude Code | `/plugin marketplace add 2tsoftwareapp/TIRAI` then `/plugin install tirai-evidence@tirai`, or `tirai install-skill --agent claude` | `~/.claude/skills` or `<project>/.claude/skills` |
| Codex | `tirai install-skill --agent codex` | `~/.agents/skills` or `<project>/.agents/skills` |
| Antigravity | `tirai install-skill --agent antigravity` | `~/.gemini/antigravity/skills` or `<project>/.agent/skills` |
| Cursor | `tirai install-skill --agent cursor` | `~/.cursor/skills` or `<project>/.cursor/skills` |
| Devin | `tirai install-skill --agent devin --project .` and commit it | `<repo>/.agents/skills` |
| Other | `tirai install-skill --agent claude --dest <skills dir>` | any directory the agent scans |

`tirai setup` installs the skill for every agent it detects (`~/.claude`, `~/.codex`, `~/.gemini/antigravity`,
`~/.cursor`); Devin skills are per repository, so use `--project`.

Add `--project <dir>` to install into a repository instead of the user profile, `--force` to overwrite.
Also install BrowserSkill's own skill so the agent can explore pages: `bsk install-skill --harness <id>`.

Agents without skill support can read `AGENTS.md` / `skills/tirai-evidence/SKILL.md` directly.

## MCP server

MCP-capable agents can call TIRAI as tools instead of the shell:

```json
{ "mcpServers": { "tirai": { "command": "tirai", "args": ["mcp"] } } }
```

Tools: `doctor`, `init`, `validate`, `dry_run`, `record`, `compose`, `verify`, `from_trace`, `annotate_js`. Each
accepts an optional `cwd`; results are the CLI output, with `isError` set when the command fails.

## Capture a flow instead of writing it

```bash
tirai capture http://127.0.0.1:8080/ --purpose "Locked account is rejected" -o scenarios/locked.yaml
```

A browser window opens (agent-browser); click through the flow, then close the window. Selectors come from the
page (id, data-testid, name, aria-label, else a short path); passwords become `${ENV}` placeholders.
`--driver bsk` uses BrowserSkill's Agent Window (`bsk record`) instead.
TIRAI replays the trace to resolve every target to a CSS selector, splits it into steps at each click/navigation
and derives an expectation from what changed (new URL or new text). Redacted values such as passwords become
`${PASSWORD}`-style placeholders. Review titles and expectations, add `annotate:`, then dry-run.
`tirai from-trace <trace dir> -o file.yaml` converts an existing trace (`--no-resolve` skips the replay and
leaves `TODO role=… name=…` selectors).
