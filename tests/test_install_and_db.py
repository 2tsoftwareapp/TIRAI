import sqlite3

import pytest

from tirai import db
from tirai.cli import main
from tirai.install import install


def test_install_skill_into_project(tmp_path):
    done = install(["claude", "codex", "antigravity", "devin"], project=tmp_path)
    paths = sorted(p.relative_to(tmp_path).as_posix() for p in done)
    assert paths == [".agent/skills/tirai-evidence", ".agents/skills/tirai-evidence", ".claude/skills/tirai-evidence"]
    assert (tmp_path / ".claude/skills/tirai-evidence/references/scenario.md").is_file()
    assert install(["claude"], project=tmp_path) == []  # existing install is kept without --force


def test_sqlite_query_is_read_only(tmp_path):
    path = tmp_path / "x.db"
    with sqlite3.connect(path) as c:
        c.execute("create table t(a)")
        c.execute("insert into t values (1)")
    assert db.query(f"sqlite:///{path}", "select a from t") == [(1,)]
    with pytest.raises(sqlite3.OperationalError):
        db.query(f"sqlite:///{path}", "insert into t values (2)")


def test_unknown_scheme():
    with pytest.raises(ValueError):
        db.query("oracle://x", "select 1")


def test_cli_init_and_validate(tmp_path, monkeypatch, capsys):
    target = tmp_path / "s.yaml"
    with pytest.raises(SystemExit) as e:
        main(["init", str(target)])
    assert e.value.code == 0
    with pytest.raises(SystemExit) as e:
        main(["validate", str(target)])
    assert e.value.code == 0
    assert "APP_URL" in capsys.readouterr().out


def test_claude_plugin_version_matches_package():
    import json
    from pathlib import Path

    from tirai import __version__

    root = Path(__file__).resolve().parents[1]
    assert json.loads((root / ".claude-plugin" / "plugin.json").read_text())["version"] == __version__
