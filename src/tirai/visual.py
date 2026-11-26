"""`tirai diff OLD NEW`: compare the per-step screenshots of two runs of the same scenario.

Each run folder keeps `step-<id>.png` (taken at the end of every recorded step, annotations included).
Steps are paired by id; a step whose share of changed pixels is above the threshold, or that exists in only
one run, counts as changed. Writes `<out>/diff.json`, `<out>/diff.html` and one `<id>.png` per changed step
(old | new | changes in red).
"""

import html
import json
from pathlib import Path

TOLERANCE = 24  # per-channel difference below this is noise (anti-aliasing, video-style compression)


def _pil():
    try:
        from PIL import Image, ImageChops, ImageDraw
    except ImportError as e:
        raise RuntimeError("tirai diff needs Pillow: pip install 'tirai[diff]'") from e
    return Image, ImageChops, ImageDraw


def run_dir(path):
    """The folder that holds timeline.json: the path itself, else its record/ or dry-run/ folder."""
    p = Path(path)
    for d in (p, p / "record", p / "dry-run"):
        if (d / "timeline.json").is_file():
            return d
    raise FileNotFoundError(f"{p}: no timeline.json (pass an evidence folder or its record/ folder)")


def shots(d):
    tl = json.loads((d / "timeline.json").read_text(encoding="utf-8"))
    return tl["scenario"], {
        s["id"]: (s.get("title", ""), d / s["screenshot"]) for s in tl["steps"] if s.get("screenshot")
    }


def compare(old_png, new_png, out_png=None):
    """(changed share 0..1, bbox of the changes or None, size_changed). Writes old|new|changes when `out_png`."""
    Image, ImageChops, ImageDraw = _pil()
    a = Image.open(old_png).convert("RGB")
    b = Image.open(new_png).convert("RGB")
    size_changed = a.size != b.size
    if size_changed:
        b = b.resize(a.size)
    diff = ImageChops.difference(a, b).convert("L").point(lambda v: 255 if v > TOLERANCE else 0)
    changed = sum(diff.histogram()[255:]) / (a.width * a.height)
    box = diff.getbbox()
    if out_png is not None:
        red = Image.new("RGB", a.size, (220, 38, 38))
        marked = Image.composite(red, b.point(lambda v: v // 3 + 140), diff)
        if box:
            ImageDraw.Draw(marked).rectangle(box, outline=(220, 38, 38), width=3)
        sheet = Image.new("RGB", (a.width * 3 + 16, a.height), (15, 23, 42))
        for i, img in enumerate((a, b, marked)):
            sheet.paste(img, (i * (a.width + 8), 0))
        sheet.save(out_png)
    return changed, box, size_changed


def diff(old, new, out, threshold=0.5):
    """Compare two runs; returns the report dict. `threshold` is the % of changed pixels a step may have."""
    old_d, new_d = run_dir(old), run_dir(new)
    name, a = shots(old_d)
    _, b = shots(new_d)
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    rows = []
    for sid in [*a, *(k for k in b if k not in a)]:
        title = (a.get(sid) or b.get(sid))[0]
        row = {"id": sid, "title": title}
        if sid not in a or sid not in b or not a[sid][1].is_file() or not b[sid][1].is_file():
            row.update(status="missing", note="only in " + ("new" if sid not in a else "old") + " run")
            if sid in a and sid in b:
                row["note"] = "screenshot file missing"
            rows.append(row)
            continue
        image = out / f"{sid}.png"
        share, box, resized = compare(a[sid][1], b[sid][1], image)
        pct = round(share * 100, 2)
        row.update(changed_pct=pct, bbox=list(box) if box else None, size_changed=resized)
        row["status"] = "changed" if pct > threshold or resized else "same"
        if row["status"] == "same":
            image.unlink()
        else:
            row["image"] = image.name
        rows.append(row)
    report = {"scenario": name, "old": str(old_d), "new": str(new_d), "threshold_pct": threshold, "steps": rows}
    (out / "diff.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    (out / "diff.html").write_text(page(report), encoding="utf-8")
    return report


def page(report):
    e = html.escape
    body = []
    for r in report["steps"]:
        detail = r.get("note") or f"{r['changed_pct']}% pixels changed" + (
            " (size changed)" if r.get("size_changed") else ""
        )
        img = f'<img src="{e(r["image"])}" alt="old, new, changes">' if r.get("image") else ""
        body.append(
            f'<section class="{r["status"]}"><h2>{e(r["id"])} {e(r["title"])} <span>{r["status"].upper()}</span></h2>'
            f"<p>{e(detail)}</p>{img}</section>"
        )
    changed = sum(r["status"] != "same" for r in report["steps"])
    return f"""<!doctype html><meta charset="utf-8"><title>Visual diff: {e(report["scenario"])}</title>
<style>body{{font:15px system-ui,sans-serif;margin:24px;background:#f8fafc;color:#0f172a}}
section{{background:#fff;border:1px solid #e2e8f0;border-radius:8px;padding:12px 16px;margin:12px 0}}
h2{{font-size:16px;margin:0 0 4px}}
h2 span{{font-size:12px;padding:2px 8px;border-radius:10px;color:#fff;background:#16a34a}}
.changed h2 span,.missing h2 span{{background:#dc2626}}
img{{max-width:100%;margin-top:8px}} p{{margin:0;color:#475569}}</style>
<h1>Visual diff: {e(report["scenario"])}</h1>
<p>{changed}/{len(report["steps"])} steps differ (threshold {report["threshold_pct"]}% of pixels).
Old: <code>{e(report["old"])}</code> · New: <code>{e(report["new"])}</code>.
Each image shows old | new | changes in red.</p>
{"".join(body)}
"""
