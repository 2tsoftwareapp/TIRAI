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

Add `--project <dir>` to install into a repository instead of the user profile, `--force` to overwrite.
Also install BrowserSkill's own skill so the agent can explore pages: `bsk install-skill --harness <id>`.

Agents without skill support can read `AGENTS.md` / `skills/tirai-evidence/SKILL.md` directly.
