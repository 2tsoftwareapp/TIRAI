# Configuration

Nothing is tied to one OS or install location. Every external tool, font and timing value can be overridden.

## Environment variables

| Variable | Default | Purpose |
|---|---|---|
| `TIRAI_HOME` | `~/.tirai` | where setup puts ffmpeg, agent-browser (`bin/`) and DBX web (`dbx/`) |
| `TIRAI_DRIVER` | `agent-browser` if installed, else `bsk` | browser driver (scenario `driver:` and `--driver` win) |
| `TIRAI_HEADED` | off | show the agent-browser window (same as `--headed`) |
| `TIRAI_CURSOR` | `1` | draw agent-browser's animated cursor in recordings |
| `TIRAI_SIGN_KEY` | unset | SSH private key; `compose` re-signs `manifest.sha256` with it after rebuilding |
| `TIRAI_TTS_CMD` | unset | custom voice command for `--voice`, e.g. `piper --output_file {out}` (`{text}`, `{out}`, `{lang}`) |
| `AGENT_DESKTOP_BIN` / `AGENT_BROWSER_BIN` | PATH, `~/.tirai/bin` | explicit driver binaries |
| `TIRAI_AGENT_BROWSER_VERSION` | `0.43.0` | agent-browser release `tirai setup` downloads (pinned digest only for the default) |
| `TIRAI_DBX_VERSION` | `0.6.72` | DBX web release `tirai setup` downloads |
| `TIRAI_ALLOW_UNVERIFIED` | unset | `1` accepts a setup download whose SHA-256 is unknown |
| `AGENT_BROWSER_BIN` | `~/.tirai/bin`, PATH, `~/.local/bin` | agent-browser CLI |
| `DBX_WEB_BIN`, `DBX_WEB_DIR` | `~/.tirai/dbx` | DBX web server binary / package folder |
| `DBX_PORT`, `DBX_DATA_DIR`, `DBX_PASSWORD` | `4224`, `~/.tirai/dbx-data`, none | passed to DBX web by `tirai dbx` |
| `BSK_BIN` | `bsk` on PATH, then `$BSK_INSTALL_DIR`, `~/.local/bin` | BrowserSkill CLI |
| `FFMPEG_BIN`, `FFPROBE_BIN` | `~/.tirai/bin`, PATH, then Homebrew / winget / choco / scoop locations | ffmpeg tools (≥ 6.0) |
| `TIRAI_FONT`, `TIRAI_FONT_BOLD` | DejaVu Sans (Linux, also via `fc-match`), Arial Unicode/Arial (macOS), Arial/Segoe UI (Windows) | title, header and subtitle font files |
| `TIRAI_SUBTITLE_FONT` | family of the font above | font family name for burned subtitles |
| `TIRAI_VIDEO_SIZE` | size of the largest recorded segment | output content size, e.g. `1920x1080` |
| `TIRAI_TIMING_SCALE` | `1.0` | multiply all settle delays (use `2` on slow machines) |
| `TIRAI_EXPECT_TIMEOUT` | `6` | seconds DOM expectations retry |

Installer variables (`install.sh` / `install.ps1`): `TIRAI_REPO`, `TIRAI_REF`, `TIRAI_SOURCE` (local checkout
or archive URL), `TIRAI_HOME` (`~/.tirai`), `TIRAI_BIN_DIR` (`~/.local/bin`), `TIRAI_EXTRAS` (`postgres`),
`TIRAI_NO_SETUP=1`, `TIRAI_SETUP_ARGS` (Windows, when piping into `iex`).

## Scenario variables and `.env`

`${VAR}` placeholders are read from the environment. `tirai validate|run|record` also load a `.env`
file next to the scenario (or `--env-file <path>`); variables already set in the shell win.
This works the same in bash, zsh, PowerShell and cmd.

## Scenario `settings:`

```yaml
settings:
  hold: 2.5            # seconds each recorded step stays on screen
  timing_scale: 1.0    # same as TIRAI_TIMING_SCALE (env wins)
  expect_timeout: 6    # same as TIRAI_EXPECT_TIMEOUT (env wins)
  camera: follow       # zoom + pan to each action target (or per step: zoom: follow)
  camera_factor: 1.6
  fast_forward: 4      # speed of long waits in the video; 0 = real time
```

## DBX tab overrides

```yaml
tabs:
  db:
    url: ${DBX_URL}
    kind: dbx
    dbx:
      new_query: "New Query"           # button text that opens a SQL editor (change for a localized UI)
      editor: ".cm-content"            # SQL editor element
      password: "input[type=password]" # DBX login field
      run_key: "Ctrl+Enter"            # default: Meta+Enter on macOS, Ctrl+Enter elsewhere
      connection: shop-readonly        # connection the query editor uses (default: connect.name); needed when DBX has several
      connect:                         # optional: create/update the DBX connection before the tab opens
        name: shop-readonly            # connection name in DBX
        database: default              # key in `databases:` whose DSN is used (default: default)
        host: evpg                     # DB host as DBX sees it (e.g. Docker service); default: the DSN host
        password_env: DBX_PASSWORD     # env var with the DBX web password (default: DBX_PASSWORD)
```

`tirai dbx-connect --dsn-env EV_DB_DSN --name shop-readonly [--db-host evpg] [--url ...]` does the same from the
command line. DBX is asked to test the connection first; use a read-only database user.

## Skill locations

`tirai install-skill --agent <name>` and `tirai setup` use the paths in [agents.md](agents.md);
`--project <dir>` installs into a repository, `--dest <dir>` into any directory.
