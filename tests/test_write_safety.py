"""Steps that write data: {{run_id}}, database reset/snapshot/restore hooks, browser checkpoints for --from-step."""

import json
import re
import sys

import pytest
from test_runner import FakeDriver

from tirai import runner, scenario
from tirai.scenario import ScenarioError

PY = f'"{sys.executable}" -c'


def sc(databases=None, cleanup=None, steps=None):
    out = {"name": "w", "tabs": {"app": {"url": "http://a.test/"}}}
    out["steps"] = steps or [
        {"id": "S1", "tab": "app", "title": "log in", "expect": [{"visible": "#a"}]},
        {"id": "S2", "tab": "app", "title": "save", "writes": "creates an order",
         "actions": [{"fill": {"selector": "#code", "value": "A-1"}}], "expect": [{"visible": "#a"}]},
    ]  # fmt: skip
    if databases:
        out["databases"] = databases
    if cleanup:
        out["cleanup"] = cleanup
    return out


def test_run_id_is_short_and_unique():
    ids = {runner.new_run_id() for _ in range(50)}
    assert len(ids) == 50 and all(re.fullmatch(r"\d{10}[0-9a-f]{4}", i) for i in ids)


def test_write_safety_lists_steps_nothing_protects():
    assert scenario.write_safety(sc()) == ["S2"]
    assert scenario.write_safety(sc(cleanup=[{"tab": "app", "actions": []}])) == []
    assert scenario.write_safety(sc(databases={"default": {"dsn": "x", "reset": "true"}})) == []
    unique = sc()
    unique["steps"][1]["actions"][0]["fill"]["value"] = "A-{{run_id}}"
    assert scenario.write_safety(unique) == []


def test_validate_database_hooks():
    def errs(db):
        return [e for e in scenario.validate(sc(databases={"default": {"dsn": "x", **db}})) if "databases" in e]

    assert errs({"snapshot": "cp a {snapshot}", "restore": "cp {snapshot} a", "reset": "true"}) == []
    assert errs({"snapshot": "cp a {snapshot}"}) == ["databases.default: snapshot and restore go together"]
    assert errs({"snapshot": "cp a b", "restore": "cp b a"})  # no {snapshot}: every snapshot would overwrite
    assert errs({"reset": ""})


def test_db_hook_runs_in_the_shell_with_the_snapshot_name(tmp_path):
    marker = tmp_path / "m.txt"
    cmd = f"{PY} \"open(r'{marker}','w').write('{{snapshot}}')\""
    runner.run_db_hook({"databases": {"default": {"snapshot": cmd}}}, "snapshot", "tirai_ab_s2")
    assert marker.read_text() == "tirai_ab_s2"
    bad = {"databases": {"main": {"reset": f"{PY} \"import sys; print('no access'); sys.exit(3)\""}}}
    with pytest.raises(ScenarioError, match=r"databases.main.reset failed \(exit 3\): no access"):
        runner.run_db_hook(bad, "reset")


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX shell expands $VAR")
def test_db_hook_takes_secrets_from_the_environment(tmp_path, monkeypatch):
    monkeypatch.setenv("TIRAI_TEST_DB", str(tmp_path / "db.txt"))
    runner.run_db_hook({"databases": {"d": {"reset": 'echo reset > "$TIRAI_TEST_DB"'}}}, "reset")
    assert (tmp_path / "db.txt").read_text().strip() == "reset"


class StateDriver(FakeDriver):
    def tab_list(self):
        return [{"id": "t1", "url": "http://a.test/orders"}]

    def state_save(self, path):
        self._log("state_save", str(path))
        path.write_text("{}")

    def state_load(self, path):
        self._log("state_load", str(path))


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setattr(runner, "TIRAI_HOME", tmp_path / "home")
    monkeypatch.setenv("TIRAI_TIMING_SCALE", "0")
    monkeypatch.setenv("TIRAI_EXPECT_TIMEOUT", "0")
    return tmp_path / "home"


def test_recording_snapshots_write_steps_and_saves_checkpoints(tmp_path, home, monkeypatch):
    d = StateDriver()
    monkeypatch.setattr(runner, "make_driver", lambda *a, **k: d)
    log = tmp_path / "hooks.txt"
    hook = f"{PY} \"open(r'{log}','a').write('{{kind}} {{snapshot}};')\""
    dbs = {"default": {"dsn": "x", "reset": hook.replace("{kind}", "reset"), "snapshot": hook.replace("{kind}", "snap"),
                       "restore": hook.replace("{kind}", "restore")}}  # fmt: skip
    out = tmp_path / "record"
    tl = runner.run(sc(databases=dbs), out, record=True, hold=0)
    assert [s["status"] for s in tl["steps"]] == ["passed", "passed"]
    snap = runner.snapshot_name(out, "S2")
    assert tl["steps"][1]["snapshot"] == snap and log.read_text() == f"reset ;snap {snap};"
    ck = runner.load_checkpoint(out, "S1")
    assert ck["urls"] == {"app": "http://a.test/orders"} and tl["run_id"]
    assert not str(ck["state"]).startswith(str(out))  # log-in cookies stay out of the evidence folder

    # Re-record from S2 without a session: restore the snapshot taken before S2 wrote, resume from S1's checkpoint.
    d2 = StateDriver()
    monkeypatch.setattr(runner, "make_driver", lambda *a, **k: d2)
    tl2 = runner.run(sc(databases=dbs), out, record=True, hold=0, from_step="S2")
    # restore, then S2 runs again and re-takes its snapshot; no reset: the kept steps' data stays
    assert log.read_text() == f"reset ;snap {snap};restore {snap};snap {snap};"
    assert ("open_session", "http://a.test/orders") in d2.calls and any(c[0] == "state_load" for c in d2.calls)
    assert [s["id"] for s in tl2["steps"]] == ["S1", "S2"] and tl2["run_id"] == tl["run_id"]


def test_from_step_without_checkpoint_or_session_is_refused(tmp_path, home, monkeypatch):
    monkeypatch.setattr(runner, "make_driver", lambda *a, **k: FakeDriver())  # no state_save: like bsk
    out = tmp_path / "record"
    runner.run(sc(), out, record=True, hold=0)
    with pytest.raises(ScenarioError, match="no browser checkpoint after S1"):
        runner.run(sc(), out, record=True, hold=0, from_step="S2")
    assert json.loads((out / "timeline.json").read_text())["mode"] == "record"


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX permissions")
def test_checkpoint_files_are_private(tmp_path, home, monkeypatch):
    monkeypatch.setattr(runner, "make_driver", lambda *a, **k: StateDriver())
    out = tmp_path / "record"
    runner.run(sc(), out, record=True, hold=0)
    d = runner.checkpoint_dir(out)
    assert d.stat().st_mode & 0o777 == 0o700
    assert all(f.stat().st_mode & 0o777 == 0o600 for f in d.iterdir())


def test_from_step_in_a_popup_is_refused(tmp_path, home, monkeypatch):
    monkeypatch.setattr(runner, "make_driver", lambda *a, **k: StateDriver())
    out = tmp_path / "record"
    s = sc()
    runner.run(s, out, record=True, hold=0)
    s["tabs"]["win"] = {"popup": True, "match": "/order"}
    s["steps"][1]["tab"] = "win"
    with pytest.raises(ScenarioError, match="popup window"):
        runner.run(s, out, record=True, hold=0, from_step="S2")
