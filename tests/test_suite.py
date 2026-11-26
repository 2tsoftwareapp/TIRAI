"""`tirai suite`: discovery, per-scenario processes, aggregate junit/summary."""

import json
import sys
import textwrap
from xml.etree import ElementTree as ET

import pytest

from tirai import cli, suite

SCENARIO = "name: {name}\ntabs: {{ app: {{ url: 'http://a.test/' }} }}\nsteps: []\n"

# Stands in for `tirai record|run --dry-run <file> --out <dir>`: writes a timeline whose step status comes
# from the scenario name ("fail" -> one failed step), or exits without a timeline when the name says "crash".
FAKE_TIRAI = textwrap.dedent(
    """
    import json, sys, pathlib, yaml
    args = sys.argv[1:]
    record = args[0] == "record"
    scenario = args[1] if record else args[2]
    out = pathlib.Path(args[args.index("--out") + 1])
    name = yaml.safe_load(open(scenario))["name"]
    if "crash" in name:
        print("error: agent-browser not found")
        sys.exit(1)
    d = out / ("record" if record else "dry-run")
    d.mkdir(parents=True)
    status = "failed" if "fail" in name else "passed"
    steps = [{"id": "S1", "title": "t", "tab": "app", "status": status, "checks": []}]
    tl = {"scenario": name, "mode": "record" if record else "dry-run", "created": "2026-11-26 10:00:00",
          "driver": "fake", "tabs": {"app": {"label": "App"}}, "steps": steps, "total_steps": 1}
    (d / "timeline.json").write_text(json.dumps(tl))
    sys.exit(0 if status == "passed" else 1)
    """
)


@pytest.fixture
def fake_tirai(tmp_path, monkeypatch):
    script = tmp_path / "fake_tirai.py"
    script.write_text(FAKE_TIRAI)
    monkeypatch.setattr(suite, "tirai_cmd", lambda: [sys.executable, str(script)])
    return script


def write(path, name):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(SCENARIO.format(name=name))
    return path


def test_discover_skips_fragments_and_evidence(tmp_path):
    a = write(tmp_path / "s" / "login.yaml", "login")
    b = write(tmp_path / "s" / "sub" / "order.yml", "order")
    (tmp_path / "s" / "steps-common.yaml").write_text("- id: S1\n  tab: app\n")  # include fragment
    write(tmp_path / "s" / "evidence" / "old.yaml", "old")
    assert suite.discover([tmp_path / "s"]) == [a, b]
    with pytest.raises(FileNotFoundError):
        suite.discover([tmp_path / "missing"])


def test_slugs_are_unique():
    assert suite.slugs(["a/login.yaml", "b/login.yaml", "order.yaml"]) == ["login", "b-login", "order"]


def test_suite_runs_each_scenario_and_aggregates(tmp_path, fake_tirai):
    src = tmp_path / "s"
    for n in ("ok", "fail", "crash"):
        write(src / f"{n}.yaml", n)
    out = tmp_path / "out"
    results = suite.run([src], out, record=True, parallel=3)
    by = {r["dir"]: r for r in results}
    assert by["ok"]["status"] == "passed" and by["ok"]["passed"] == 1
    assert by["fail"]["status"] == "failed" and by["fail"]["exit"] == 1
    assert by["crash"]["status"] == "failed" and "agent-browser not found" in by["crash"]["error"]
    root = ET.parse(out / "junit.xml").getroot()
    names = [s.get("name") for s in root]
    assert root.tag == "testsuites" and sorted(names) == sorted(["ok", "fail", str(src / "crash.yaml")])
    assert root.find("testsuite[@name='fail']").get("failures") == "1"
    assert "1/3 scenarios passed" in (out / "suite.md").read_text()
    assert json.loads((out / "suite.json").read_text())["mode"] == "record"
    page = (out / "index.html").read_text()
    assert page.count('data-status="') == 2  # ok + fail recordings; never their dry-runs as extra rows
    assert "agent-browser not found" in (out / "crash" / "suite.log").read_text()


def test_suite_dry_run_command(tmp_path, fake_tirai, capsys):
    write(tmp_path / "ok.yaml", "ok")
    with pytest.raises(SystemExit) as code:
        cli.main(["suite", str(tmp_path / "ok.yaml"), "--dry-run", "--out", str(tmp_path / "out")])
    assert code.value.code == 0
    assert (tmp_path / "out" / "ok" / "dry-run" / "timeline.json").is_file()
    assert "1/1 scenarios passed" in capsys.readouterr().out


def test_parallel_refused_with_bsk(tmp_path, capsys):
    write(tmp_path / "ok.yaml", "ok")
    with pytest.raises(SystemExit) as code:
        cli.main(["suite", str(tmp_path), "-j", "2", "--driver", "bsk"])
    assert code.value.code == 2


def test_parallel_refused_when_scenarios_reset_a_database(tmp_path, fake_tirai):
    write(tmp_path / "a.yaml", "a")
    (tmp_path / "b.yaml").write_text(SCENARIO.format(name="b") + "databases: { default: { dsn: x, reset: 'true' } }\n")
    with pytest.raises(ValueError, match="b.yaml reset/snapshot/restore a database"):
        suite.run([tmp_path], tmp_path / "out", parallel=2)
    assert len(suite.run([tmp_path], tmp_path / "out", parallel=1)) == 2
