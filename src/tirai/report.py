"""Evidence reports (HTML, optional Excel) and the SHA-256 manifest that makes tampering detectable."""

import base64
import hashlib
import html
from pathlib import Path

MANIFEST = "manifest.sha256"
EVIDENCE_GLOBS = ["final.mp4", "subtitles.srt", "report.*", "timeline*.json", "step-*.png", "seg-*.mp4"]


def _mmss(sec):
    sec = int(sec or 0)
    return f"{sec // 60:02d}:{sec % 60:02d}"


def _checks(step):
    return [(c["type"], c["ok"], c.get("expected"), c.get("actual")) for c in step.get("checks", [])]


def write_html(rec_dir, tl, video_name):
    """Single self-contained file: screenshots are embedded, step times jump the video player."""
    rec_dir = Path(rec_dir)
    e = html.escape
    rows = []
    for s in tl["steps"]:
        shot = rec_dir / s.get("screenshot", "")
        img = ""
        if s.get("screenshot") and shot.is_file():
            data = base64.b64encode(shot.read_bytes()).decode()
            img = f'<img src="data:image/png;base64,{data}" alt="{e(s["id"])}">'
        checks = "".join(
            f'<li class="{"ok" if ok else "fail"}"><b>{e(t)}</b> {e(str(exp))}'
            + ("" if ok else f"<br><small>actual: {e(str(act))}</small>")
            + "</li>"
            for t, ok, exp, act in _checks(s)
        )
        if s.get("error"):
            checks += f'<li class="fail"><b>error</b> {e(s["error"])}</li>'
        when = ""
        if "final_start" in s:
            when = f'<a href="#" onclick="seek({s["final_start"]});return false">{_mmss(s["final_start"])}</a>'
        status = s["status"].upper()
        rows.append(
            f"<tr><td>{e(s['id'])}</td><td>{e(tl['tabs'][s['tab']]['label'])}</td>"
            f'<td>{e(s["title"])}<div class="sub">{e(s.get("subtitle", ""))}</div></td>'
            f'<td><span class="st {status.lower()}">{status}</span></td><td>{when}</td>'
            f"<td><ul>{checks}</ul></td><td>{img}</td></tr>"
        )
    passed = sum(s["status"] == "passed" for s in tl["steps"])
    page = f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<title>{e(tl["scenario"])} — evidence</title>
<style>
body{{font:14px/1.45 system-ui,sans-serif;margin:24px;color:#1f2328}}h1{{margin:0 0 4px}}
.meta{{color:#59636e;margin-bottom:16px}}video{{width:100%;max-width:960px;border-radius:8px;background:#000}}
table{{border-collapse:collapse;width:100%;margin-top:16px}}td,th{{border-top:1px solid #d1d9e0;padding:8px;
vertical-align:top;text-align:left}}th{{background:#f6f8fa}}img{{max-width:320px;border:1px solid #d1d9e0;
border-radius:4px}}ul{{margin:0;padding-left:18px}}li.ok{{color:#1a7f37}}li.fail{{color:#d1242f}}
.sub{{color:#59636e;font-size:12px}}.st{{padding:2px 8px;border-radius:10px;color:#fff;font-weight:600}}
.st.passed{{background:#1a7f37}}.st.failed,.st.error{{background:#d1242f}}
</style></head><body>
<h1>{e(tl["scenario"])}</h1>
<div class="meta">Recorded {e(tl["created"])} · {passed}/{tl.get("total_steps", len(tl["steps"]))} steps passed ·
integrity: <code>{MANIFEST}</code> (check with <code>tirai verify</code>)</div>
<video id="v" src="{e(video_name)}" controls></video>
<table><tr><th>Step</th><th>Tab</th><th>Title</th><th>Status</th><th>Video</th><th>Checks</th><th>Screenshot</th></tr>
{"".join(rows)}</table>
<script>function seek(t){{const v=document.getElementById('v');v.currentTime=t;v.play();}}</script>
</body></html>
"""
    out = rec_dir / "report.html"
    out.write_text(page, encoding="utf-8")
    return out


def write_xlsx(rec_dir, tl, video_name):
    """Excel evidence sheet (one row per step with its screenshot); skipped when openpyxl is missing."""
    try:
        import PIL  # noqa: F401  (openpyxl needs Pillow to embed screenshots)
        from openpyxl import Workbook
        from openpyxl.drawing.image import Image
        from openpyxl.styles import Alignment, Font, PatternFill
    except ImportError:
        return None
    rec_dir = Path(rec_dir)
    wb = Workbook()
    ws = wb.active
    ws.title = "Evidence"
    ws.append([tl["scenario"]])
    ws["A1"].font = Font(bold=True, size=14)
    ws.append([f"Recorded {tl['created']} · video {video_name}"])
    header = ["Step", "Tab", "Title", "Expected", "Actual", "Status", "Video time", "Screenshot"]
    ws.append(header)
    for cell in ws[3]:
        cell.font = Font(bold=True)
        cell.fill = PatternFill("solid", fgColor="F6F8FA")
    widths = [8, 14, 36, 48, 48, 10, 12, 60]
    for i, w in enumerate(widths):
        ws.column_dimensions[chr(65 + i)].width = w
    for s in tl["steps"]:
        checks = _checks(s)
        expected = "\n".join(f"{t}: {exp}" for t, _, exp, _ in checks)
        actual = "\n".join(f"{t}: {'OK' if ok else act}" for t, ok, _, act in checks) + (
            f"\nerror: {s['error']}" if s.get("error") else ""
        )
        when = _mmss(s["final_start"]) if "final_start" in s else ""
        ws.append([s["id"], tl["tabs"][s["tab"]]["label"], s["title"], expected, actual, s["status"].upper(), when])
        r = ws.max_row
        for cell in ws[r]:
            cell.alignment = Alignment(wrap_text=True, vertical="top")
        ws.cell(r, 6).font = Font(bold=True, color="1A7F37" if s["status"] == "passed" else "D1242F")
        shot = rec_dir / s.get("screenshot", "")
        if s.get("screenshot") and shot.is_file():
            img = Image(str(shot))
            scale = 420 / img.width
            img.width, img.height = 420, int(img.height * scale)
            ws.add_image(img, f"H{r}")
            ws.row_dimensions[r].height = img.height * 0.75 + 6
    out = rec_dir / "report.xlsx"
    wb.save(out)
    return out


def _sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def write_manifest(rec_dir):
    rec_dir = Path(rec_dir)
    files = sorted({p for g in EVIDENCE_GLOBS for p in rec_dir.glob(g) if p.is_file() and p.name != MANIFEST})
    lines = [f"{_sha256(p)}  {p.name}" for p in files]
    out = rec_dir / MANIFEST
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return out


def verify(rec_dir):
    """Return a list of problems; empty means every file still matches the manifest."""
    rec_dir = Path(rec_dir)
    manifest = rec_dir / MANIFEST
    if not manifest.is_file():
        return [f"{MANIFEST} not found in {rec_dir}"]
    problems = []
    for line in manifest.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        digest, name = line.split("  ", 1)
        path = rec_dir / name
        if not path.is_file():
            problems.append(f"missing: {name}")
        elif _sha256(path) != digest:
            problems.append(f"modified: {name}")
    return problems
