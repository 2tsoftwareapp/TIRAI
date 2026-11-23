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

## Releasing

1. Bump `version` in `pyproject.toml`, `src/tirai/__init__.py` and `.claude-plugin/plugin.json`; move the
   `CHANGELOG.md` entries under the new version.
2. On each target OS/arch (macOS arm64/x64, Linux x64/arm64, Windows x64) run `python scripts/build_binary.py`.
   It writes `dist/tirai-<os>-<arch>[.exe]` + `.sha256`. Build Linux in an old-glibc image (e.g.
   `python:3.12-bullseye`) so the binary runs on older distributions.
3. `git tag -a vX.Y.Z -m "TIRAI X.Y.Z" && git push origin vX.Y.Z`, then
   `gh release create vX.Y.Z dist/tirai-* --title "TIRAI X.Y.Z" --notes-file <notes>`. Keep the asset names: the
   installers download `releases/latest/download/tirai-<os>-<arch>` and build from source when an asset is missing.

## Rules

- Keep each step's contract: actions + expect; a missing selector, target or env var fails the step.
- Never persist secrets; database access stays read-only.
- `annotate.js` stays dependency-free and isolated in its shadow root.
- When the scenario vocabulary changes, update `skills/tirai-evidence/references/*` and `docs/` together.
- After editing docs, the skill, the CLI or the demo scenario, run `python scripts/build_llms_full.py` (a test fails if `llms-full.txt` is stale).
- Small, focused PRs with tests.
