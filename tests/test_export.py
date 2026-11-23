import csv
import json
from xml.etree import ElementTree as ET

from tirai import cli, export

TL = {
    "scenario": "Login",
    "mode": "record",
    "driver": "agent-browser",
    "created": "2026-11-23 10:00:00",
    "tabs": {"app": {"label": "APP"}},
    "total_steps": 3,
    "steps": [
        {"id": "S1", "title": "Open", "tab": "app", "status": "passed", "checks": [{"type": "visible", "ok": True}],
         "final_start": 3.0, "final_end": 6.5, "screenshot": "step-S1.png"},
        {"id": "S2", "title": "Bad login", "tab": "app", "status": "failed",
         "checks": [{"type": "text_contains", "ok": False, "expected": {"text": "x"}, "actual": "y"}],
         "final_start": 6.5, "final_end": 9.0},
    ],
}  # fmt: skip


def run(argv):
    args = cli.build_parser().parse_args(argv)
    return args.fn(args)


def test_junit_counts_failures_and_not_run_steps():
    root = ET.fromstring(export.junit(TL))
    assert (root.get("tests"), root.get("failures"), root.get("skipped")) == ("3", "1", "1")
    cases = root.findall("testcase")
    assert cases[1].find("failure").get("message").startswith("text_contains")
    assert cases[2].find("skipped") is not None


def test_xray_new_test_or_existing_key(tmp_path):
    (tmp_path / "report.html").write_text("<html>")
    data = export.xray(TL, tmp_path, project_key="QA")
    t = data["tests"][0]
    assert t["status"] == "FAILED" and t["testInfo"]["projectKey"] == "QA" and len(t["steps"]) == 2
    assert t["evidence"][0]["filename"] == "report.html"
    assert export.xray(TL, tmp_path, test_key="QA-7")["tests"][0]["testKey"] == "QA-7"


def test_export_command_writes_files_and_refreshes_manifest(tmp_path):
    (tmp_path / "timeline.final.json").write_text(json.dumps(TL))
    (tmp_path / "manifest.sha256").write_text("")
    assert run(["export", str(tmp_path), "--case-id", "C9"]) == 0
    rows = list(csv.DictReader((tmp_path / "testrail.csv").open(encoding="utf-8")))
    assert rows[0]["Case ID"] == "C9" and rows[1]["Status"] == "Failed"
    assert "junit.xml" in (tmp_path / "manifest.sha256").read_text()
    assert run(["export", str(tmp_path), "-f", "pdf"]) == 2
