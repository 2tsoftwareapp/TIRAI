"""Annotated visual previews for PDF, Excel (.xlsx) and image outputs appended to `final.mp4`.

Locates target values automatically:
- PDF: PyMuPDF `page.search_for(text)` (exact coordinates on any page) or explicit `{x, y, w, h}`.
- Excel: `openpyxl` rendered sheet grid with `cell: "E12"` / `"B2:E2"` or `text: "25,000"`.
- Image: explicit pixel/normalized `{x, y, w, h}` or `text: "..."` via `tesseract --tsv`.

Draws anti-aliased Snagit-style boxes, highlights, circles, directional arrows, spotlight dim,
and mixed Latin/Vietnamese + CJK callout labels directly onto the preview PNG.
"""

from __future__ import annotations

import csv
import io
import math
import re
from functools import lru_cache
from pathlib import Path

from tirai.system import find_font, run_text, tesseract_bin

PREVIEW_ANNOTATIONS = {"box", "arrow", "highlight", "circle", "badge"}
DIRS = {
    "left": (-1.0, 0.0),
    "right": (1.0, 0.0),
    "top": (0.0, -1.0),
    "bottom": (0.0, 1.0),
    "top-left": (-0.7, -0.7),
    "top-right": (0.7, -0.7),
    "bottom-left": (-0.7, 0.7),
    "bottom-right": (0.7, 0.7),
}
HEX_RE = re.compile(r"^#?[0-9a-fA-F]{6}$")
CELL_RE = re.compile(r"^([A-Za-z]{1,3})(\d+)$")


def hex_to_rgba(color: str, alpha: int = 255) -> tuple[int, int, int, int]:
    c = (color or "#e5252a").lstrip("#")
    if len(c) != 6 or not HEX_RE.match(c):
        c = "e5252a"
    return (int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16), alpha)


def _need_pillow():
    try:
        from PIL import Image, ImageDraw, ImageFont

        return Image, ImageDraw, ImageFont
    except ImportError as e:
        raise RuntimeError("annotated previews need: pip install 'tirai[excel]' (Pillow)") from e


@lru_cache(maxsize=8)
def _fc_font(pattern: str) -> str | None:
    try:
        p = run_text(["fc-match", "-f", "%{file}\n", pattern])
    except FileNotFoundError:
        return None
    if p.returncode == 0:
        path = p.stdout.strip().splitlines()[0] if p.stdout.strip() else ""
        if path and Path(path).is_file():
            return path
    return None


@lru_cache(maxsize=16)
def _font_cmap(path: str) -> frozenset[int]:
    try:
        from fontTools.ttLib import TTCollection, TTFont

        if path.lower().endswith(".ttc"):
            font = TTCollection(path).fonts[0]
        else:
            font = TTFont(path, lazy=True)
        try:
            cmap = font.getBestCmap() or {}
            return frozenset(cmap.keys())
        finally:
            font.close()
    except Exception:  # noqa: BLE001
        return frozenset()


class _FontChain:
    """Primary Latin/Vietnamese font + CJK fallback so mixed labels render without tofu boxes."""

    def __init__(self, size: int, preferred: str | None = None, bold: bool = True):
        _, _, ImageFont = _need_pillow()
        paths: list[str] = []
        if preferred:
            p = _fc_font(f"{preferred}:bold" if bold else preferred)
            if p:
                paths.append(p)
        base = find_font(bold=bold)
        if base and base not in paths:
            paths.append(base)
        for pat in ("Noto Sans CJK JP:bold" if bold else "Noto Sans CJK JP", ":lang=ja:bold" if bold else ":lang=ja"):
            p = _fc_font(pat)
            if p and p not in paths:
                paths.append(p)
        self.fonts = []
        for p in paths:
            try:
                self.fonts.append((ImageFont.truetype(p, size), _font_cmap(p)))
            except OSError:
                continue
        if not self.fonts:
            self.fonts.append((ImageFont.load_default(), frozenset()))
        self.size = size

    def _split(self, text: str):
        if len(self.fonts) == 1:
            return [(text, self.fonts[0][0])]
        runs = []
        cur_font, buf = None, []
        for ch in text:
            cp = ord(ch)
            chosen = self.fonts[0][0]
            if cp > 32:
                for fnt, cmap in self.fonts:
                    if not cmap or cp in cmap:
                        chosen = fnt
                        break
            if chosen is not cur_font:
                if buf:
                    runs.append(("".join(buf), cur_font))
                cur_font, buf = chosen, [ch]
            else:
                buf.append(ch)
        if buf:
            runs.append(("".join(buf), cur_font))
        return runs

    def measure(self, draw, text: str) -> tuple[int, int]:
        w, h = 0, self.size
        for part, fnt in self._split(text):
            box = draw.textbbox((0, 0), part, font=fnt)
            w += max(0, box[2] - box[0])
            h = max(h, box[3] - box[1])
        return int(w), int(h)

    def draw(self, draw, xy: tuple[float, float], text: str, fill):
        x, y = xy
        for part, fnt in self._split(text):
            draw.text((x, y), part, font=fnt, fill=fill)
            box = draw.textbbox((0, 0), part, font=fnt)
            x += max(0, box[2] - box[0])


