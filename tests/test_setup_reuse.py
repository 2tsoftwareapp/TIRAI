import json
import subprocess

from tirai import bootstrap, system


def _ffmpeg(path, version):
    path.write_text(f"#!/bin/sh\necho 'ffmpeg version {version} Copyright'\n")
    path.chmod(0o755)
    return path


def test_ffmpeg_bin_picks_new_enough_copy_anywhere_on_path(tmp_path, monkeypatch):
    old, new = tmp_path / "old", tmp_path / "new"
    old.mkdir(), new.mkdir()
    _ffmpeg(old / "ffmpeg", "4.4.2")
    _ffmpeg(new / "ffmpeg", "7.1")
    (new / "ffprobe").write_text("")
    monkeypatch.delenv("FFMPEG_BIN", raising=False)
    monkeypatch.delenv("FFPROBE_BIN", raising=False)
    monkeypatch.setattr(system, "TIRAI_BIN", tmp_path / "none")
    monkeypatch.setattr(system, "_ffmpeg_dirs", lambda: [])
    monkeypatch.setenv("PATH", f"{old}:{new}")
    assert system.ffmpeg_bin() == str(new / "ffmpeg")
    assert system.ffprobe_bin() == str(new / "ffprobe")
    assert system.tool_env()["PATH"].startswith(str(new))
    monkeypatch.setenv("PATH", str(old))
    assert system.ffmpeg_bin() == str(old / "ffmpeg")  # only an old one: still reported, doctor flags it


def test_find_dbx_prefers_running_server_then_binary_then_docker(monkeypatch):
    monkeypatch.setattr(system, "dbx_running", lambda url=None: True)
    assert system.find_dbx()[0] == "running"
    monkeypatch.setattr(system, "dbx_running", lambda url=None: False)
    monkeypatch.setattr(system, "dbx_web_bin", lambda: "/opt/dbx/dbx-web")
    assert system.find_dbx() == ("binary", "/opt/dbx/dbx-web")
    monkeypatch.setattr(system, "dbx_web_bin", lambda: None)
    monkeypatch.setattr(system, "dbx_docker", lambda: ("docker", [("dbx", False)], True))
    assert system.find_dbx() == ("docker", "container dbx (stopped)")
    monkeypatch.setattr(system, "dbx_docker", lambda: ("docker", [], True))
    assert system.find_dbx() == ("docker", "image t8y2/dbx")
    monkeypatch.setattr(system, "dbx_docker", lambda: None)
    assert system.find_dbx() is None


def test_dbx_docker_lists_containers_of_any_tag(monkeypatch):
    def fake(cmd, **kw):
        out = "dbx\tt8y2/dbx:latest\trunning\nother\tpostgres:16\trunning\nold\tt8y2/dbx:0.6\texited\n"
        return subprocess.CompletedProcess(cmd, 0, out if cmd[1] == "ps" else "", "")

    monkeypatch.setattr(system, "find_bin", lambda name, *a: "/usr/bin/docker")
    monkeypatch.setattr(system, "run_text", fake)
    assert system.dbx_docker() == ("/usr/bin/docker", [("dbx", True), ("old", False)], False)


def test_dbx_package_root(tmp_path):
    (tmp_path / "bin").mkdir()
    assert system.dbx_package_root(tmp_path / "bin" / "dbx-web-bin") == tmp_path.resolve()
    assert system.dbx_package_root(tmp_path / "dbx-web.exe") == tmp_path.resolve()


def _doctor(monkeypatch, checks):
    out = json.dumps({"checks": [{"id": k, "status": v} for k, v in checks.items()], "success": True})
    monkeypatch.setattr(bootstrap, "run_text", lambda cmd, **kw: subprocess.CompletedProcess(cmd, 0, out, ""))


def test_agent_browser_state(monkeypatch):
    _doctor(monkeypatch, {"chrome.installed": "pass", "launch.elapsed": "pass"})
    assert bootstrap.agent_browser_state("ab") == "ok"
    _doctor(monkeypatch, {"chrome.installed": "fail"})
    assert bootstrap.agent_browser_state("ab") == "no-chrome"
    _doctor(monkeypatch, {"chrome.installed": "pass", "launch.test": "fail"})
    assert bootstrap.agent_browser_state("ab") == "launch-failed"
    monkeypatch.setattr(bootstrap, "run_text", lambda cmd, **kw: subprocess.CompletedProcess(cmd, 2, "boom", ""))
    assert bootstrap.agent_browser_state("ab") is None


def test_setup_reuses_existing_tools_without_prompting(monkeypatch, capsys):
    monkeypatch.setattr(bootstrap, "ffmpeg_version", lambda *a: (8, 1))
    monkeypatch.setattr(bootstrap, "find_font", lambda *a: "/f.ttf")
    monkeypatch.setattr(bootstrap, "agent_browser_bin", lambda: "/x/agent-browser")
    monkeypatch.setattr(bootstrap, "agent_browser_state", lambda exe: "ok")
    monkeypatch.setattr(bootstrap, "find_dbx", lambda: ("running", "http://127.0.0.1:4224/"))
    monkeypatch.setattr(bootstrap, "bsk_bin", lambda: "/x/bsk")
    monkeypatch.setattr(bootstrap, "bsk_skill_installed", lambda bsk: {"claude-code"})
    monkeypatch.setattr("tirai.doctor.bsk_doctor", lambda bsk: (True, "extension connected"))
    monkeypatch.setattr(bootstrap.install, "install", lambda *a, **k: None)
    ran = []
    monkeypatch.setattr(bootstrap.Setup, "execute", lambda self, cmd: ran.append(cmd) or True)
    monkeypatch.setattr(bootstrap.Setup, "confirm", lambda self, what: ran.append(what) or True)
    assert bootstrap.run(agents=["claude"]) == 0
    out = capsys.readouterr().out
    assert ran == []  # nothing downloaded, installed or asked
    assert "already running" in out and "browser-skill already installed" in out and "extension connected" in out


def test_setup_only_and_optional_bsk(monkeypatch, capsys):
    monkeypatch.setattr(bootstrap, "agent_browser_bin", lambda: "/x/agent-browser")
    monkeypatch.setattr(bootstrap, "bsk_bin", lambda: None)
    asked = []
    monkeypatch.setattr(bootstrap.Setup, "confirm", lambda self, what: asked.append(what) or False)
    assert bootstrap.run(only={"browserskill"}) == 1  # explicitly requested: offered (declined here)
    assert asked and "BrowserSkill" in asked[0]
    asked.clear()
    assert bootstrap.run(skip={"ffmpeg", "agent-browser", "dbx", "skills"}) == 0  # optional: not offered
    assert asked == [] and "optional" in capsys.readouterr().out
