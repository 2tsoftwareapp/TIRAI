# Configuration

Nothing is tied to one OS or install location. Every external tool, font and timing value can be overridden.

## Environment variables

| Variable | Default | Purpose |
|---|---|---|
| `BSK_BIN` | `bsk` on PATH, then `$BSK_INSTALL_DIR`, `~/.local/bin` | BrowserSkill CLI |
| `FFMPEG_BIN`, `FFPROBE_BIN` | PATH, then Homebrew / winget / choco / scoop locations | ffmpeg tools |
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
```

## Skill locations

`tirai install-skill --agent <name>` and `tirai setup` use the paths in [agents.md](agents.md);
`--project <dir>` installs into a repository, `--dest <dir>` into any directory.
