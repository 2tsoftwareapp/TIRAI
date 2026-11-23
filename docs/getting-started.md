# Getting started

## 1. Install

See [setup](../skills/tirai-evidence/references/setup.md) for ffmpeg, BrowserSkill and DBX. Then:

```bash
pipx install "tirai[postgres] @ git+https://github.com/2tsoftwareapp/TIRAI"
tirai doctor
```

## 2. Run the demo

```bash
cd examples/demo
docker compose up -d                       # app :8080, PostgreSQL :5432, DBX :4224
cp .env.example .env && set -a && . ./.env && set +a
```

In DBX (http://127.0.0.1:4224, password `dbx_demo_pw`) create one PostgreSQL connection:
host `db`, port `5432`, database `shop`, user `evidence_ro`, password `ro_demo_pw`. DBX keeps it in its data dir.

```bash
tirai run login-lock.yaml --dry-run        # 6 steps, no video
tirai record login-lock.yaml               # evidence/record/final.mp4 + report.md
```

## 3. Your own scenario

```bash
tirai init scenarios/my-feature.yaml
tirai validate scenarios/my-feature.yaml
```

Write steps as *action + expect*, see [scenario format](scenario-format.md) and [annotations](annotations.md).
