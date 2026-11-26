"""`tirai diff`: per-step screenshot comparison between two runs."""

import json

import pytest

PIL = pytest.importorskip("PIL")
from PIL import Image, ImageDraw  # noqa: E402

from tirai import visual  # noqa: E402


def run(tmp_path, name, steps):
    """A run folder: timeline.json + step-<id>.png drawn by `steps` {id: draw(ImageDraw) or None}."""
    d = tmp_path / name / "record"
    d.mkdir(parents=True)
    rows = []
    for sid, draw in steps.items():
        img = Image.new("RGB", (200, 100), (248, 250, 252))
        if draw:
            draw(ImageDraw.Draw(img))
        img.save(d / f"step-{sid}.png")
        rows.append({"id": sid, "title": f"title {sid}", "status": "passed", "screenshot": f"step-{sid}.png"})
    (d / "timeline.json").write_text(json.dumps({"scenario": "demo", "steps": rows}))
    return tmp_path / name


def button(text_x):
    return lambda g: g.rectangle((text_x, 40, text_x + 40, 60), fill=(37, 99, 235))


def test_diff_flags_changed_and_missing_steps(tmp_path):
    old = run(tmp_path, "old", {"S1": button(10), "S2": button(10), "S3": None})
    new = run(tmp_path, "new", {"S1": button(10), "S2": button(120), "S4": None})
    rep = visual.diff(old, new, tmp_path / "out", threshold=0.5)
    by = {r["id"]: r for r in rep["steps"]}
    assert by["S1"]["status"] == "same" and by["S1"]["changed_pct"] == 0
    assert by["S2"]["status"] == "changed" and by["S2"]["changed_pct"] > 5
    assert by["S2"]["bbox"] == [10, 40, 161, 61]
    assert by["S3"]["status"] == "missing" and by["S3"]["note"] == "only in old run"
    assert by["S4"]["note"] == "only in new run"
    assert (tmp_path / "out" / "S2.png").is_file() and not (tmp_path / "out" / "S1.png").exists()
    assert Image.open(tmp_path / "out" / "S2.png").size == (616, 100)  # old | new | changes
    assert "S2 title S2" in (tmp_path / "out" / "diff.html").read_text()
    assert json.loads((tmp_path / "out" / "diff.json").read_text())["threshold_pct"] == 0.5


def test_small_changes_stay_under_the_threshold(tmp_path):
    old = run(tmp_path, "old", {"S1": None})
    new = run(tmp_path, "new", {"S1": lambda g: g.point((5, 5), fill=(0, 0, 0))})
    rep = visual.diff(old / "record", new, tmp_path / "out", threshold=0.5)
    assert rep["steps"][0]["status"] == "same" and 0 < rep["steps"][0]["changed_pct"] < 0.5


def test_needs_a_timeline(tmp_path):
    with pytest.raises(FileNotFoundError, match="no timeline.json"):
        visual.run_dir(tmp_path)