def normalize_preview_annotations(annotate, contains=None) -> list[dict]:
    """Turn `annotate: true | 'auto' | [...]` into a normalized list of `{kind, ...}` dicts."""
    if not annotate:
        return []
    if annotate is True or annotate == "auto":
        items = [contains] if isinstance(contains, str) else list(contains or [])
        return [{"kind": "highlight", "text": str(t)} for t in items if str(t).strip()]
    out = []
    for entry in annotate:
        if not isinstance(entry, dict) or len(entry) != 1:
            continue
        ((kind, arg),) = entry.items()
        if kind not in PREVIEW_ANNOTATIONS:
            continue
        if isinstance(arg, str):
            out.append({"kind": kind, "text": arg})
        elif isinstance(arg, dict):
            out.append({"kind": kind, **arg})
    return out


def _resolve_explicit_rect(spec: dict, w: int, h: int) -> tuple[float, float, float, float] | None:
    if not all(k in spec for k in ("x", "y")):
        return None
    x, y = float(spec["x"]), float(spec["y"])
    rw = float(spec.get("w", 0.12 if x <= 1 and y <= 1 else 80))
    rh = float(spec.get("h", 0.05 if x <= 1 and y <= 1 else 30))
    if 0 <= x <= 1 and 0 <= y <= 1 and rw <= 1 and rh <= 1:
        return (x * w, y * h, (x + rw) * w, (y + rh) * h)
    return (x, y, x + rw, y + rh)


def _draw_callout_label(draw, text: str, pos: tuple[float, float], color_hex: str, font: _FontChain, iw: int, ih: int):
    tw, th = font.measure(draw, text)
    pad_x, pad_y = 12, 7
    bw, bh = tw + pad_x * 2, th + pad_y * 2
    lx = max(6, min(pos[0], iw - bw - 6))
    ly = max(6, min(pos[1], ih - bh - 6))
    shadow = (lx + 2, ly + 3, lx + bw + 2, ly + bh + 3)
    draw.rounded_rectangle(shadow, radius=8, fill=(0, 0, 0, 95))
    draw.rounded_rectangle((lx, ly, lx + bw, ly + bh), radius=8, fill=hex_to_rgba(color_hex, 245))
    font.draw(draw, (lx + pad_x, ly + pad_y - 1), text, fill=(255, 255, 255, 255))
    return (lx, ly, lx + bw, ly + bh)


