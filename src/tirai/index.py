"""One HTML page listing many evidence folders (runs), with filters and integrity status."""

import html
import json
import os
from pathlib import Path

from tirai import report


def find_runs(roots):
    seen = set()
    for root in roots:
        root = Path(root)
        candidates = [root] if (root / "timeline.json").is_file() else root.rglob("timeline.json")
        for tl_file in candidates:
            d = tl_file if tl_file.is_dir() else tl_file.parent
            if d.resolve() not in seen:
                seen.add(d.resolve())
                yield d


def run_info(d):
    tl_path = d / "timeline.final.json" if (d / "timeline.final.json").is_file() else d / "timeline.json"
    tl = json.loads(tl_path.read_text(encoding="utf-8"))
    steps = tl.get("steps", [])
    passed = sum(s["status"] == "passed" for s in steps)
    total = tl.get("total_steps", len(steps))
    has_manifest = (d / report.MANIFEST).is_file()
    problems = report.verify(d) if has_manifest else []
    integrity = "no manifest" if not has_manifest else ("modified" if problems else "intact")
    if has_manifest and (d / (report.MANIFEST + ".sig")).is_file():
        from tirai import sign

        bad_sig, _ = sign.verify_signature(d)
        if bad_sig:
            integrity = "modified (bad signature)"
        elif not problems:
            integrity = "intact, signed"
    videos = sorted(p.name for p in d.glob("final*.mp4"))
    return {
        "dir": d,
        "scenario": tl.get("scenario", d.name),
        "created": tl.get("created", ""),
        "driver": tl.get("driver", ""),
        "mode": tl.get("mode", ""),
        "passed": passed,
        "total": total,
        "status": "passed" if steps and passed == total else "failed",
        "duration": max((s.get("final_end", 0) for s in steps), default=0),
        "integrity": integrity,
        "video": videos[0] if videos else None,
        "files": [n for n in ("report.html", "report.xlsx", "junit.xml", "subtitles.srt") if (d / n).is_file()],
        "fails": [f"{s['id']} {s['title']}" for s in steps if s["status"] != "passed"],
    }


def write(roots, out):
    out = Path(out)
    runs = sorted((run_info(d) for d in find_runs(roots)), key=lambda r: r["created"], reverse=True)
    e = html.escape
    rows = []
    for r in runs:
        rel = Path(os.path.relpath(r["dir"], out.parent)).as_posix()
        links = " ".join(f'<a href="{e(rel)}/{n}">{n.split(".")[-1]}</a>' for n in r["files"])
        video = f'<a href="{e(rel)}/{e(r["video"])}">video</a>' if r["video"] else ""
        fails = f'<div class="sub">{e(", ".join(r["fails"]))}</div>' if r["fails"] else ""
        rows.append(
            f'<tr data-status="{r["status"]}" data-integrity="{e(r["integrity"])}">'
            f'<td>{e(r["created"])}</td><td><a href="{e(rel)}/report.html">{e(r["scenario"])}</a>'
            f'<div class="sub">{e(rel)}</div>{fails}</td>'
            f'<td><span class="st {r["status"]}">{r["passed"]}/{r["total"]}</span></td>'
            f"<td>{e(r['driver'])} · {e(r['mode'])}</td><td>{r['duration']:.0f}s</td>"
            f'<td class="i-{e(r["integrity"].split(",")[0])}">{e(r["integrity"])}</td><td>{video} {links}</td></tr>'
        )
    ok = sum(r["status"] == "passed" for r in runs)
    page = f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>TIRAI evidence index</title>
<style>
body{{font:14px/1.45 system-ui,sans-serif;margin:0;background:#f6f7f9;color:#1d2330}}
header{{background:#1d2330;color:#fff;padding:18px 28px}}h1{{margin:0;font-size:20px}}
.bar{{display:flex;gap:10px;padding:14px 28px;align-items:center}}
input,select{{padding:6px 8px;border:1px solid #ccd;border-radius:6px}}
table{{border-collapse:collapse;width:calc(100% - 56px);margin:0 28px 28px;
background:#fff;border-radius:8px;overflow:hidden}}
th,td{{padding:8px 10px;border-bottom:1px solid #eceef2;text-align:left;vertical-align:top}}
th{{background:#eef0f4;font-weight:600}}
.sub{{color:#6b7280;font-size:12px}}
.st{{padding:2px 8px;border-radius:10px;font-weight:600}}
.st.passed{{background:#dcfce7;color:#166534}}
.st.failed{{background:#fee2e2;color:#991b1b}}
.i-modified{{color:#b91c1c;font-weight:600}}.i-intact{{color:#166534}}
a{{color:#2563eb}}
</style></head><body><header><h1>TIRAI evidence index</h1>
<div>{len(runs)} runs · {ok} passed · {len(runs) - ok} failed</div></header>
<div class="bar"><input id="q" placeholder="Filter scenario, folder, step…" size="40">
<select id="st"><option value="">all results</option><option>passed</option><option>failed</option></select>
<select id="ig"><option value="">any integrity</option><option>intact</option><option>modified</option></select></div>
<table><thead><tr><th>Recorded</th><th>Scenario</th><th>Steps</th><th>Driver · mode</th><th>Video</th>
<th>Integrity</th><th>Files</th></tr></thead><tbody>{"".join(rows)}</tbody></table>
<script>
const f=()=>{{const q=document.getElementById('q').value.toLowerCase(),s=document.getElementById('st').value,
g=document.getElementById('ig').value;for(const r of document.querySelectorAll('tbody tr')){{
r.hidden=!(r.textContent.toLowerCase().includes(q)&&(!s||r.dataset.status===s)&&(!g||r.dataset.integrity.startsWith(g)))}}}};
for(const id of ['q','st','ig'])document.getElementById(id).addEventListener('input',f);
</script></body></html>"""
    out.write_text(page, encoding="utf-8")
    return out, runs
