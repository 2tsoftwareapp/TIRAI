import json

import pytest

from tirai import runner
from tirai.bsk import DriverError


class FakeDriver:
    """Records calls; `evaluate` answers expectation probes with `self.ok` and everything else with True."""

    name = "fake"

    def __init__(self, ok=True, fail_on=None):
        self.session = None
        self.calls = []
        self.ok = ok
        self.fail_on = fail_on
        self.init_scripts = []
        self.n = 0

    def _log(self, *call):
        self.calls.append(call)
        if self.fail_on and call[0] == self.fail_on:
            raise DriverError(f"{call[0]} boom")

    def open_session(self, url, scope):
        self.session = scope
        self._log("open_session", url)
        return "t1"

    def tab_create(self, url):
        self.n += 1
        self._log("tab_create", url)
        return f"t{self.n + 1}"

    def close_session(self):
        self._log("close_session")

    def sync(self, tab, retries=None):
        return {}

    def tab_select(self, tab):
        self._log("tab_select", tab)

    def video_start(self, tab, duration=None):
        self._log("video_start", tab)
        return f"rec-{tab}"

    def video_stop(self, rid, path):
        self._log("video_stop", rid, path)

    def navigate(self, tab, url):
        self._log("navigate", tab, url)

    def fill(self, tab, selector, value):
        self._log("fill", tab, selector, value)

    def click(self, tab, selector):
        self._log("click", tab, selector)

    def press(self, tab, key, selector=None):
        self._log("press", tab, key, selector)

    def screenshot(self, tab, path):
        self._log("screenshot", tab)
        return path

    def console(self, tab, since=None):
        return {"entries": [], "next_since": 0}

    def evaluate(self, tab, expr):
        if expr.startswith("(()=>{const e=document.querySelector(") and "return e?" in expr:
            return "ORD-42"  # save
        if "return [" in expr or expr.startswith("[location"):
            return [self.ok, "actual"]
        self._log("evaluate", tab, expr[:40])
        return []


def scenario(**extra):
    sc = {
        "name": "fake",
        "tabs": {"app": {"url": "http://app.test/"}, "db": {"url": "http://dbx.test/", "privacy": False}},
        "steps": [
            {
                "id": "S1",
                "tab": "app",
                "title": "Login",
                "actions": [{"fill": {"selector": "#email", "value": "a@b.c"}}, {"click": "#go"}],
                "expect": [{"visible": "#welcome"}],
            },
            {"id": "S2", "tab": "db", "title": "DB", "actions": [], "expect": [{"visible": "canvas"}]},
            {"id": "S3", "tab": "app", "title": "Back", "actions": [], "expect": [{"url_contains": "/home"}]},
        ],
    }
    sc.update(extra)
    return sc


@pytest.fixture
def fake(monkeypatch):
    holder = {}

    def make(name=None, session=None, headed=None):
        holder["d"] = holder.get("proto") or FakeDriver()
        return holder["d"]

    monkeypatch.setattr(runner, "make_driver", make)
    monkeypatch.setenv("TIRAI_TIMING_SCALE", "0")
    monkeypatch.setenv("TIRAI_EXPECT_TIMEOUT", "0")
    return holder


def test_dry_run_passes_and_writes_timeline(fake, tmp_path):
    tl = runner.run(scenario(), tmp_path, record=False, hold=0)
    d = fake["d"]
    assert [s["status"] for s in tl["steps"]] == ["passed"] * 3
    assert tl["driver"] == "fake" and tl["segments"] == []
    assert ("fill", "t1", "#email", "a@b.c") in d.calls and ("click", "t1", "#go") in d.calls
    assert d.calls[0] == ("open_session", "http://app.test/") and d.calls[-1] == ("close_session",)
    assert json.loads((tmp_path / "timeline.json").read_text())["total_steps"] == 3


