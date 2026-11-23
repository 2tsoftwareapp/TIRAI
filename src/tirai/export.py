"""Test-management exports written next to the evidence: JUnit XML, Xray JSON and TestRail CSV.

Files only; nothing is uploaded. Import them with the tool's own importer (CI JUnit reports, Xray
"Import Execution Results", TestRail "Import Results from CSV").
"""

import base64
import csv
import json
import time
from pathlib import Path
from xml.etree import ElementTree as ET

FORMATS = ("junit", "xray", "testrail")


def _failures(step):
    msgs = [f"{c['type']}: expected {c.get('expected')!r}, actual {c.get('actual')!r}" for c in step.get("checks", [])]
    bad = [m for m, c in zip(msgs, step.get("checks", []), strict=True) if not c["ok"]]
    if step.get("error"):
        bad.append(f"error: {step['error']}")
    return bad


def _seconds(step):
    if step.get("final_start") is not None and step.get("final_end") is not None:
        return max(0.0, step["final_end"] - step["final_start"])
    if step.get("start") is not None and step.get("end") is not None:
        return max(0.0, step["end"] - step["start"])
    return 0.0


def _skipped(tl):
    done = {s["id"] for s in tl["steps"]}
    return [sid for sid in tl.get("step_ids", []) if sid not in done]


def junit(tl, video="final.mp4"):
    steps = tl["steps"]
    failed = sum(s["status"] == "failed" for s in steps)
    errors = sum(s["status"] == "error" for s in steps)
    skipped = max(0, tl.get("total_steps", len(steps)) - len(steps))
    suite = ET.Element(
        "testsuite",
        name=tl["scenario"],
        tests=str(len(steps) + skipped),
        failures=str(failed),
        errors=str(errors),
        skipped=str(skipped),
        time=f"{sum(_seconds(s) for s in steps):.3f}",
        timestamp=tl.get("created", "").replace(" ", "T"),
    )
    props = ET.SubElement(suite, "properties")
    for k, v in (("driver", tl.get("driver", "")), ("mode", tl.get("mode", "")), ("video", video)):
        ET.SubElement(props, "property", name=k, value=str(v))
    for s in steps:
        case = ET.SubElement(
            suite, "testcase", classname=tl["scenario"], name=f"{s['id']} {s['title']}", time=f"{_seconds(s):.3f}"
        )
        bad = _failures(s)
        if s["status"] == "failed":
            ET.SubElement(case, "failure", message=bad[0] if bad else "failed").text = "\n".join(bad)
        elif s["status"] == "error":
            ET.SubElement(case, "error", message=s.get("error", "error")).text = "\n".join(bad)
        out = [f"tab: {tl['tabs'][s['tab']]['label']}"]
        if s.get("final_start") is not None:
            out.append(f"video: {video} at {s['final_start']:.1f}s")
        if s.get("screenshot"):
            out.append(f"screenshot: {s['screenshot']}")
        ET.SubElement(case, "system-out").text = "\n".join(out)
    for i in range(skipped):
        case = ET.SubElement(suite, "testcase", classname=tl["scenario"], name=f"not run #{i + 1}", time="0")
        ET.SubElement(case, "skipped", message="stopped after an earlier failing step")
    ET.indent(suite)
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(suite, encoding="unicode") + "\n"


def xray(tl, rec_dir, test_key=None, project_key=None, report="report.html"):
    """Xray JSON (Jira Server/Cloud "Import Execution Results"): one test, one Xray step per scenario step."""
    status = "PASSED" if all(s["status"] == "passed" for s in tl["steps"]) else "FAILED"
    created = tl.get("created") or time.strftime("%Y-%m-%d %H:%M:%S")
    test = {
        "status": status,
        "comment": f"TIRAI evidence ({tl.get('driver', '')}): {sum(s['status'] == 'passed' for s in tl['steps'])}/"
        f"{tl.get('total_steps', len(tl['steps']))} steps passed",
        "steps": [
            {
                "status": "PASSED" if s["status"] == "passed" else "FAILED",
                "actualResult": "; ".join(_failures(s)) or "as expected",
            }
            for s in tl["steps"]
        ],
    }
    if test_key:
        test["testKey"] = test_key
    else:
        test["testInfo"] = {
            "summary": tl["scenario"],
            "type": "Manual",
            **({"projectKey": project_key} if project_key else {}),
            "steps": [{"action": s["title"], "result": s.get("subtitle", s["title"])} for s in tl["steps"]],
        }
    rep = Path(rec_dir) / report
    if rep.is_file():
        test["evidence"] = [
            {"data": base64.b64encode(rep.read_bytes()).decode(), "filename": report, "contentType": "text/html"}
        ]
    return {
        "info": {
            "summary": f"Evidence: {tl['scenario']}",
            "startDate": created.replace(" ", "T") + "Z",
            "finishDate": created.replace(" ", "T") + "Z",
        },
        "tests": [test],
    }


def testrail_rows(tl, case_id=None):
    """TestRail "Import Results from CSV" rows: one per step (map Title/Case ID, Status, Comment, Elapsed)."""
    rows = []
    for s in tl["steps"]:
        secs = max(1, round(_seconds(s)))
        rows.append(
            {
                "Case ID": case_id or "",
                "Title": f"{s['id']} {s['title']}",
                "Status": "Passed" if s["status"] == "passed" else "Failed",
                "Comment": "; ".join(_failures(s)) or "as expected",
                "Elapsed": f"{secs}s",
            }
        )
    return rows


def write(rec_dir, tl, formats=FORMATS, video="final.mp4", test_key=None, project_key=None, case_id=None):
    rec_dir = Path(rec_dir)
    written = []
    if "junit" in formats:
        (rec_dir / "junit.xml").write_text(junit(tl, video), encoding="utf-8")
        written.append(rec_dir / "junit.xml")
    if "xray" in formats:
        data = xray(tl, rec_dir, test_key, project_key)
        (rec_dir / "xray.json").write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        written.append(rec_dir / "xray.json")
    if "testrail" in formats:
        path = rec_dir / "testrail.csv"
        rows = testrail_rows(tl, case_id)
        with open(path, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=["Case ID", "Title", "Status", "Comment", "Elapsed"])
            w.writeheader()
            w.writerows(rows)
        written.append(path)
    return written
