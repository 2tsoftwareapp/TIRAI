# Getting started

## 1. Install

```bash
# macOS / Linux
curl -fsSL https://raw.githubusercontent.com/2tsoftwareapp/TIRAI/main/install.sh | sh
```

```powershell
# Windows (PowerShell)
irm https://raw.githubusercontent.com/2tsoftwareapp/TIRAI/main/install.ps1 | iex
```

The installer works on any machine, with or without Python:

| Method | When | What it does |
|---|---|---|
| **Prebuilt binary** (default when available) | a GitHub Release has `tirai-<os>-<arch>` for this machine | downloads it to `~/.tirai/bin`, verifies `.sha256`; no Python needed |
| **From source** (fallback, or `--source`) | no binary for this machine | Python ≥ 3.10 on the machine → `~/.tirai/venv`; otherwise it downloads [uv](https://docs.astral.sh/uv/) and a private Python 3.12 into `~/.tirai` (system Python is never touched) |

Force a method with `sh install.sh --binary|--source` (PowerShell: `./install.ps1 --binary|--source`) or
`TIRAI_INSTALL_MODE`. `tirai` is linked into `~/.local/bin`, then `tirai setup` installs, for this OS:

| Tool | How | Where |
|---|---|---|
| ffmpeg ≥ 6.0 | kept if already new enough; otherwise a static [BtbN](https://github.com/BtbN/FFmpeg-Builds) 8.1 build (Linux, Windows) or `brew install ffmpeg` (macOS). ffmpeg 4.4 breaks agent-browser recording | `~/.tirai/bin` |
| [agent-browser](https://github.com/vercel-labs/agent-browser) | release binary, then `agent-browser install` (Chrome for Testing; `--with-deps` on Linux) | `~/.tirai/bin` |
| [DBX web](https://github.com/t8y2/dbx) | `browser-static` release package, SHA-256 checked (Linux x64/arm64, Windows x64); Docker image `t8y2/dbx` elsewhere | `~/.tirai/dbx` |
| BrowserSkill CLI | official installer (only needed for `driver: bsk`) | `~/.local/bin` |

Skip any of them with `--skip ffmpeg,agent-browser,dbx,browserskill,skills`. Then:

```bash
tirai doctor
tirai dbx -d          # DBX web on http://127.0.0.1:4224; set DBX_PASSWORD for the web login
```

## Browser drivers

| | `agent-browser` (default) | `bsk` |
|---|---|---|
| Browser | Chrome for Testing, headless (`--headed` to watch) | your real Chrome/Edge via the BrowserSkill extension |
| Recording | 30 fps, animated cursor (`TIRAI_CURSOR=0` to hide) | ~12 fps |
| Extension needed | no | yes |
| `tirai capture` | yes (close the window to finish) | yes (`bsk record`) |

Pick one with `driver:` in the scenario, `--driver`, or `TIRAI_DRIVER`. Both record the active tab only, so TIRAI
records one segment per tab block and composes them.

### Build the binary yourself

```bash
python scripts/build_binary.py             # dist/tirai-<os>-<arch>[.exe] + .sha256 (PyInstaller, one file)
TIRAI_BINARY=dist/tirai-linux-x64 sh install.sh --binary
```

Run it on each OS/arch you ship and attach the files to a GitHub Release; the installers pick them up from
`releases/latest` (or `TIRAI_VERSION=<tag>`).

## 2. Run the demo

```bash
cd examples/demo
docker compose up -d                       # app :8080, PostgreSQL :5432, DBX :4224
cp .env.example .env                       # Windows: copy .env.example .env
```

In DBX (http://127.0.0.1:4224, password `dbx_demo_pw`) create one PostgreSQL connection:
host `db`, port `5432`, database `shop`, user `evidence_ro`, password `ro_demo_pw`. DBX keeps it in its data dir.

```bash
tirai run login-lock.yaml --dry-run        # loads .env next to the scenario; 6 steps, no video
tirai record login-lock.yaml               # evidence/record/final.mp4 + report.md
```

## 3. Your own scenario

```bash
tirai init scenarios/my-feature.yaml
tirai validate scenarios/my-feature.yaml
```

Write steps as *action + expect*, see [scenario format](scenario-format.md) and [annotations](annotations.md).
