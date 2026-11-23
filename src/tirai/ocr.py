"""OCR pass over the final video: find PII the DOM masking could not see (canvas grids, images, PDFs).

Frames are sampled with ffmpeg, read with tesseract (TSV with word boxes), matched against the same
PII rules as `privacy.mask`, and optionally blurred in place (`--fix` / `privacy.ocr: fix`).
"""

import csv
import io
import re
import shutil
import tempfile
from pathlib import Path

from tirai.system import ffmpeg_bin, run_text, tesseract_bin

PII = {
    "email": r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}",
    "phone": r"(?<![\d+])(?!\d{4}-\d\d?-\d\d?(?!\d))\+?\d[\d ().-]{7,}\d(?!\d)",
    "card": r"\b(?:\d[ -]?){12,18}\d\b",
    "token": r"\b(?:eyJ[\w-]{8,}\.[\w-]{8,}\.[\w-]+|(?:sk|pk|ghp|gho|ghs|xox[abp])[-_][A-Za-z0-9_-]{10,})\b",
}
UPSCALE = 2


def rules_regex(mask=None, patterns=None):
    parts = [PII[k] for k in (mask or PII)] + [str(p) for p in patterns or []]
    return re.compile("|".join(f"(?:{p})" for p in parts))


def hide(text):
    return text[:2] + "*" * max(3, len(text) - 2)


def read_words(png, lang=None):
    """[(line_key, text, (x, y, w, h))] from tesseract TSV, boxes in source-frame pixels."""
    cmd = [tesseract_bin(), str(png), "-", "--psm", "11", *(["-l", lang] if lang else []), "tsv"]
    p = run_text(cmd, timeout=120)
    if p.returncode:
        raise RuntimeError(f"tesseract failed: {p.stderr.strip()[:300]}")
    words = []
    for row in csv.DictReader(io.StringIO(p.stdout), delimiter="\t", quoting=csv.QUOTE_NONE):
        text = (row.get("text") or "").strip()
        if not text or row.get("conf") in (None, "-1"):
            continue
        box = tuple(int(row[k]) // UPSCALE for k in ("left", "top", "width", "height"))
        words.append(((row["block_num"], row["par_num"], row["line_num"]), text, box))
    return words


def find_hits(words, regex, keep=()):
    """Match the regex over each OCR line; return [(matched text, union box of the words it spans)]."""
    lines = {}
    for key, text, box in words:
        lines.setdefault(key, []).append((text, box))
    hits = []
    for items in lines.values():
        line, spans = "", []
        for text, box in items:
            start = len(line) + (1 if line else 0)
            line = f"{line} {text}" if line else text
            spans.append((start, start + len(text), box))
        for m in regex.finditer(line):
            if not m.group(0).strip() or m.group(0) in keep:
                continue
            boxes = [b for s, e, b in spans if s < m.end() and e > m.start()]
            x0, y0 = min(b[0] for b in boxes), min(b[1] for b in boxes)
            x1, y1 = max(b[0] + b[2] for b in boxes), max(b[1] + b[3] for b in boxes)
            hits.append((m.group(0), (x0, y0, x1 - x0, y1 - y0)))
    return hits


def scan(video, mask=None, patterns=None, keep=(), every=1.0, lang=None):
    """Return [{"t": seconds, "text": masked, "box": [x, y, w, h]}] for every PII match in sampled frames."""
    if not tesseract_bin():
        raise RuntimeError("tesseract not found; run `tirai setup --only ocr` or set TESSERACT_BIN")
    regex = rules_regex(mask, patterns)
    found = []
    with tempfile.TemporaryDirectory() as tmp:
        p = run_text(
            [ffmpeg_bin(), "-v", "error", "-i", str(video), "-vf",
             f"fps=1/{every},scale=iw*{UPSCALE}:ih*{UPSCALE}:flags=bicubic", str(Path(tmp) / "f-%05d.png")],
            timeout=1800,
        )  # fmt: skip
        if p.returncode:
            raise RuntimeError(f"ffmpeg frame extraction failed: {p.stderr.strip()[:300]}")
        for png in sorted(Path(tmp).glob("f-*.png")):
            t = (int(png.stem.split("-")[1]) - 1) * every
            for text, box in find_hits(read_words(png, lang), regex, set(keep)):
                found.append({"t": round(t, 2), "text": hide(text), "box": list(box)})
    return found


def regions(hits, every=1.0, pad=6):
    """Merge per-frame hits into blur regions [(x, y, w, h, t0, t1)] covering the frames around them."""
    out = []
    for h in sorted(hits, key=lambda h: h["t"]):
        x, y, w, hh = h["box"]
        box = (max(0, x - pad), max(0, y - pad), w + 2 * pad, hh + 2 * pad)
        t0, t1 = max(0.0, h["t"] - every), h["t"] + every
        for i, r in enumerate(out):
            same = all(abs(a - b) <= 12 for a, b in zip(r[:4], box, strict=True))
            if same and t0 <= r[5]:
                out[i] = (*r[:4], r[4], max(r[5], t1))
                break
        else:
            out.append((*box, t0, t1))
    return out


def redact(video, hits, every=1.0):
    """Pixelate every hit region in place (re-encodes the video, keeps audio and chapters)."""
    from tirai.compose import video_size

    fw, fh = video_size(video)
    regs = []
    for x, y, w, h, t0, t1 in regions(hits, every):
        x, y = min(x, fw - 2), min(y, fh - 2)
        regs.append((x, y, min(w, fw - x), min(h, fh - y), t0, t1))
    if not regs:
        return 0
    graph, last = [], "0:v"
    for i, (x, y, w, h, t0, t1) in enumerate(regs):
        # Pixelate (downscale + nearest upscale): unreadable at any box size, unlike boxblur's radius limits.
        graph.append(
            f"[0:v]crop={w}:{h}:{x}:{y},scale={max(1, w // 10)}:{max(1, h // 6)},scale={w}:{h}:flags=neighbor[b{i}]"
        )
        graph.append(f"[{last}][b{i}]overlay={x}:{y}:enable='between(t,{t0:.2f},{t1:.2f})'[v{i}]")
        last = f"v{i}"
    video = Path(video)
    tmp = video.with_name(video.stem + ".redacting" + video.suffix)
    p = run_text(
        [ffmpeg_bin(), "-y", "-v", "error", "-i", str(video), "-filter_complex", ";".join(graph),
         "-map", f"[{last}]", "-map", "0:a?", "-map_chapters", "0", "-c:a", "copy",
         "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p", str(tmp)],
        timeout=3600,
    )  # fmt: skip
    if p.returncode:
        tmp.unlink(missing_ok=True)
        raise RuntimeError(f"redaction failed: {p.stderr.strip()[:300]}")
    shutil.move(tmp, video)
    return len(regs)