def draw_annotations(
    image_path: Path,
    out_path: Path,
    located: list[dict],
    theme: dict | None = None,
    spotlight: bool = False,
) -> tuple[Path, list[float] | None, tuple[int, int]]:
    """Draw Snagit-style annotations onto `image_path` -> `out_path`; return `(path, union_rect, (w, h))`."""
    Image, ImageDraw, _ = _need_pillow()
    theme = theme or {}
    accent = theme.get("accent", "#2563eb")
    font_pref = theme.get("font")
    spot_op = float(theme.get("spotlight_opacity", 0.30))

    base = Image.open(str(image_path)).convert("RGBA")
    iw, ih = base.size
    overlay = Image.new("RGBA", (iw, ih), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay, "RGBA")
    label_font = _FontChain(max(16, round(min(iw, ih) * 0.022)), preferred=font_pref, bold=True)

    if spotlight and located:
        mask = Image.new("RGBA", (iw, ih), (15, 23, 42, int(round(max(0.0, min(0.85, spot_op)) * 255))))
        mdraw = ImageDraw.Draw(mask, "RGBA")
        for it in located:
            x0, y0, x1, y1 = it["rect"]
            mdraw.rounded_rectangle((x0 - 12, y0 - 12, x1 + 12, y1 + 12), radius=10, fill=(0, 0, 0, 0))
        base = Image.alpha_composite(base, mask)

    ux0, uy0, ux1, uy1 = float("inf"), float("inf"), float("-inf"), float("-inf")

    def grow(box):
        nonlocal ux0, uy0, ux1, uy1
        ux0, uy0 = min(ux0, box[0]), min(uy0, box[1])
        ux1, uy1 = max(ux1, box[2]), max(uy1, box[3])

    for idx, it in enumerate(located, 1):
        kind = it["kind"]
        x0, y0, x1, y1 = it["rect"]
        pad = int(it.get("padding", 4 if kind == "highlight" else 6))
        bx0, by0, bx1, by1 = x0 - pad, y0 - pad, x1 + pad, y1 + pad
        color = it.get("color") or ("#facc15" if kind == "highlight" else accent)
        width = int(it.get("width", 4))
        label = it.get("label")

        if kind == "highlight":
            draw.rounded_rectangle((bx0, by0, bx1, by1), radius=4, fill=hex_to_rgba(color, 95))
            draw.rounded_rectangle((bx0, by0, bx1, by1), radius=4, outline=hex_to_rgba(color, 210), width=2)
            grow((bx0, by0, bx1, by1))
        elif kind == "box":
            draw.rounded_rectangle((bx0, by0, bx1, by1), radius=8, outline=hex_to_rgba(color, 255), width=width)
            grow((bx0, by0, bx1, by1))
        elif kind == "circle":
            draw.ellipse((bx0 - 6, by0 - 6, bx1 + 6, by1 + 6), outline=hex_to_rgba(color, 255), width=width)
            grow((bx0 - 6, by0 - 6, bx1 + 6, by1 + 6))
        elif kind == "badge":
            r = 16
            cx, cy = bx0, by0
            draw.ellipse(
                (cx - r, cy - r, cx + r, cy + r),
                fill=hex_to_rgba(color, 255),
                outline=(255, 255, 255, 255),
                width=3,
            )
            num = str(it.get("n", idx))
            nw, nh = label_font.measure(draw, num)
            label_font.draw(draw, (cx - nw / 2, cy - nh / 2 - 2), num, fill=(255, 255, 255, 255))
            grow((cx - r, cy - r, cx + r, cy + r))
        elif kind == "arrow":
            direction = it.get("from", "top")
            dx, dy = DIRS.get(direction, DIRS["top"])
            cx, cy = (bx0 + bx1) / 2, (by0 + by1) / 2
            tip_x = cx + dx * (bx1 - bx0) / 2
            tip_y = cy + dy * (by1 - by0) / 2
            length = float(it.get("length", 68))
            tail_x = max(16, min(iw - 16, tip_x + dx * length))
            tail_y = max(16, min(ih - 16, tip_y + dy * length))
            ang = math.atan2(tip_y - tail_y, tip_x - tail_x)
            hl = 18
            rgba = hex_to_rgba(color, 255)
            draw.rounded_rectangle((bx0, by0, bx1, by1), radius=6, outline=rgba, width=max(2, width - 1))
            end_x = tip_x - math.cos(ang) * hl * 0.65
            end_y = tip_y - math.sin(ang) * hl * 0.65
            draw.line((tail_x, tail_y, end_x, end_y), fill=rgba, width=width + 1)
            p1 = (tip_x - hl * math.cos(ang - 0.48), tip_y - hl * math.sin(ang - 0.48))
            p2 = (tip_x - hl * math.cos(ang + 0.48), tip_y - hl * math.sin(ang + 0.48))
            draw.polygon([(tip_x, tip_y), p1, p2], fill=rgba)
            grow((min(bx0, tail_x), min(by0, tail_y), max(bx1, tail_x), max(by1, tail_y)))
            if label:
                tw, th = label_font.measure(draw, label)
                bw, bh = tw + 24, th + 14
                lx = tail_x + (-bw - 8 if dx < 0 else 8 if dx > 0 else -bw / 2)
                ly = tail_y + (-bh - 8 if dy < 0 else 8 if dy > 0 else -bh / 2)
                lbox = _draw_callout_label(draw, label, (lx, ly), color, label_font, iw, ih)
                grow(lbox)
                label = None

        if label:
            tw, th = label_font.measure(draw, label)
            bw, bh = tw + 24, th + 14
            pos = it.get("label_pos", "right")
            if pos == "top":
                lx, ly = bx0, by0 - bh - 10
            elif pos == "bottom":
                lx, ly = bx0, by1 + 10
            elif pos == "left":
                lx, ly = bx0 - bw - 10, (by0 + by1 - bh) / 2
            else:
                lx, ly = (bx1 + 10 if bx1 + 10 + bw < iw - 6 else bx0 - bw - 10), (by0 + by1 - bh) / 2
            lbox = _draw_callout_label(draw, label, (lx, ly), color, label_font, iw, ih)
            grow(lbox)

    composed = Image.alpha_composite(base, overlay).convert("RGB")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    composed.save(str(out_path))
    if math.isfinite(ux0):
        margin = 48
        rx = max(0.0, ux0 - margin)
        ry = max(0.0, uy0 - margin)
        rw = min(iw - rx, (ux1 - ux0) + margin * 2)
        rh = min(ih - ry, (uy1 - uy0) + margin * 2)
        return out_path, [rx, ry, rw, rh], (iw, ih)
    return out_path, None, (iw, ih)


