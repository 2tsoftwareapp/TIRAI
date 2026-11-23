import os

import pytest

from tirai import bootstrap, system
from tirai.cli import main
from tirai.scenario import load_env_file


def test_find_bin_prefers_env_then_extra_dirs(tmp_path, monkeypatch):
    tool = tmp_path / ("mytool.exe" if system.IS_WINDOWS else "mytool")
    tool.write_text("")
    monkeypatch.setenv("MYTOOL_BIN", "/custom/mytool")
    assert system.find_bin("mytool", "MYTOOL_BIN", [tmp_path]) == "/custom/mytool"
    monkeypatch.delenv("MYTOOL_BIN")
    assert system.find_bin("mytool", "MYTOOL_BIN", [tmp_path]) == str(tool)
    assert system.find_bin("mytool-missing", None, [tmp_path]) is None


def test_bsk_bin_uses_install_dir(tmp_path, monkeypatch):
    monkeypatch.delenv("BSK_BIN", raising=False)
    monkeypatch.setenv("PATH", "")
    monkeypatch.setenv("BSK_INSTALL_DIR", str(tmp_path))
    (tmp_path / ("bsk.exe" if system.IS_WINDOWS else "bsk")).write_text("")
    assert system.bsk_bin().startswith(str(tmp_path))


def test_font_env_override(tmp_path, monkeypatch):
    font = tmp_path / "x.ttf"
    font.write_bytes(b"")
    monkeypatch.setenv("TIRAI_FONT", str(font))
    monkeypatch.delenv("TIRAI_FONT_BOLD", raising=False)
    assert system.find_font() == str(font)


def test_primary_modifier_matches_platform():
    assert system.primary_modifier() == ("Meta" if system.IS_MAC else "Ctrl")


def test_package_install_cmd_is_platform_specific():
    cmd = bootstrap.package_install_cmd(["ffmpeg"])
    if cmd is None:
        pytest.skip("no package manager on this runner")
    tools = {"winget", "choco", "scoop"} if system.IS_WINDOWS else {"brew"} if system.IS_MAC else None
    if tools:
        assert cmd[0] in tools
    else:
        assert any(pm in cmd for pm in ("apt-get", "dnf", "pacman", "zypper", "apk"))


def test_setup_dry_run_changes_nothing(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(bootstrap, "AGENT_HOMES", {"claude": tmp_path / ".claude"})
    rc = bootstrap.run(agents=["claude"], project=tmp_path, dry_run=True)
    out = capsys.readouterr().out
    assert rc == 0
    assert "would install tirai-evidence for: claude" in out
    assert not (tmp_path / ".claude").exists()


def test_setup_installs_skills_only(tmp_path, capsys):
    rc = bootstrap.run(
        agents=["claude", "antigravity"],
        project=tmp_path,
        yes=True,
        skip={"ffmpeg", "agent-browser", "dbx", "browserskill"},
    )
    assert rc == 0
    assert (tmp_path / ".claude/skills/tirai-evidence/SKILL.md").is_file()
    assert (tmp_path / ".agent/skills/tirai-evidence/SKILL.md").is_file()


def test_detect_agents(tmp_path, monkeypatch):
    (tmp_path / ".cursor").mkdir()
    monkeypatch.setattr(bootstrap, "AGENT_HOMES", {"cursor": tmp_path / ".cursor", "claude": tmp_path / ".claude"})
    assert bootstrap.detect_agents() == ["cursor"]


def test_env_file_does_not_override(tmp_path, monkeypatch):
    f = tmp_path / ".env"
    f.write_text("# c\nA_TIRAI=1\nexport B_TIRAI='two words'\nC_TIRAI=\"x\"\n", encoding="utf-8")
    monkeypatch.setenv("A_TIRAI", "kept")
    for k in ("B_TIRAI", "C_TIRAI"):
        monkeypatch.delenv(k, raising=False)
    load_env_file(f)
    assert (os.environ["A_TIRAI"], os.environ["B_TIRAI"], os.environ["C_TIRAI"]) == ("kept", "two words", "x")
    for k in ("B_TIRAI", "C_TIRAI"):
        monkeypatch.delenv(k)


def test_validate_reads_env_next_to_scenario(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("APP_URL", raising=False)
    with pytest.raises(SystemExit):
        main(["init", str(tmp_path / "s.yaml")])
    (tmp_path / ".env").write_text("APP_URL=http://x\n")
    with pytest.raises(SystemExit) as e:
        main(["validate", str(tmp_path / "s.yaml")])
    assert e.value.code == 0
    assert os.environ.get("APP_URL") == "http://x"
    monkeypatch.delenv("APP_URL")


def test_unknown_settings_rejected():
    from tirai.scenario import validate

    sc = {
        "name": "x",
        "settings": {"speed": 1},
        "tabs": {"a": {"url": "u", "dbx": {"bogus": 1}}},
        "steps": [{"id": "S1", "tab": "a", "title": "t", "expect": [{"visible": "#a"}]}],
    }
    problems = validate(sc)
    assert any("settings.speed" in p for p in problems)
    assert any("dbx.bogus" in p for p in problems)
