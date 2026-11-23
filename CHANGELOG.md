# TIRAI Changelog

All notable changes to TIRAI, the scenario-driven test evidence recorder (CLI + agent skill).

---

## [Unreleased]

### Added

- `eval:` action: run JS in the page (e.g. seed cookies/localStorage before a flow); fails on an exception or `false`.
- `targets:` + `@name`: name an element once with fallback locators (`testid=`, CSS, `role=…[name=…]`,
  `label=`, `placeholder=`, `text=`/`text*=`, `within:`, `nth:`); it is tagged in the page as `data-tirai-id` and
  kept tagged through re-renders and navigation, on agent-browser and bsk. 0 or 2+ matches fail the step; a
  fallback match passes with a warning (also in `timeline.json`). Locators also work inline (`click: text=Save`).
- `tirai inspect <scenario|url>` (and MCP `inspect`): per-step element map with unique locators and a suggested
  `targets:` block, including pages reached after login.
- Selector failures end with `nearby: …` suggestions from the current page.
- `tirai verify --out <dir>` (same as the positional folder, matching `run`/`record --out`).

### Fixed

- `tirai dbx -d` no longer fails with AddrInUse when another (non-DBX) service holds port 4224: it picks the next
  free port and prints the `DBX_URL` to use.
- `tirai setup` skips sudo package installs when sudo would prompt without a terminal (agent shells) and prints the
  command instead.

## [2.2.0] - 2026-11-23

### Added

- Desktop apps: tabs with `app:` are driven by agent-desktop (accessibility tree) and recorded with ffmpeg screen
  capture; mix them with browser tabs. `tirai setup --only agent-desktop` installs the pinned, checksummed CLI.
- Video: `zoom: follow` / `settings.camera: follow` (zoom and pan between action targets) and fast-forwarded
  waits (`settings.fast_forward`, "4x" badge).
- `--voice` narration on `tirai compose` (say / SAPI / espeak-ng / `TIRAI_TTS_CMD`).
- OCR PII pass: `privacy.ocr: warn|fix|fail` and `tirai scan-pii [--fix]` (tesseract, `tirai setup --only ocr`).
- `junit.xml` with every recording; `tirai export` adds Xray JSON and TestRail CSV import files (no upload).
- `tirai sign` (SSH signature over `manifest.sha256`, optional RFC 3161 timestamp); `tirai verify --pubkey`.
- `tirai index`: one filterable HTML page across evidence runs.
- `tirai from-spec`: draft scenarios from Gherkin, Markdown or CSV test cases, with live selector resolution.
- `tirai setup --only <steps>`.
- Pinned, checksum-verified downloads in `tirai setup`: agent-browser 0.43.0 and DBX web 0.6.72 are checked against
  built-in SHA-256 digests; the static ffmpeg 8.1 archive against its release's `checksums.sha256`.
  `TIRAI_AGENT_BROWSER_VERSION` / `TIRAI_DBX_VERSION` pick another release (digest then read from GitHub);
  `TIRAI_ALLOW_UNVERIFIED=1` accepts a download without a known digest.
- `privacy:` masking is registered as an agent-browser init script, so it runs before the page's own scripts on
  every navigation and new tab (no unmasked first frames). Only origins of tabs without `privacy: false` are masked.
- `tirai capture` works on agent-browser (default): a visible browser records clicks, field changes and Enter with
  stable CSS selectors; close the window to write the scenario. `--driver bsk` keeps the `bsk record` flow.
- `tirai dbx-connect` and tab `dbx.connect:` create or update a DBX web connection from a scenario DSN, so a database
  tab needs no manual DBX setup.
- MCP: `driver` / `headed` on `dry_run` and `record`; new `capture` and `dbx_connect` tools.
- Runner unit tests with a fake driver (segments per tab block, failures, saved values, privacy, DBX provisioning).
- agent-browser driver (vercel-labs, Apache-2.0) behind a driver interface, now the default; BrowserSkill stays
  available via `driver: bsk`, `--driver bsk` or `TIRAI_DRIVER`. `--headed`, animated cursor in recordings.
- `tirai setup` checks ffmpeg's version (>= 6.0; 4.4 breaks agent-browser recording) and installs a static build
  into `~/.tirai/bin` when missing or old; downloads agent-browser + Chrome for Testing and DBX web.
- `tirai dbx [-d] [--port]` starts DBX web (installed binary, or the Docker image on macOS).
- `tirai doctor` reports ffmpeg version, agent-browser and DBX web; bsk is optional when agent-browser is present.
- Data-driven scenarios: `include:` shared steps (`with:`, `prefix:`), `vars:`, `cases:` / `matrix:`, `once: true`,
  `{{name}}` placeholders, `save:` action and `db.save` to pass values between steps.