def render_pdf_preview(
    pdf_path: Path,
    out_dir: Path,
    annotations: list[dict],
    theme: dict | None = None,
    spotlight: bool = False,
    dpi: int = 150,
) -> list[dict]:
    """Render each PDF page, locating any `text:` annotations with PyMuPDF `page.search_for()`."""
    try:
        import pymupdf
    except ImportError:
        try:
            import fitz as pymupdf  # noqa: N812
        except ImportError as e:
            raise RuntimeError("PDF preview needs: pip install 'tirai[pdf]'") from e

    out_dir.mkdir(parents=True, exist_ok=True)
    doc = pymupdf.open(str(pdf_path))
    pages_out = []
    scale = dpi / 72.0
    try:
        for i, page in enumerate(doc, 1):
            pix = page.get_pixmap(matrix=pymupdf.Matrix(scale, scale))
            raw = out_dir / f"{pdf_path.stem}-raw-p{i}.png"
            pix.save(str(raw))
            located = []
            for spec in annotations:
                want_page = spec.get("page")
                if want_page is not None and int(want_page) != i:
                    continue
                rect = _resolve_explicit_rect(spec, pix.width, pix.height)
                if rect is None and spec.get("text"):
                    hits = page.search_for(str(spec["text"]))
                    nth = int(spec.get("nth", 0))
                    if hits and nth < len(hits):
                        r = hits[nth]
                        rect = (r.x0 * scale, r.y0 * scale, r.x1 * scale, r.y1 * scale)
                if rect is not None:
                    located.append({**spec, "rect": rect})
            if located:
                ann_png = out_dir / f"{pdf_path.stem}-ann-p{i}.png"
                img, union, dims = draw_annotations(raw, ann_png, located, theme=theme, spotlight=spotlight)
            else:
                img, union, dims = raw, None, (pix.width, pix.height)
            pages_out.append({"page": i, "total": len(doc), "image": img, "rect": union, "size": dims})
    finally:
        doc.close()
    return pages_out


def _col_letter_to_idx(letters: str) -> int:
    n = 0
    for ch in letters.upper():
        n = n * 26 + (ord(ch) - ord("A") + 1)
    return n


def _idx_to_col_letter(n: int) -> str:
    out = []
    while n > 0:
        n, r = divmod(n - 1, 26)
        out.append(chr(ord("A") + r))
    return "".join(reversed(out))


