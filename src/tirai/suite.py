"""`tirai suite`: run many scenarios, each in its own `tirai` process, then write one summary.

Each scenario gets its own process, so agent-browser sessions (named after the pid) never collide when
`--parallel` runs several at once. Results land in `<out>/<name>/`, plus `<out>/suite.json`,
`<out>/suite.md`, `<out>/junit.xml` (one testsuite per scenario) and `<out>/index.html`.
"""

import json
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from xml.etree import ElementTree as ET

import yaml

from tirai import export, index

SKIP_DIRS = {".git", ".venv", "node_modules", "evidence", "__pycache__"}


def is_scenario(path):
    """A runnable scenario has top-level `tabs:` and `steps:`; include-only fragments do not."""
    try:
        data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return False
    return isinstance(data, dict) and "tabs" in data and "steps" in data


def discover(paths):
    """Scenario files under `paths` (files are taken as given; directories are searched recursively)."""
    found = []
    for p in map(Path, paths):
        if p.is_file():
            found.append(p)
            continue
        if not p.is_dir():
            raise FileNotFoundError(f"no such file or directory: {p}")
        for f in sorted([*p.rglob("*.yaml"), *p.rglob("*.yml")]):
            if not SKIP_DIRS.intersection(f.relative_to(p).parts[:-1]) and is_scenario(f):
                found.append(f)
    return list(dict.fromkeys(found))


def slugs(files):
    """Short unique folder names: the file stem, prefixed by parent folders only when stems clash."""
    out, used = [], set()
    for f in files:
        parts = Path(f).with_suffix("").parts
        n = 1
        name = parts[-1]
        while name in used:
            n += 1
            name = "-".join(parts[-n:]) if n <= len(parts) else f"{parts[-1]}-{n}"
        used.add(name)
        out.append(name)
    return out


def tirai_cmd():
    """How to start another `tirai` (a frozen binary runs itself; a Python install uses `-m tirai`)."""
    return [sys.executable] if getattr(sys, "frozen", False) else [sys.executable, "-m", "tirai"]


def timeline_of(run_dir):
    for rel in ("record/timeline.final.json", "record/timeline.json", "dry-run/timeline.json"):
        f = Path(run_dir) / rel
        if f.is_file():
            return f
    return None


def run_one(scenario, run_dir, record, extra):
    run_dir.mkdir(parents=True, exist_ok=True)
    cmd = [*tirai_cmd(), *(["record"] if record else ["run", "--dry-run"]), str(scenario), "--out", str(run_dir)]
    t0 = time.monotonic()
    with open(run_dir / "suite.log", "w", encoding="utf-8") as log:
        code = subprocess.run([*cmd, *extra], stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL).returncode
    res = {"scenario": str(scenario), "dir": run_dir.name, "exit": code, "seconds": round(time.monotonic() - t0, 1)}
    tl_file = timeline_of(run_dir)
    if tl_file:
        tl = json.loads(tl_file.read_text(encoding="utf-8"))
        res["name"] = tl["scenario"]
        res["timeline"] = str(tl_file.relative_to(run_dir.parent))
        res["passed"] = sum(s["status"] == "passed" for s in tl["steps"])
        res["total"] = tl.get("total_steps", len(tl["steps"]))
        if (tl_file.parent / "final.mp4").is_file():
            res["video"] = str((tl_file.parent / "final.mp4").relative_to(run_dir.parent))
    else:
        tail = (run_dir / "suite.log").read_text(encoding="utf-8", errors="replace").strip().splitlines()[-5:]
        res["error"] = " | ".join(tail) or f"exit {code}"
    res["status"] = "passed" if code == 0 and tl_file and res["passed"] == res["total"] else "failed"
    return res


def junit(results, out):
    """One <testsuite> per scenario; a scenario that never wrote a timeline becomes one errored testcase."""
    root = ET.Element("testsuites", name="tirai suite")
    for r in results:
        tl_file = out / r["timeline"] if r.get("timeline") else None
        if tl_file:
            tl = json.loads(tl_file.read_text(encoding="utf-8"))
            root.append(ET.fromstring(export.junit(tl, video=r.get("video", "final.mp4")).split("\n", 1)[1]))
            continue
        suite = ET.SubElement(root, "testsuite", name=r["scenario"], tests="1", failures="0", errors="1")
        case = ET.SubElement(suite, "testcase", classname=r["scenario"], name="run", time=str(r["seconds"]))
        ET.SubElement(case, "error", message=r["error"][:300]).text = f"see {r['dir']}/suite.log"
    ET.indent(root)
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(root, encoding="unicode") + "\n"


def markdown(results):
    ok = sum(r["status"] == "passed" for r in results)
    lines = [
        f"## TIRAI suite: {ok}/{len(results)} scenarios passed",
        "",
        "| Scenario | Result | Steps | Time | Evidence |",
        "|---|---|---|---|---|",
    ]
    for r in results:
        steps = f"{r['passed']}/{r['total']}" if "total" in r else "-"
        mark = "PASS" if r["status"] == "passed" else "FAIL"
        lines.append(f"| {r.get('name', r['scenario'])} | {mark} | {steps} | {r['seconds']}s | `{r['dir']}/` |")
    return "\n".join(lines) + "\n"


def db_hook_users(files):
    """Scenarios with databases.*.reset/snapshot/restore: run at once, one's reset or restore would wipe data
    another is recording against."""
    found = []
    for f in files:
        data = yaml.safe_load(Path(f).read_text(encoding="utf-8")) or {}
        dbs = data.get("databases") or {}
        if any(isinstance(d, dict) and (d.get("reset") or d.get("snapshot") or d.get("restore")) for d in dbs.values()):
            found.append(Path(f).name)
    return found


def run(paths, out, record=True, parallel=1, extra=(), on_done=None):
    files = discover(paths)
    if not files:
        raise FileNotFoundError("no scenario files found (a scenario has top-level `tabs:` and `steps:`)")
    hooked = db_hook_users(files) if parallel > 1 else []
    if hooked:
        raise ValueError(
            f"--parallel: {', '.join(hooked)} reset/snapshot/restore a database; run the suite without --parallel"
        )
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    jobs = list(zip(files, slugs(files), strict=True))

    def one(job):
        res = run_one(job[0], out / job[1], record, list(extra))
        if on_done:
            on_done(res)
        return res

    with ThreadPoolExecutor(max_workers=max(1, parallel)) as pool:
        results = list(pool.map(one, jobs))
    summary = {"created": time.strftime("%Y-%m-%d %H:%M:%S"), "mode": "record" if record else "dry-run"}
    summary["scenarios"] = results
    (out / "suite.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    (out / "suite.md").write_text(markdown(results), encoding="utf-8")
    (out / "junit.xml").write_text(junit(results, out), encoding="utf-8")
    runs = [str((out / r["timeline"]).parent) for r in results if r.get("timeline")]
    if runs:
        index.write(runs, str(out / "index.html"))  # the final run of each scenario, not its dry-run too
    return results
