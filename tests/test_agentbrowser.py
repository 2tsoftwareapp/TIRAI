import json
import subprocess

import pytest

from tirai import agentbrowser as ab
from tirai.bsk import Bsk, DriverError


class FakeCli:
    def __init__(self, replies):
        self.replies, self.calls = replies, []

    def __call__(self, cmd, timeout=None, input=None, env=None):
        self.calls.append((cmd, input))
        reply = self.replies.get(cmd[4] if len(cmd) > 4 else "", {"success": True, "data": {}})
        code = 0 if reply.get("success") else 1
        return subprocess.CompletedProcess(cmd, code, json.dumps(reply), "")


@pytest.fixture
def cli(monkeypatch):
    fake = FakeCli({})
    monkeypatch.setattr(ab, "run_text", fake)
    monkeypatch.setattr(ab, "_bin", lambda: "agent-browser")
    return fake


def test_key_and_timeout_translation():
    assert ab._key("Ctrl+Enter") == "Control+Enter"
    assert ab._key("Cmd+K") == "Meta+K"
    assert ab._ms("10s") == "10000" and ab._ms("250ms") == "250" and ab._ms(3) == "3000"


def test_commands_target_session_and_switch_tabs(cli):
    b = ab.AgentBrowser("s1", cursor=False)
    b.active = "t1"
    b.fill("t1", "#email", "a@b.c")
    b.click("t2", "#go")
    cmds = [c for c, _ in cli.calls]
    assert cmds[0] == ["agent-browser", "--session", "s1", "--json", "fill", "#email", "--", "a@b.c"]
    assert cmds[1][4:] == ["tab", "t2"] and cmds[2][4:] == ["click", "#go"]
    assert b.active == "t2"


def test_evaluate_uses_stdin_and_returns_result(cli):
    cli.replies["eval"] = {"success": True, "data": {"result": {"a": 1}}}
    assert ab.AgentBrowser("s").evaluate(None, "({a:1})") == {"a": 1}
    assert cli.calls[-1][1] == "({a:1})"


def test_console_is_bsk_shaped(cli):
    msgs = [{"type": "log", "text": "hi"}, {"type": "error", "text": "boom"}]
    cli.replies["console"] = {"success": True, "data": {"messages": msgs}}
    out = ab.AgentBrowser("s").console(None, since=1)
    assert out == {"entries": [{"text": "boom", "level": "error"}], "next_since": 2}


def test_failure_raises_driver_error(cli):
    cli.replies["click"] = {"success": False, "error": "Element not found: #nope"}
    with pytest.raises(DriverError, match="Element not found"):
        ab.AgentBrowser("s").click(None, "#nope")


def test_record_start_stop(cli, tmp_path):
    b = ab.AgentBrowser("s", cursor=True)
    rec = b.video_start(None)
    assert cli.calls[-1][0][4:] == ["record", "start", rec, "--cursor"]
    open(rec, "wb").write(b"x")
    out = b.video_stop(rec, str(tmp_path / "seg.mp4"))
    assert open(out, "rb").read() == b"x"


def test_make_driver_selection(monkeypatch):
    monkeypatch.delenv("TIRAI_DRIVER", raising=False)
    monkeypatch.setattr(ab, "agent_browser_bin", lambda: "/x/agent-browser")
    assert isinstance(ab.make_driver(), ab.AgentBrowser)
    assert isinstance(ab.make_driver("bsk"), Bsk)
    monkeypatch.setenv("TIRAI_DRIVER", "bsk")
    assert isinstance(ab.make_driver(), Bsk)
    with pytest.raises(DriverError):
        ab.make_driver("selenium")
