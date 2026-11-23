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

The installer creates `~/.tirai/venv`, puts `tirai` in `~/.local/bin`, then runs `tirai setup`
(ffmpeg, BrowserSkill CLI, agent skills). Install the BrowserSkill browser extension, then:

```bash
tirai doctor
```

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
