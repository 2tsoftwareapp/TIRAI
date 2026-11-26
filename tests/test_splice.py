"""`tirai record --from-step`: re-record the tail of a recording and splice it into the earlier one."""

import json
import types

import pytest

from tirai import cli, runner
from tirai.scenario import ScenarioError


def old_recording(d, statuses, segs=("seg-01-app.mp4", "seg-02-db.mp4")):
    steps = [
        {"id": f"S{i}", "status": st, "segment": segs[0] if i < 3 else segs[1]} for i, st in enumerate(statuses, 1)
    ]
    for f in segs:
        (d / f).write_bytes(b"mp4")
    tl = {"mode": "record", "steps": steps, "segments": [{"tab": "x", "file": f, "duration": 1} for f in segs],
          "total_steps": 4, "meta": {"ticket": "#1"}}  # fmt: skip
    (d / "timeline.json").write_text(json.dumps(tl))
    return tl


def test_splice_base_keeps_the_passed_steps_before(tmp_path):
    old_recording(tmp_path, ["passed", "passed", "failed"])
    old, kept = runner.splice_base(tmp_path, "S3")
    assert [s["id"] for s in kept] == ["S1", "S2"]
    with pytest.raises(ScenarioError, match="stopped at S3"):
        runner.splice_base(tmp_path, "S4")
    old_recording(tmp_path, ["passed", "passed", "failed", "failed"])  # --record-failures kept going
    with pytest.raises(ScenarioError, match="earlier step S3 did not pass; re-record from S3"):
        runner.splice_base(tmp_path, "S4")


def test_splice_base_needs_an_earlier_recording(tmp_path):
    with pytest.raises(ScenarioError, match="does not exist"):
        runner.splice_base(tmp_path, "S2")
    (tmp_path / "timeline.json").write_text(json.dumps({"mode": "dry-run", "steps": []}))
    with pytest.raises(ScenarioError, match="is not a recording"):
        runner.splice_base(tmp_path, "S2")


def test_splice_merges_steps_and_moves_unused_segments(tmp_path):
    old_recording(tmp_path, ["passed", "passed", "failed"])
    old, kept = runner.splice_base(tmp_path, "S3")
    new = {"created": "now", "segments": [{"tab": "db", "file": "seg-03-db.mp4", "duration": 2}],
           "steps": [{"id": "S3", "status": "passed", "segment": "seg-03-db.mp4"},
                     {"id": "S4", "status": "passed", "segment": "seg-03-db.mp4"}],
           "total_steps": 2, "meta": {"ticket": "#1"}}  # fmt: skip
    tl = runner.splice(tmp_path, old, kept, new, "S3")
    assert [s["id"] for s in tl["steps"]] == ["S1", "S2", "S3", "S4"]
    assert [s["file"] for s in tl["segments"]] == ["seg-01-app.mp4", "seg-03-db.mp4"]
    assert tl["total_steps"] == 4 and tl["spliced"] == [{"from_step": "S3", "at": "now"}]
    assert tl["meta"] == {"ticket": "#1", "re-recorded from": "S3"}
    assert (tmp_path / "replaced" / "seg-02-db.mp4").is_file() and not (tmp_path / "seg-02-db.mp4").exists()


def test_record_from_step_skips_the_dry_run_and_keeps_the_step(monkeypatch):
    seen = []
    monkeypatch.setattr(cli, "cmd_run", lambda a: seen.append((a.record, a.from_step)) or 0)
    monkeypatch.setattr(cli, "cmd_compose", lambda a: 0)
    args = types.SimpleNamespace(from_step="S3", until=None, keep_session=False, skip_dry_run=False, out="ev",
                                 session=None, record_failures=False)  # fmt: skip
    assert cli.cmd_record(args) == 0
    assert seen == [(True, "S3")]


def test_recording_with_until_is_refused(tmp_path, capsys):
    (tmp_path / "s.yaml").write_text(
        "name: x\ntabs: { app: { url: 'http://a.test/' } }\n"
        "steps: [{id: S1, tab: app, title: t, expect: [{visible: a}]}]\n"
    )
    with pytest.raises(SystemExit) as code:
        cli.main(["run", str(tmp_path / "s.yaml"), "--record", "--until", "S1", "--out", str(tmp_path)])
    assert code.value.code == 2 and "--until is for dry-runs" in capsys.readouterr().out


def test_splice_vars_prefer_the_newer_preparing_dry_run(tmp_path):
    import os

    rec, dry = tmp_path / "record", tmp_path / "dry-run"
    rec.mkdir()
    dry.mkdir()
    (rec / "timeline.json").write_text(json.dumps({"steps": [{"saved": {"order": "A-1", "user": "u1"}}]}))
    (dry / "timeline.json").write_text(json.dumps({"steps": [{"saved": {"order": "A-2"}}]}))
    os.utime(rec / "timeline.json", (1, 1))  # the recording is older than the preparing dry-run
    assert runner.splice_vars(rec) == {"order": "A-2", "user": "u1"}
    os.utime(dry / "timeline.json", (0, 0))  # a stale dry-run from before the recording does not win
    assert runner.splice_vars(rec)["order"] == "A-1"


def test_kept_steps_that_write_data_are_warned_about(tmp_path, capsys):
    tl = old_recording(tmp_path, ["passed", "passed", "failed"])
    tl["steps"][1]["writes"] = "creates an order"
    (tmp_path / "timeline.json").write_text(json.dumps(tl))
    runner.splice_base(tmp_path, "S3")
    assert "kept step(s) S2 write data" in capsys.readouterr().out
