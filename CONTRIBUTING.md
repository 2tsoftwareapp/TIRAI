# Contributing to TIRAI

## Setup

```bash
python3 -m venv .venv && .venv/bin/pip install -e '.[dev,postgres]'
.venv/bin/ruff check . && .venv/bin/ruff format --check .
.venv/bin/pytest
node --check src/tirai/assets/annotate.js
```

End-to-end changes (runner, BrowserSkill wrapper, annotations) must be verified with the demo in
`examples/demo` (`tirai record examples/demo/login-lock.yaml`) and the resulting `final.mp4` inspected.

## Rules

- Keep each step's contract: actions + expect; a missing selector, target or env var fails the step.
- Never persist secrets; database access stays read-only.
- `annotate.js` stays dependency-free and isolated in its shadow root.
- When the scenario vocabulary changes, update `skills/tirai-evidence/references/*` and `docs/` together.
- After editing docs, the skill, the CLI or the demo scenario, run `python scripts/build_llms_full.py` (a test fails if `llms-full.txt` is stale).
- Small, focused PRs with tests.
