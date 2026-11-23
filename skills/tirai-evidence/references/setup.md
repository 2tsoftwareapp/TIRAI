# Setup

| OS | Install `tirai` + run `tirai setup` |
|---|---|
| macOS / Linux | `curl -fsSL https://raw.githubusercontent.com/2tsoftwareapp/TIRAI/main/install.sh \| sh -s -- --yes` |
| Windows | `$env:TIRAI_SETUP_ARGS="--yes"; irm https://raw.githubusercontent.com/2tsoftwareapp/TIRAI/main/install.ps1 \| iex` |

If `tirai` is already on PATH, run `tirai setup --yes` (add `--agent <name>` to choose agents).
It installs, with the OS package manager or official installer:

1. ffmpeg >= 6.0 (+ DejaVu font on Linux) — kept if new enough; otherwise a static build into `~/.tirai/bin`
   (Linux, Windows) or `brew install ffmpeg` (macOS).
2. agent-browser (default driver) — release binary into `~/.tirai/bin`, then `agent-browser install` (Chrome for Testing).
3. DBX web — `browser-static` release package into `~/.tirai/dbx` (Linux, Windows x64), else the Docker image.
4. BrowserSkill CLI (`bsk`) — Tencent's official `install.sh` / `install.ps1` into `~/.local/bin`.
5. The `tirai-evidence` skill for detected agents, plus BrowserSkill's own skill for Claude Code, Codex, Cursor.

Manual steps the user must do (ask them; never automate):

- Only for `driver: bsk`: install the **BrowserSkill** extension from the Chrome Web Store or Edge Add-ons.
- For database tabs, start DBX web: `DBX_PASSWORD=... tirai dbx -d` (installed binary, or Docker)
  and create a connection with a **read-only** database user.

Finish with `tirai doctor` → `ready`. If Linux package installs need `sudo` and it asks for a password,
ask the user to run the printed command. Tool paths can be overridden with `FFMPEG_BIN`, `FFPROBE_BIN`, `AGENT_BROWSER_BIN`, `DBX_WEB_BIN`, `BSK_BIN`, `TIRAI_FONT`.
