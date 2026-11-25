import json
import subprocess

import pytest

from tirai import compose


def test_srt_timestamps():
    assert compose.ts(0) == "00:00:00,000"
    assert compose.ts(3725.5) == "01:02:05,500"


def test_frame_size_env_override(monkeypatch, tmp_path):
    monkeypatch.setenv("TIRAI_VIDEO_SIZE", "1921x1081")
    assert compose.frame_size({"steps": []}, tmp_path) == (1920, 1080)
    monkeypatch.delenv("TIRAI_VIDEO_SIZE")
    assert compose.frame_size({"steps": []}, tmp_path) == compose.DEFAULT_SIZE


@pytest.mark.skipif(not compose.ffmpeg_bin() or not compose.find_font(), reason="needs ffmpeg and a font")
def test_compose_two_tab_segments(tmp_path):
    for name, color in (("seg-01-app.mp4", "blue"), ("seg-02-db.mp4", "purple")):
        subprocess.run(
            [
                "ffmpeg",
                "-loglevel",
                "error",
                "-y",
                "-f",
                "lavfi",
                "-i",
                f"color=c={color}:s=640x360:d=4:r=12",
                "-pix_fmt",
                "yuv420p",
                str(tmp_path / name),
            ],
            check=True,
        )
    step = {"title": "t", "subtitle": "Bước 1", "status": "passed", "checks": [{"type": "visible", "ok": True}]}
    tl = {
        "scenario": "demo",
        "mode": "record",
        "created": "2026-01-01 00:00:00",
        "tabs": {"app": {"label": "APP"}, "db": {"label": "DB"}},
        "segments": [],
        "steps": [
            {**step, "id": "S1", "tab": "app", "segment": "seg-01-app.mp4", "start": 0.5, "end": 2.5},
            {**step, "id": "S2", "tab": "db", "segment": "seg-02-db.mp4", "start": 1.0, "end": 3.0},
        ],
    }
    (tmp_path / "timeline.json").write_text(json.dumps(tl))
    final, seconds = compose.compose(tmp_path / "timeline.json", title_seconds=1.0)
    assert final.is_file()
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "stream=width,height:format=duration", "-of", "json", str(final)],
        capture_output=True,
        text=True,
        check=True,
    )
    info = json.loads(probe.stdout)
    assert (info["streams"][0]["width"], info["streams"][0]["height"]) == (640, 360 + compose.TOP + compose.BOTTOM)
    assert abs(float(info["format"]["duration"]) - seconds) < 0.3
    assert "Bước 1" in (tmp_path / "subtitles.srt").read_text(encoding="utf-8")
    assert "| S2 | DB |" in (tmp_path / "report.md").read_text(encoding="utf-8")


def test_build_ass_keeps_cjk_and_times():
    tl = {
        "scenario": "受注番号を確認 — Kiểm tra đơn hàng",
        "mode": "record",
        "created": "2026-01-01 00:00:00",
        "driver": "agent-browser",
        "tabs": {"app": {"label": "APP"}},
        "steps": [
            {
                "id": "S1",
                "tab": "app",
                "title": "受注番号を確認",
                "subtitle": "Xác nhận số đơn",
                "status": "passed",
                "final_start": 3.0,
                "final_end": 6.5,
            }
        ],
    }
    ass = compose.build_ass(tl, (1280, 720), 3.0)
    assert "ScriptType: v4.00+" in ass
    assert "PlayResX: " in ass and "PlayResY: 288" in ass
    assert "PlayResX=" not in ass and "PlayResY=" not in ass
    for name in ("Sub", "Hdr", "T1", "T2", "T3", "Pdf"):
        assert f"\nStyle: {name}," in ass
    assert "受注番号を確認" in ass  # CJK text is kept for libass font fallback
    assert ",Hdr," in ass and ",Sub," in ass and ",T1," in ass
    assert "0:00:03.00" in ass and "0:00:06.50" in ass


def test_pdf_page_ass_valid_headers(tmp_path):
    name = compose.pdf_page_ass(tmp_path, {"step": "S1", "file": "report.pdf"}, 1, 2, 1280, 720)
    ass = (tmp_path / name).read_text(encoding="utf-8")
    assert "ScriptType: v4.00+" in ass and "PlayResX: " in ass and "PlayResY: 288" in ass
    assert "\nStyle: Pdf," in ass
    assert "PDF report.pdf — page 1/2" in ass


def test_compose_rejects_dry_run(tmp_path):
    (tmp_path / "timeline.json").write_text(json.dumps({"mode": "dry-run"}))
    if not compose.ffmpeg_bin() or not compose.find_font():
        pytest.skip("needs ffmpeg and a font")
    with pytest.raises(ValueError):
        compose.compose(tmp_path / "timeline.json")
