from pathlib import Path
from types import SimpleNamespace

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