- Video: chapters in `final.mp4`, `zoom:` ease-in on a target, `layout: split` (previous step beside this one).
- Multilingual subtitles: `subtitle: {en: ..., vi: ...}`, scenario `lang:`, `--lang`, `subtitles.<lang>.srt`.
- `privacy:` automatic PII masking (email/phone/card/token rules, patterns, selectors, keep list).
- `tirai capture` / `tirai from-trace`: turn a `bsk record` trace into a scenario with resolved CSS selectors.
- `tirai mcp`: stdio MCP server exposing the CLI as tools.
- Installers pick a method automatically: prebuilt `tirai-<os>-<arch>` binary from GitHub Releases
  (SHA-256 checked, no Python needed), otherwise build from source. `--binary` / `--source` /
  `TIRAI_INSTALL_MODE`, `TIRAI_VERSION`, `TIRAI_BINARY`.
- Source builds no longer require Python >= 3.10 on the machine: without it the installer downloads uv and a
  private Python 3.12 into `~/.tirai`.
- `scripts/build_binary.py`: one-file PyInstaller build of `tirai` for the current OS/arch.
- Scenario actions `select`, `hover`, `scroll`, `upload`, `dialog`; expectations `not_visible`, `text_matches`,
  `value`, `attribute`, `count`, `request`, `no_console_errors`. Argument keys are validated before running.
- `report.html` (self-contained, click a step to seek the video) and `report.xlsx` (`excel` extra) next to
  `report.md`; `manifest.sha256` over every evidence file and `tirai verify` to detect edits.
- `tirai record --record-failures`: records and composes a failing run as bug evidence.

### Changed

- DBX: reuses an open query editor instead of opening a new query tab on every run.

### Fixed

- DBX with several connections: the query editor is pointed at `dbx.connection` (default: `dbx.connect.name`);
  with none selected the step fails with a clear message instead of `grid body not found`.
- Final UAT fixes: `tirai index` verifies `manifest.sha256.sig` (a regenerated manifest with a stale signature shows
  `modified (bad signature)`); `expect: db` without `columns:` uses the keys of the first expected row; the `phone`
  PII rule no longer matches dates/timestamps; MCP exposes `sign`, `export`, `scan_pii`, `index`, `from_spec`;
  `tirai doctor` lists tesseract, voice, agent-desktop and ssh-keygen.
- Audit fixes: agent-browser sessions are closed when a run aborts; tab/`dbx.connect` errors are reported without a
  traceback; an unreachable tab URL fails the run; `sql:` steps fail when DBX shows a query error; the title card
  names the driver used.
- `tirai setup` reuses tools already on the machine instead of asking to install them again: a DBX web already
  running (`DBX_URL` / port 4224), `dbx-web` on PATH or an existing `t8y2/dbx` Docker container/image; agent-browser's
  Chrome when `agent-browser doctor` says it is installed and launches (no more `install --with-deps` / sudo on every
  run); the browser-skill agent skill when bsk reports it installed; the BrowserSkill extension when `bsk doctor`
  shows it connected. bsk is no longer offered when agent-browser is present (`tirai setup --only browserskill`).
