# TIRAI Changelog

All notable changes to the TIRAI specification-to-test engine and CLI.

---

## [Unreleased]

### Added

- Installers pick a method automatically: prebuilt `tirai-<os>-<arch>` binary from GitHub Releases
  (SHA-256 checked, no Python needed), otherwise build from source. `--binary` / `--source` /
  `TIRAI_INSTALL_MODE`, `TIRAI_VERSION`, `TIRAI_BINARY`.
- Source builds no longer require Python >= 3.10 on the machine: without it the installer downloads uv and a
  private Python 3.12 into `~/.tirai`.
- `scripts/build_binary.py`: one-file PyInstaller build of `tirai` for the current OS/arch.

### Fixed

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