def _parse_cell_ref(ref: str) -> tuple[int, int, int, int] | None:
    parts = str(ref).strip().split(":")
    m1 = CELL_RE.match(parts[0])
    if not m1:
        return None
    c1, r1 = _col_letter_to_idx(m1.group(1)), int(m1.group(2))
    if len(parts) == 2:
        m2 = CELL_RE.match(parts[1])
        if not m2:
            return None
        c2, r2 = _col_letter_to_idx(m2.group(1)), int(m2.group(2))
    else:
        c2, r2 = c1, r1
    return (min(r1, r2), min(c1, c2), max(r1, r2), max(c1, c2))


def render_xlsx_preview(
    xlsx_path: Path,
    out_dir: Path,
    annotations: list[dict],
    sheet: str | None = None,
    max_rows: int = 35,
    max_cols: int = 14,
    theme: dict | None = None,
    spotlight: bool = False,
) -> list[dict]:
    """Render an Excel sheet to a crisp PNG grid and draw annotations by `cell:` or `text:`."""
    Image, ImageDraw, _ = _need_pillow()
    try:
        from openpyxl import load_workbook
    except ImportError as e:
        raise RuntimeError("Excel preview needs: pip install 'tirai[excel]'") from e

    theme = theme or {}
    wb = load_workbook(str(xlsx_path), data_only=True)
    try:
        ws = wb[sheet] if sheet and sheet in wb.sheetnames else wb.active
        sheet_name = ws.title
        nrows = min(max_rows, max(1, ws.max_row or 1))
        ncols = min(max_cols, max(1, ws.max_column or 1))
        grid = []
        for r in range(1, nrows + 1):
            row_vals = []
            for c in range(1, ncols + 1):
                v = ws.cell(row=r, column=c).value
                row_vals.append("" if v is None else str(v))
            grid.append(row_vals)
    finally:
        wb.close()

    font = _FontChain(16, preferred=theme.get("font"), bold=False)
    bold_font = _FontChain(16, preferred=theme.get("font"), bold=True)
    probe = ImageDraw.Draw(Image.new("RGBA", (10, 10)))

    row_hdr_w = 54
    col_hdr_h = 34
    row_h = 32
    col_widths = []
    for c in range(ncols):
        max_w = 84
        for r in range(nrows):
            txt = grid[r][c][:40]
            if txt:
                tw, _ = font.measure(probe, txt)
                max_w = max(max_w, min(320, tw + 22))
        col_widths.append(max_w)

    iw = max(960, row_hdr_w + sum(col_widths) + 32)
    ih = max(540, col_hdr_h + nrows * row_h + 32)
    img = Image.new("RGB", (iw, ih), (255, 255, 255))
    draw = ImageDraw.Draw(img)

    # Header bar for column letters
    draw.rectangle((0, 0, iw, col_hdr_h), fill=(241, 245, 249))
    draw.rectangle((0, 0, row_hdr_w, ih), fill=(241, 245, 249))

    col_x = [row_hdr_w]
    for w in col_widths:
        col_x.append(col_x[-1] + w)

    for c in range(ncols):
        x0, x1 = col_x[c], col_x[c + 1]
        draw.rectangle((x0, 0, x1, col_hdr_h), outline=(203, 213, 225))
        lbl = _idx_to_col_letter(c + 1)
        tw, th = bold_font.measure(draw, lbl)
        bold_font.draw(draw, (x0 + (x1 - x0 - tw) / 2, (col_hdr_h - th) / 2 - 1), lbl, fill=(51, 65, 85))

    for r in range(nrows):
        y0 = col_hdr_h + r * row_h
        y1 = y0 + row_h
        draw.rectangle((0, y0, row_hdr_w, y1), outline=(203, 213, 225))
        rlbl = str(r + 1)
        tw, th = bold_font.measure(draw, rlbl)
        bold_font.draw(draw, ((row_hdr_w - tw) / 2, y0 + (row_h - th) / 2 - 1), rlbl, fill=(51, 65, 85))
        bg = (248, 250, 252) if r % 2 == 1 else (255, 255, 255)
        for c in range(ncols):
            x0, x1 = col_x[c], col_x[c + 1]
            draw.rectangle((x0, y0, x1, y1), fill=bg, outline=(226, 232, 240))
            txt = grid[r][c]
            if txt:
                if len(txt) > 38:
                    txt = txt[:37] + "…"
                font.draw(draw, (x0 + 8, y0 + 6), txt, fill=(15, 23, 42))

    out_dir.mkdir(parents=True, exist_ok=True)
    raw = out_dir / f"{xlsx_path.stem}-{sheet_name}-raw.png"
    img.save(str(raw))

    located = []
    for spec in annotations:
        want_sheet = spec.get("sheet")
        if want_sheet and want_sheet != sheet_name:
            continue
        rect = _resolve_explicit_rect(spec, iw, ih)
        if rect is None and spec.get("cell"):
            parsed = _parse_cell_ref(spec["cell"])
            if parsed:
                r1, c1, r2, c2 = parsed
                if 1 <= r1 <= nrows and 1 <= c1 <= ncols:
                    r2, c2 = min(r2, nrows), min(c2, ncols)
                    rect = (col_x[c1 - 1], col_hdr_h + (r1 - 1) * row_h, col_x[c2], col_hdr_h + r2 * row_h)
        if rect is None and spec.get("text"):
            needle = str(spec["text"])
            hits = []
            for r in range(nrows):
                for c in range(ncols):
                    if needle in grid[r][c]:
                        hits.append((col_x[c], col_hdr_h + r * row_h, col_x[c + 1], col_hdr_h + (r + 1) * row_h))
            nth = int(spec.get("nth", 0))
            if hits and nth < len(hits):
                rect = hits[nth]
        if rect is not None:
            located.append({**spec, "rect": rect})

    if located:
        ann_png = out_dir / f"{xlsx_path.stem}-{sheet_name}-ann.png"
        final_img, union, dims = draw_annotations(raw, ann_png, located, theme=theme, spotlight=spotlight)
    else:
        final_img, union, dims = raw, None, (iw, ih)
    return [{"page": 1, "total": 1, "sheet": sheet_name, "image": final_img, "rect": union, "size": dims}]