- agent-browser now records with the ffmpeg TIRAI selected (e.g. setup's copy in `~/.tirai/bin`) instead of an old
  system ffmpeg on PATH, which failed with `ffmpeg write failed: Broken pipe`.
- Any ffmpeg >= 6.0 anywhere on PATH (or Homebrew/Linuxbrew/snap dirs) is used before downloading one.
- `tirai dbx` reuses a DBX web that is already running or an existing DBX Docker container.
- Re-running `install.sh` / `install.ps1` keeps an installed `tirai` of the same version (`TIRAI_FORCE=1` reinstalls).
- `tirai annotate-js` returns a stable path when running from the one-file binary.

---

## [2.1.0] - 2026-11-23

### Added

- One-command installers: `install.sh` (macOS/Linux) and `install.ps1` (Windows) create `~/.tirai/venv`,
  link `tirai` into `~/.local/bin` and run `tirai setup`.
- `tirai setup`: installs ffmpeg (brew, apt/dnf/pacman/zypper/apk, winget/choco/scoop), the BrowserSkill CLI
  (official installer) and skills for detected agents; `--dry-run`, `--yes`, `--skip`.
- `.env` next to the scenario (or `--env-file`) is loaded automatically on every OS.
- Scenario `settings:` (hold, timing_scale, expect_timeout) and per-tab `dbx:` overrides.
- `docs/configuration.md`; CI runs both installers on Linux, macOS and Windows.

### Changed

- Tool and font discovery is cross-platform with env overrides (`BSK_BIN`, `FFMPEG_BIN`, `FFPROBE_BIN`,
  `TIRAI_FONT`, `TIRAI_SUBTITLE_FONT`); subprocess output is decoded as UTF-8 on Windows.
- Output video size follows the recorded segments (or `TIRAI_VIDEO_SIZE`) instead of a fixed 1392x704.
- DBX run shortcut defaults to `Meta+Enter` on macOS.
- A stale BrowserSkill session left by a previous run is closed and the open is retried.

## [2.0.0] - 2026-11-23

### Changed (breaking)

- TIRAI is now a scenario-driven **test evidence recorder** packaged as an agent skill
  (Claude Code plugin, Codex, Antigravity, Cursor, Devin).
- The v1 spec-to-test platform (TypeScript workspaces, `tirai` Node CLI, site) was removed from `main`
  and is preserved on branch `archive/tirai-v1`.

### Added

- `tirai` Python CLI: `doctor`, `init`, `validate`, `run --dry-run|--record`, `record`, `compose`,
  `install-skill`, `annotate-js`.
- BrowserSkill-driven runner with per-tab recording segments and `timeline.json`.
- `annotate.js` overlay: box, circle, arrow, text, badge, highlight, blur; CSS/text/rect/canvas-grid targets;
  one-shot draw/fade/none animations.
- ffmpeg composition: per-step clips, header bar, title card, burned subtitles, `report.md`.
- Read-only `expect: db` checks for PostgreSQL, MySQL and SQLite.
- Demo stack (`examples/demo`): login app, PostgreSQL, DBX web, reference scenario.

---

## [1.1.1] - 2026-11-04

### 🚀 Enhancements & Features

- **Professional Multi-Format Exporters:**
  - **Excel (`.xlsx`):** Unified test cases into a primary sheet featuring corporate navy headers (`#1F4E79`), thin borders (`#D9D9D9`), zebra striping (`#F9FAFB`), freeze panes, auto-filters, and visual badges for priority and execution status (`READY`/`MANUAL`). Included companion KPI summary dashboard and traceability matrix sheets.
  - **Word (`.docx`):** Upgraded from plain unstructured text to professional bordered tables with category shading (`#D9E1F2`), step matrix layout, and default `Segoe UI` typography.
  - **Markdown (`.md`):** Designed an intuitive Full Test Matrix presenting step numbers, actions, targets, inputs, and expected outcomes side-by-side with visual badges (`🔴 HIGH`, `🟢 READY`).
  - **PDF (`.pdf`):** Styled as publication-ready technical report cards with top navy banners, executive summary KPI boxes, and card-based test case layouts.

- **True Unicode & Multi-Language Support (Vietnamese & Japanese CJK):**
  - Integrated `@pdf-lib/fontkit` into the CLI bundle.
  - Implemented **Dual-Font Segment Rendering** in the PDF exporter, dynamically routing Vietnamese diacritics to `NotoSans` and Japanese Kanji/Kana to `IPAGothic` to eliminate `WinAnsi cannot encode` crashes and question-mark (`????`) mojibake.
  - Configured `Segoe UI` across document default runs in DOCX export.

- **Playwright Test Code Generator:**
  - Added support for the `'wait'` action verb in `test-code-generator`, materializing steps into deterministic `page.locator(...).waitFor({ state: "visible" })` statements.

---

### 🐛 Bug Fixes & Stability

- **Installer (`install.sh`):**
  - Resolved `SHA256 verification failed` issue caused by duplicate `Accept: application/vnd.github+json` headers returning JSON metadata instead of binary tarball. Direct release browser download URLs are now prioritized.
- **CLI Packaging (`tirai-cli`):**
  - Updated `scripts/prepack.mjs` to automatically filter internal monorepo workspace dependencies (`agentic-test-executor`, `contract-ir`, etc.) from `package.json` before publishing tarballs, preventing `npm 404 Not Found` errors during standalone global installation.
- **Large Excel Ingestion Performance (`cell-layout-extractor`):**
  - Optimized cell traversal to skip empty cells with pattern `'none'` transparent styling, preventing catastrophic loops over 1.5M+ cells in enterprise Japanese design templates (`画面設計書`).
  - Fixed catastrophic regex backtracking in `extractArrayFormulasFromXml`.
  - Reduced ingestion time for 14-sheet 3.9MB Excel workbooks from **>12 minutes to under 52 seconds**.
- **Contract & Plan Builder:**
  - Added null-safety guards and default values for scenario preconditions, confidence scores, and quality coverage metrics in `contract-builder.ts`, eliminating unhandled `TypeError` exceptions.
- **Markdown Summary Metrics:**
  - Added safe fallbacks for test plan quality metrics in `markdown-exporter.ts`, eliminating `undefined` and `NaN%` displays.
