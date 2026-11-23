# Setup

| OS | Install `tirai` + run `tirai setup` |
|---|---|
| macOS / Linux | `curl -fsSL https://raw.githubusercontent.com/2tsoftwareapp/TIRAI/main/install.sh \| sh -s -- --yes` |
| Windows | `$env:TIRAI_SETUP_ARGS="--yes"; irm https://raw.githubusercontent.com/2tsoftwareapp/TIRAI/main/install.ps1 \| iex` |

If `tirai` is already on PATH, run `tirai setup --yes` (add `--agent <name>` to choose agents).
It installs, with the OS package manager or official installer:

1. ffmpeg (+ DejaVu font on Linux) — brew / apt, dnf, pacman, zypper, apk / winget, choco, scoop.
2. BrowserSkill CLI (`bsk`) — Tencent's official `install.sh` / `install.ps1` into `~/.local/bin`.
3. The `tirai-evidence` skill for detected agents, plus BrowserSkill's own skill for Claude Code, Codex, Cursor.

Manual steps the user must do (ask them; never automate):

- Install the **BrowserSkill** extension from the Chrome Web Store or Edge Add-ons and enable the connection.
- For database tabs, run DBX web (`docker run -d -p 127.0.0.1:4224:4224 -e DBX_PASSWORD=... -e DBX_DISABLE_PASSWORD_VIEWER=true t8y2/dbx`)
  and create a connection with a **read-only** database user.

Finish with `tirai doctor` → `ready`. If Linux package installs need `sudo` and it asks for a password,
ask the user to run the printed command. Tool paths can be overridden with `FFMPEG_BIN`, `FFPROBE_BIN`, `BSK_BIN`, `TIRAI_FONT`.
