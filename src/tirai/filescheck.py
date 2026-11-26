"""File expectations for downloaded evidence: `expect: pdf` (pypdf) and `expect: xlsx` (openpyxl)."""

from pathlib import Path


def _need(mod, extra):
    try:
        return __import__(mod)
    except ImportError as e:
        raise RuntimeError(f"file checks need: pip install 'tirai[{extra}]'") from e


def _contains(haystack, needles):
    if needles is None:
        return [], []
    items = [needles] if isinstance(needles, str) else list(needles)
    missing = [n for n in items if n not in haystack]
    return items, missing


def check_pdf(path: Path, arg: dict) -> dict:
    """`expect: pdf`: page count (`pages: 2` or `pages: [1, 3]`) and text (`contains: str|[str]`)."""
    _need("pypdf", "pdf")
    from pypdf import PdfReader

    try:
        reader = PdfReader(str(path))
        n = len(reader.pages)
        texts = [p.extract_text() or "" for p in reader.pages]
    except Exception as e:  # noqa: BLE001 - pypdf raises many error types on broken files
        return {"type": "pdf", "expected": arg, "actual": f"unreadable: {e}", "ok": False}
    full = "\n".join(texts)
    _, missing = _contains(full, arg.get("contains"))
    pages = arg.get("pages")
    pages_ok = True
    if isinstance(pages, int):
        pages_ok = n == pages
    elif isinstance(pages, list):
        pages_ok = pages[0] <= n <= pages[1]
    actual = {"pages": n, "missing_text": missing} if missing or not pages_ok else {"pages": n}
    return {
        "type": "pdf",
        "expected": arg,
        "actual": actual,
        "ok": pages_ok and not missing,
    }


def pdf_page_count(path: Path) -> int:
    from pypdf import PdfReader

    return len(PdfReader(str(path)).pages)


def pdf_page_images(path: Path, out_dir: Path, dpi: int = 110) -> list[Path]:
    """Render each PDF page to a PNG (PyMuPDF); used by `tirai compose` to append pages to the video."""
    try:
        import pymupdf
    except ImportError:
        try:
            import fitz as pymupdf  # noqa: N812 - PyMuPDF's old module name
        except ImportError as e:
            raise RuntimeError("appending PDF pages needs: pip install 'tirai[pdf]'") from e
    out_dir.mkdir(parents=True, exist_ok=True)
    doc = pymupdf.open(str(path))
    try:
        zoom = dpi / 72
        out = []
        for i, page in enumerate(doc, 1):
            pix = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom))
            png = out_dir / f"{path.stem}-p{i}.png"
            pix.save(str(png))
            out.append(png)
        return out
    finally:
        doc.close()


def check_xlsx(path: Path, arg: dict) -> dict:
    """`expect: xlsx`: sheet names (`sheets: [...]`) and cell text (`contains: str|[str]`)."""
    _need("openpyxl", "excel")
    from openpyxl import load_workbook

    try:
        wb = load_workbook(str(path), read_only=True, data_only=True)
        names = wb.sheetnames
        cells = []
        for ws in wb.worksheets:
            ws.reset_dimensions()
            for row in ws.iter_rows(values_only=True):
                cells.extend(str(c) for c in row if c is not None)
        wb.close()
    except Exception as e:  # noqa: BLE001
        return {"type": "xlsx", "expected": arg, "actual": f"unreadable: {e}", "ok": False}
    hay = "\n".join(cells)
    _, missing = _contains(hay, arg.get("contains"))
    want_sheets = arg.get("sheets")
    sheets_ok = True
    if want_sheets is not None:
        want = [want_sheets] if isinstance(want_sheets, str) else list(want_sheets)
        sheets_ok = all(s in names for s in want)
    actual = {"sheets": names, "missing_text": missing} if missing or not sheets_ok else {"sheets": names}
    return {"type": "xlsx", "expected": arg, "actual": actual, "ok": sheets_ok and not missing}


def check_image(path: Path, arg: dict) -> dict:
    """`expect: image`: readable image file, optional OCR `contains: str|[str]`."""
    _need("PIL", "excel")
    from PIL import Image

    try:
        with Image.open(str(path)) as im:
            w, h = im.size
    except Exception as e:  # noqa: BLE001
        return {"type": "image", "expected": arg, "actual": f"unreadable: {e}", "ok": False}
    missing = []
    if arg.get("contains") is not None:
        from tirai.system import run_text, tesseract_bin

        tbin = tesseract_bin()
        if not tbin:
            return {
                "type": "image",
                "expected": arg,
                "actual": "tesseract not installed for contains check",
                "ok": False,
            }
        p = run_text([tbin, str(path), "stdout"])
        _, missing = _contains(p.stdout if p.returncode == 0 else "", arg.get("contains"))
    actual = {"size": [w, h], "missing_text": missing} if missing else {"size": [w, h]}
    return {"type": "image", "expected": arg, "actual": actual, "ok": not missing}