def test_record_makes_one_segment_per_tab_block(fake, tmp_path):
    tl = runner.run(scenario(), tmp_path, record=True, hold=0)
    assert [s["tab"] for s in tl["segments"]] == ["app", "db", "app"]
    assert [s["file"] for s in tl["segments"]] == ["seg-01-app.mp4", "seg-02-db.mp4", "seg-03-app.mp4"]
    starts = [c for c in fake["d"].calls if c[0] == "video_start"]
    stops = [c for c in fake["d"].calls if c[0] == "video_stop"]
    assert len(starts) == len(stops) == 3
    assert all(s["segment"] for s in tl["steps"]) and tl["steps"][1]["start"] is not None


def test_failed_expectation_stops_recording_run(fake, tmp_path):
    fake["proto"] = FakeDriver(ok=False)
    tl = runner.run(scenario(), tmp_path, record=True, hold=0)
    assert [s["status"] for s in tl["steps"]] == ["failed"]  # record mode stops at the first failure
    assert tl["steps"][0]["checks"][0] == {"type": "visible", "expected": "#welcome", "actual": "actual", "ok": False}
    dry = runner.run(scenario(), tmp_path, record=False, hold=0)
    assert len(dry["steps"]) == 3


def test_driver_error_marks_step_error(fake, tmp_path):
    fake["proto"] = FakeDriver(fail_on="click")
    tl = runner.run(scenario(), tmp_path, record=False, hold=0)
    assert tl["steps"][0]["status"] == "error" and "click boom" in tl["steps"][0]["error"]


def test_save_feeds_later_actions(fake, tmp_path):
    sc = scenario()
    sc["steps"][0]["actions"].append({"save": {"name": "order", "selector": "#order"}})
    sc["steps"][2]["actions"] = [{"fill": {"selector": "#q", "value": "{{order}}"}}]
    tl = runner.run(sc, tmp_path, record=False, hold=0)
    assert tl["steps"][0]["saved"] == {"order": "ORD-42"}
    assert ("fill", "t1", "#q", "ORD-42") in fake["d"].calls


def test_privacy_init_script_limited_to_masked_origins(fake, tmp_path):
    runner.run(scenario(privacy={"mask": ["email"]}), tmp_path, record=False, hold=0)
    (script,) = fake["d"].init_scripts
    assert '["http://app.test"]' in script and "dbx.test" not in script
    assert "__ann.mask(" in script and "DOMContentLoaded" in script


def test_no_init_script_without_privacy(fake, tmp_path):
    runner.run(scenario(), tmp_path, record=False, hold=0)
    assert fake["d"].init_scripts == []


def test_dbx_connect_provisions_before_tab_opens(fake, tmp_path, monkeypatch):
    seen = []
    monkeypatch.setattr("tirai.dbxconn.connect", lambda url, dsn, name, pw, host: seen.append((url, dsn, name, host)))
    monkeypatch.setenv("DBX_PASSWORD", "pw")
    sc = scenario(databases={"default": {"dsn": "postgresql://ro:x@db:5432/shop"}})
    sc["tabs"]["db"]["kind"] = "dbx"
    sc["tabs"]["db"]["dbx"] = {"connect": {"name": "shop", "host": "evpg"}}
    runner.run(sc, tmp_path, record=False, hold=0)
    assert seen == [("http://dbx.test/", "postgresql://ro:x@db:5432/shop", "shop", "evpg")]


def test_session_closed_when_a_tab_fails_to_load(monkeypatch, tmp_path):
    d = FakeDriver()
    monkeypatch.setattr(
        d, "evaluate", lambda tab, expr: "chrome-error://chromewebdata/" if expr == "location.href" else None
    )
    monkeypatch.setattr(runner, "make_driver", lambda *a, **k: d)
    import pytest

    with pytest.raises(RuntimeError, match="did not load"):
        runner.run(scenario(), tmp_path, record=False, hold=0)
    assert d.calls[-1] == ("close_session",)
