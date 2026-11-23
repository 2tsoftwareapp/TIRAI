import json

from tirai import index, report


def run(d, status, created):
    d.mkdir(parents=True)
    tl = {"scenario": f"S {d.name}", "created": created, "driver": "agent-browser", "mode": "record",
          "steps": [{"id": "S1", "title": "Open", "status": status, "final_end": 4.0}]}  # fmt: skip
    (d / "timeline.final.json").write_text(json.dumps(tl))
    (d / "timeline.json").write_text(json.dumps(tl))
    (d / "report.html").write_text("r")
    report.write_manifest(d)


def test_index_lists_runs_newest_first_with_integrity(tmp_path):
    run(tmp_path / "ev" / "a" / "record", "passed", "2026-01-01 10:00:00")
    run(tmp_path / "ev" / "b" / "record", "failed", "2026-01-02 10:00:00")
    (tmp_path / "ev" / "a" / "record" / "report.html").write_text("tampered")
    out, runs = index.write([tmp_path / "ev"], tmp_path / "index.html")
    assert [r["status"] for r in runs] == ["failed", "passed"]
    assert runs[1]["integrity"] == "modified"
    page = out.read_text()
    assert 'href="ev/a/record/report.html"' in page and "1 passed" in page
