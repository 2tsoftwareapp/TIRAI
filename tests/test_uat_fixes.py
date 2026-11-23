import json
import tempfile
import types
from pathlib import Path
from types import SimpleNamespace

import pytest

from tirai import mcp, ocr, runner

ROOT = Path(__file__).resolve().parents[1]


def test_phone_rule_ignores_dates_and_timestamps():
    rx = ocr.rules_regex(["phone"])
    assert not rx.search("Recorded 2026-11-23 06:59:09")
    assert not rx.search("2026-11-23")
    assert rx.search("call +84 912 345 678").group(0) == "+84 912 345 678"
    assert rx.search("(028) 3822-1234")


def test_db_expect_infers_columns_from_expected_rows(monkeypatch):
    monkeypatch.setattr(runner.dbq, "query", lambda dsn, sql: [("LOCKED", 5)])
    me = SimpleNamespace(sc={"databases": {"default": {"dsn": "sqlite:///x"}}}, vars={}, saved={})
    arg = {"sql": "SELECT status, failed FROM users", "rows": [{"status": "LOCKED", "failed": 5}]}
    assert runner.Runner.check_db(me, arg)["ok"]
    arg["save"] = {"st": "status"}
    runner.Runner.check_db(me, arg)
    assert me.vars["st"] == "LOCKED"


def test_mcp_exposes_every_evidence_command():
    assert {"sign", "export", "scan_pii", "index", "from_spec"} <= set(mcp.TOOLS)
    assert mcp.TOOLS["export"][2]({"dir": "e", "formats": ["junit"]}) == ["export", "e", "--format", "junit"]
    assert mcp.TOOLS["verify"][2]({"dir": "e", "pubkey": "k.pub"}) == ["verify", "e", "--pubkey", "k.pub"]


def test_skill_scenario_reference_matches_docs():
    ref = ROOT / "skills/tirai-evidence/references/scenario.md"
    assert ref.read_text(encoding="utf-8") == (ROOT / "docs/scenario-format.md").read_text(encoding="utf-8")


class _DbxTab:
    def __init__(self, current, options=("shop", "other")):
        self.current, self.options, self.clicked = current, options, []

    def evaluate(self, tab, expr):
        if expr.endswith(".click()"):
            self.clicked.append("trigger")
            return None
        if "popover-content" in expr:
            hit = next((o for o in self.options if json.dumps(o) in expr), None)
            self.clicked.append(hit)
            return bool(hit)
        return self.current


def _dbx_runner(tab):
    return SimpleNamespace(tabs={"db": "t1"}, b=tab, pause=lambda s: None)


def test_dbx_editor_without_connection_fails_clearly():
    me = _dbx_runner(_DbxTab("Select connection"))
    with pytest.raises(runner.ScenarioError, match=r"tabs\.db\.dbx\.connection"):
        runner.Runner.dbx_select_connection(me, "db", {})


def test_dbx_selects_connect_name_and_skips_when_already_selected():
    tab = _DbxTab("Select connection")
    runner.Runner.dbx_select_connection(_dbx_runner(tab), "db", {"connect": {"name": "shop"}})
    assert tab.clicked == ["trigger", "shop"]
    same = _DbxTab("shop")
    runner.Runner.dbx_select_connection(_dbx_runner(same), "db", {"connection": "shop"})
    assert same.clicked == []
    with pytest.raises(runner.ScenarioError, match="not found: nope"):
        runner.Runner.dbx_select_connection(_dbx_runner(_DbxTab("shop")), "db", {"connection": "nope"})


def test_eval_action_runs_js_and_fails_on_false():
    from tirai import scenario as sc_mod

    assert "eval" in sc_mod.ACTIONS
    calls = []

    class B:
        def evaluate(self, tid, expr):
            calls.append(expr)
            return expr != "false"

    me = types.SimpleNamespace(tabs={"app": "t1"}, b=B(), apply_privacy=lambda tab: None, pause=lambda s: None, sc={})
    runner.Runner.do_action(me, "app", {"eval": "localStorage.setItem('k','v')"})
    assert calls == ["localStorage.setItem('k','v')"]
    with pytest.raises(runner.ScenarioError, match="eval returned false"):
        runner.Runner.do_action(me, "app", {"eval": "false"})


def test_verify_accepts_out(tmp_path, capsys):
    from tirai import cli, report

    (tmp_path / "a.txt").write_text("x")
    report.write_manifest(tmp_path)
    with pytest.raises(SystemExit) as done:
        cli.main(["verify", "--out", str(tmp_path)])
    assert done.value.code == 0
    assert "evidence intact" in capsys.readouterr().out


def test_dbx_moves_off_a_port_held_by_another_service(monkeypatch, capsys):
    from tirai import cli, system

    monkeypatch.setattr(system, "dbx_running", lambda url=None, timeout=2: False)
    monkeypatch.setattr(system, "dbx_web_bin", lambda: None)
    monkeypatch.setattr(system, "dbx_docker", lambda: None)
    monkeypatch.setattr(cli, "_port_busy", lambda p: p == 4224)
    cli.cmd_dbx(types.SimpleNamespace(port=4224, detach=True))
    assert "not installed" in capsys.readouterr().out  # no DBX install: port logic not triggered

    started = []
    monkeypatch.setattr(system, "dbx_web_bin", lambda: "/x/dbx-web")
    monkeypatch.setattr(system, "dbx_package_root", lambda b: Path("/x"))
    import subprocess
    import urllib.request

    monkeypatch.setattr(subprocess, "Popen", lambda cmd, env, **k: started.append(env["DBX_PORT"]))
    monkeypatch.setattr(urllib.request, "urlopen", lambda url, timeout=2: None)
    monkeypatch.setattr(system, "TIRAI_HOME", Path(tempfile.mkdtemp()))
    assert cli.cmd_dbx(types.SimpleNamespace(port=4224, detach=True)) == 0
    out = capsys.readouterr().out
    assert started == ["4225"] and "DBX_URL=http://127.0.0.1:4225/" in out


def test_setup_skips_sudo_without_terminal(monkeypatch, capsys):
    from tirai import bootstrap

    monkeypatch.setattr(bootstrap, "sudo_ready", lambda: False)
    ran = []
    monkeypatch.setattr(bootstrap.subprocess, "run", lambda *a, **k: ran.append(a))
    assert bootstrap.Setup(yes=True).execute(["sudo", "apt-get", "install", "-y", "x"]) is False
    assert ran == [] and "sudo needs a password" in capsys.readouterr().out
