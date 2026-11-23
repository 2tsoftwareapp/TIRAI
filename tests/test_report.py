import struct
import zlib

from tirai import report


def _png(path):
    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d))

    raw = b"\x00\xff\x00\x00"
    path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b"")
    )


def _timeline():
    return {
        "scenario": "Demo <x>",
        "created": "2026-11-23 10:00:00",
        "total_steps": 2,
        "tabs": {"app": {"label": "Web app"}},
        "steps": [
            {
                "id": "S1", "title": "ok", "tab": "app", "status": "passed", "screenshot": "step-S1.png",
                "final_start": 3.0, "final_end": 8.0,
                "checks": [{"type": "visible", "ok": True, "expected": "#a", "actual": "rect"}],
            },
            {
                "id": "S2", "title": "bad", "tab": "app", "status": "failed", "final_start": 8.0, "final_end": 12.0,
                "checks": [{"type": "count", "ok": False, "expected": {"equals": 3}, "actual": 2}],
            },
        ],
    }  # fmt: skip


def test_html_xlsx_and_manifest_roundtrip(tmp_path):
    _png(tmp_path / "step-S1.png")
    (tmp_path / "final.mp4").write_bytes(b"video")
    tl = _timeline()
    page = report.write_html(tmp_path, tl, "final.mp4").read_text(encoding="utf-8")
    assert "Demo &lt;x&gt;" in page and "data:image/png;base64," in page and "seek(8.0)" in page
    assert "actual: 2" in page
    xlsx = report.write_xlsx(tmp_path, tl, "final.mp4")
    assert xlsx is None or xlsx.stat().st_size > 0
    manifest = report.write_manifest(tmp_path).read_text()
    assert "final.mp4" in manifest and "report.html" in manifest
    assert report.verify(tmp_path) == []
    (tmp_path / "final.mp4").write_bytes(b"edited")
    (tmp_path / "step-S1.png").unlink()
    assert sorted(report.verify(tmp_path)) == ["missing: step-S1.png", "modified: final.mp4"]


def test_verify_without_manifest(tmp_path):
    assert report.verify(tmp_path) == [f"{report.MANIFEST} not found in {tmp_path}"]
