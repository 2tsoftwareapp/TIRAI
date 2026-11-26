"""settings.device/locale/timezone/color_scheme: validation, agent-browser wiring, read-back check, portrait frame."""

import json
import types

import pytest

from tirai import agentbrowser, compose, runner, scenario
from tirai.scenario import ScenarioError


def errs(settings):
    sc = {"name": "x", "tabs": {"app": {"url": "http://a.test/"}}, "steps": [], "settings": settings}
    return [e for e in scenario.validate(sc) if e.startswith("settings")]


def test_validate_emulation_settings():
    ok = {"device": "iPhone 14", "locale": "ja-JP", "timezone": "Asia/Tokyo", "color_scheme": "dark"}
    assert errs(ok) == []
    assert errs({"timezone": "UTC"}) == [] and errs({"timezone": "America/Argentina/Buenos_Aires"}) == []
    assert errs({"locale": "ja_JP"}) and errs({"timezone": "+09:00"}) and errs({"color_scheme": "blue"})
    assert errs({"device": ""})
    assert errs({"device": "Pixel 7", "viewport": {"width": 800, "height": 600}})
    sc = {"name": "x", "tabs": {"app": {"url": "http://a.test/"}, "db": {"url": "http://d.test/", "kind": "dbx"}},
          "steps": [], "settings": {"device": "Pixel 7"}}  # fmt: skip
    assert any("DBX grid" in e for e in scenario.validate(sc))


class Proc:
    def __init__(self, data):
        self.returncode, self.stderr = 0, ""
        self.stdout = json.dumps({"success": True, "data": data})


def test_agent_browser_applies_emulation(monkeypatch):
    calls = []

    def fake_run_text(cmd, timeout=None, input=None, env=None):
        calls.append((cmd, env))
        if "tab" in cmd and "list" in cmd:
            return Proc({"tabs": [{"tabId": "t1", "active": True}]})
        if "device" in cmd:
            return Proc({"device": "iPhone 14", "width": 390, "height": 844, "deviceScaleFactor": 3.0})
        return Proc({})

    monkeypatch.setattr(agentbrowser, "run_text", fake_run_text)
    monkeypatch.setattr(agentbrowser, "_bin", lambda: "ab")
    b = agentbrowser.AgentBrowser()
    b.emulation = {"device": "iPhone 14", "locale": "ja-JP", "timezone": "Asia/Tokyo", "color_scheme": "dark"}
    assert b.open_session("http://a.test/", "t") == "t1"
    cmds = [c for c, _ in calls]
    launch = next(c for c in cmds if "open" in c)
    assert launch[launch.index("--args") + 1] == "--lang=ja-JP,--accept-lang=ja-JP"
    assert all(env["TZ"] == "Asia/Tokyo" for _, env in calls)
    tail = [c[c.index("--json") + 1 :] for c in cmds if "--json" in c]
    assert ["set", "viewport", "390", "844", "1"] in tail  # pixel ratio 1: clicks land while recording
    assert ["set", "media", "dark"] in tail and ["reload"] in tail
    assert not any("--args" in c for c in cmds if "open" not in c)  # launch flags only on the launch


def test_emulation_needs_agent_browser():
    bsk = types.SimpleNamespace(name="bsk")
    with pytest.raises(ScenarioError, match="settings.device: needs the agent-browser driver"):
        runner.with_emulation(bsk, {"device": "iPhone 14"})
    assert runner.with_emulation(bsk, {}) is bsk


def check(seen, want):
    s = types.SimpleNamespace(emulation=want, emulation_seen=None, tabs={"app": "t1"})
    s.b = types.SimpleNamespace(evaluate=lambda tab, expr: seen)
    runner.Runner.check_emulation(s, "app")
    return s.emulation_seen


def test_check_emulation_reads_values_back():
    seen = check(["Asia/Tokyo", "ja-JP", True, "Mozilla/5.0 (iPhone)"], {"timezone": "Asia/Tokyo", "locale": "ja-jp"})
    assert seen["color_scheme"] == "dark" and seen["timezone"] == "Asia/Tokyo"
    with pytest.raises(ScenarioError, match="emulation not applied: timezone 'Asia/Tokyo' .*'UTC'"):
        check(["UTC", "en-US", False, "x"], {"timezone": "Asia/Tokyo"})
    with pytest.raises(ScenarioError, match="color_scheme 'dark'"):
        check(["UTC", "en-US", False, "x"], {"color_scheme": "dark"})


def test_emulation_goes_on_the_title_card():
    assert runner.emulation_meta({"timezone": "Asia/Tokyo", "color_scheme": "dark"}) == {
        "time zone": "Asia/Tokyo",
        "color scheme": "dark",
    }


def test_portrait_recording_gets_a_landscape_frame(monkeypatch, tmp_path):
    monkeypatch.delenv("TIRAI_VIDEO_SIZE", raising=False)
    monkeypatch.setattr(compose, "video_size", lambda path: (390, 844))
    assert compose.frame_size({"steps": [{"segment": "seg-01-app.mp4"}]}, tmp_path) == (1500, 844)
    monkeypatch.setattr(compose, "video_size", lambda path: (1280, 720))
    assert compose.frame_size({"steps": [{"segment": "seg-01-app.mp4"}]}, tmp_path) == (1280, 720)


def test_long_title_card_and_header_lines_stay_on_one_line():
    steps = [{"id": "S1", "tab": "app", "title": "T " * 200, "status": "passed", "final_start": 3, "final_end": 4}]
    tl = {"scenario": "s", "created": "now", "tabs": {"app": {"label": "App"}}, "steps": steps,
          "meta": {f"k{i}": "value" * 3 for i in range(20)}}  # fmt: skip
    ass = compose.build_ass(tl, (1280, 720), 3.0)
    meta = next(line for line in ass.splitlines() if "k0: value" in line)
    hdr = next(line for line in ass.splitlines() if ",Hdr," in line)
    assert meta.endswith("…") and hdr.endswith("…")