def _ocr_word_boxes(image_path: Path) -> list[dict]:
    bin_path = tesseract_bin()
    if not bin_path:
        return []
    p = run_text([bin_path, str(image_path), "stdout", "tsv"])
    if p.returncode != 0:
        return []
    words = []
    reader = csv.DictReader(io.StringIO(p.stdout), delimiter="\t")
    for row in reader:
        txt = (row.get("text") or "").strip()
        if not txt:
            continue
        try:
            x, y, w, h = int(row["left"]), int(row["top"]), int(row["width"]), int(row["height"])
        except (KeyError, ValueError):
            continue
        if w > 0 and h > 0:
            words.append({"text": txt, "rect": (float(x), float(y), float(x + w), float(y + h))})
    return words


def render_image_preview(
    image_path: Path,
    out_dir: Path,
    annotations: list[dict],
    theme: dict | None = None,
    spotlight: bool = False,
) -> list[dict]:
    """Annotate an existing PNG/JPG by explicit coords `{x,y,w,h}` or `text:` via tesseract OCR."""
    Image, _, _ = _need_pillow()
    with Image.open(str(image_path)) as im:
        iw, ih = im.size
    need_ocr = any(spec.get("text") and _resolve_explicit_rect(spec, iw, ih) is None for spec in annotations)
    words = _ocr_word_boxes(image_path) if need_ocr else []
    located = []
    for spec in annotations:
        rect = _resolve_explicit_rect(spec, iw, ih)
        if rect is None and spec.get("text") and words:
            needle = str(spec["text"]).strip()
            hits = [w["rect"] for w in words if needle.lower() in w["text"].lower()]
            nth = int(spec.get("nth", 0))
            if hits and nth < len(hits):
                rect = hits[nth]
        if rect is not None:
            located.append({**spec, "rect": rect})
    if located:
        out_dir.mkdir(parents=True, exist_ok=True)
        ann_png = out_dir / f"{image_path.stem}-ann.png"
        final_img, union, dims = draw_annotations(image_path, ann_png, located, theme=theme, spotlight=spotlight)
    else:
        final_img, union, dims = image_path, None, (iw, ih)
    return [{"page": 1, "total": 1, "image": final_img, "rect": union, "size": dims}]
