# Troubleshooting

| Symptom | Fix |
|---|---|
| `bsk doctor` shows no extension | open the browser with the BrowserSkill extension enabled and connected |
| `bsk open failed ... session <id> unknown` | TIRAI closes the stale session and retries once; if it persists: `bsk session list`, `bsk close --session <id>`, or `--scope <new>` |
| `requires an unused strict observation` / `control context no longer belongs` | page changed under an action; add `wait_for` before the next action. The runner already syncs before every action |
| `annotate: target not found` | selector not visible at annotation time; check `step-<id>.png` from the dry-run |
| DBX cells not found by text | DBX draws results on a canvas: use `{ grid: { column, row } }` targets and `expect: db` |
| `tirai: command not found` after install | open a new terminal (PATH was updated) or run `~/.local/bin/tirai` / `%USERPROFILE%\\.local\\bin\\tirai.cmd` |
| ffmpeg installed by winget but not found | open a new terminal, or set `FFMPEG_BIN`; TIRAI also checks `%LOCALAPPDATA%\\Microsoft\\WinGet\\Links` |
| Linux package install asks for a sudo password | run the printed `sudo ...` command yourself, then `tirai setup` again |
| DBX query does not run on macOS | the run shortcut defaults to `Meta+Enter`; override with `tabs.<db>.dbx.run_key` |
| Steps flaky on a slow machine | `TIRAI_TIMING_SCALE=2` |
| Subtitles missing Vietnamese glyphs | set `TIRAI_FONT` (and `TIRAI_FONT_BOLD`) to a Unicode .ttf |
| `missing environment variable X` | export it; `tirai validate` lists every variable the scenario needs |
| Video is choppy | BrowserSkill records ~12 fps; keep `anim: draw`/`fade` short or use `anim: none` |
