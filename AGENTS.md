# TIRAI — agent instructions

TIRAI records test evidence videos from YAML scenarios. Using it in another project: follow
`skills/tirai-evidence/SKILL.md`. Working on this repository: read on.

## Layout

| Path | Role |
|---|---|
| `src/tirai/cli.py` | `tirai` command (doctor, init, validate, run, record, compose, install-skill, annotate-js) |
| `src/tirai/scenario.py` | scenario validation and `${ENV}` interpolation |
| `src/tirai/runner.py` | executes steps through BrowserSkill, records per-tab segments, writes `timeline.json` |
| `src/tirai/bsk.py` | wrapper over the `bsk` CLI (sync before every action) |
| `src/tirai/compose.py` | ffmpeg composition: clips, header bar, title card, subtitles, report |
| `src/tirai/db.py` | read-only queries for `expect: db` |
| `src/tirai/assets/annotate.js` | injected annotation overlay |
| `skills/tirai-evidence/` | the agent skill (also packaged into the wheel and the Claude plugin) |
| `examples/demo/` | demo app + PostgreSQL + DBX stack and the reference scenario |

## Commands

```bash
python3 -m venv .venv && .venv/bin/pip install -e '.[dev,postgres]'
.venv/bin/ruff check . && .venv/bin/ruff format --check .
.venv/bin/pytest
for f in src/tirai/assets/*.js; do node --check "$f"; done
```

End-to-end (needs BrowserSkill extension connected and the demo stack): see `docs/getting-started.md`.

## Rules

- Secrets only through `${ENV_VAR}`; never write them to timelines, reports or fixtures.
- Database checks stay read-only.
- A missing annotation target or selector must fail the step, never be skipped silently.
- Keep `annotate.js` dependency-free and isolated in its shadow root.
- Update `docs/` and the skill references when the scenario vocabulary changes.
