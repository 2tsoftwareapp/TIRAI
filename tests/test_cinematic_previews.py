"""Tests for theme customization, cinematic zoom-in/out, human pacing, and annotated PDF/Excel/image previews."""

import json
import subprocess

import pytest

from tirai import compose, filescheck, previews, runner
from tirai.scenario import validate


def _base_scenario(**extra):
    return {
        "name": "Cinematic demo",
        "tabs": {"app": {"url": "http://app.test/", "label": "App"}},
        "steps": [
            {
                "id": "S1",
                "tab": "app",
                "title": "Step 1",
                "actions": [{"click": "#go"}],
                "expect": [{"visible": "#ok"}],
            }
        ],
        **extra,
    }


def test_validate_theme_pace_camera_and_preview_annotations():
    ok = _base_scenario(
        theme={
            "font": "Noto Sans",
            "header_size": 22,
            "subtitle_size": 24,
            "subtitle_height": 88,
            "subtitle_bg": "#111827",
            "subtitle_color": "#f8fafc",
            "tab_colors": ["#1d4ed8", "#6d28d9"],
            "pass_color": "#15803d",
            "fail_color": "#b91c1c",
            "accent": "#e11d48",
            "cursor_color": "#0f172a",
            "ripple_color": "#3b82f6",
            "spotlight_opacity": 0.35,
        },
        settings={"pace": "human", "camera": "annotate", "spotlight": True, "cursor_glide": True},
    )
    ok["steps"][0]["zoom"] = {"mode": "annotate", "factor": 1.7, "out": True}
    ok["steps"][0]["spotlight"] = True
    ok["steps"][0]["expect"].append(
        {
            "pdf": {
                "path": "out.pdf",
                "pages": 1,
                "contains": ["25,000"],
                "annotate": [{"arrow": {"text": "25,000", "label": "Total", "from": "top"}}],
                "zoom": True,
                "spotlight": True,
            }
        }
    )
    ok["steps"][0]["expect"].append(
        {
            "xlsx": {
                "path": "out.xlsx",
                "annotate": [{"box": {"cell": "B2", "label": "OK"}}],
                "preview": True,
            }
        }
    )
    ok["steps"][0]["expect"].append(
        {
            "image": {
                "path": "out.png",
                "annotate": [{"highlight": {"x": 0.1, "y": 0.2, "w": 0.3, "h": 0.1}}],
            }
        }
    )
    assert validate(ok) == []

    bad = _base_scenario(
        theme={"accent": "red", "spotlight_opacity": 0.99, "bogus": 1},
        settings={"pace": "turbo", "camera": "orbit"},
    )
    errs = validate(bad)
    assert any("theme.accent" in e for e in errs)
    assert any("theme.spotlight_opacity" in e for e in errs)
    assert any("theme.bogus" in e for e in errs)
    assert any("settings.pace" in e for e in errs)
    assert any("settings.camera" in e for e in errs)


def test_build_ass_applies_theme_and_shrinks_long_subtitle():
    long_sub = "Bước 5: " + "A" * 115
    tl = {
        "scenario": "Demo",
        "mode": "record",
        "created": "2026-01-01 00:00:00",
        "driver": "agent-browser",
        "theme": {"font": "CustomFont", "subtitle_color": "#00ff88", "subtitle_size": 24, "subtitle_height": 84},
        "tabs": {"app": {"label": "APP"}},
        "steps": [
            {
                "id": "S1",
                "tab": "app",
                "title": "Title",
                "subtitle": long_sub,
                "status": "passed",
                "final_start": 3.0,
                "final_end": 7.0,
            }
        ],
    }
    ass = compose.build_ass(tl, (1440, 900), 3.0)
    assert "Style: Sub,CustomFont," in ass
    assert "&H0088FF00" in ass  # BGR conversion of #00ff88
    assert "{\\fs" in ass  # long subtitle (>105 chars) shrinks automatically


def test_zoom_filter_supports_smooth_zoom_out():
    step = {"zoom": {"rect": [100, 100, 200, 80], "viewport": [1280, 720], "factor": 1.8, "at": 0.5, "out": True}}
    filt = compose.zoom_filter(step, (1280, 720), clip_start=0.0, clip_dur=4.0)
    assert "zoompan=" in filt
    assert "*(1-" in filt  # ease-out multiplier present

    no_out = {"zoom": {"rect": [100, 100, 200, 80], "viewport": [1280, 720], "factor": 1.8, "at": 0.5}}
    filt2 = compose.zoom_filter(no_out, (1280, 720), clip_start=0.0, clip_dur=4.0)
    assert "zoompan=" in filt2 and "*(1-" not in filt2


def test_runner_human_pace_glides_cursor_and_types_when_recording(monkeypatch, tmp_path):
    from test_runner import FakeDriver

    d = FakeDriver()
    typed = []
    monkeypatch.setattr(d, "type_text", lambda tab, sel, val: typed.append((sel, val)), raising=False)
    evals = []

    def eval_fn(tab, expr):
        evals.append(expr)
        if "innerWidth,innerHeight" in expr:
            return [100, 120, 200, 40, 1280, 720]
        if "type==='password'" in expr:
            return False
        if "__ann.cursorMove" in expr:
            return 200
        if "__ann.bounds()" in expr:
            return [90, 110, 260, 70, 1280, 720]
        return [True, "ok"]

    monkeypatch.setattr(d, "evaluate", eval_fn)
    monkeypatch.setattr(runner, "make_driver", lambda *a, **k: d)
    monkeypatch.setattr(runner.Runner, "pause", lambda self, s: None)
    monkeypatch.setattr(runner.time, "sleep", lambda s: None)

    sc = _base_scenario(
        theme={"accent": "#ff00aa", "cursor_color": "#000000", "ripple_color": "#2563eb"},
        settings={"pace": "human", "camera": "annotate", "spotlight": True},
    )
    sc["steps"][0]["actions"] = [
        {"fill": {"selector": "#code", "value": "ORDER-123"}},
        {"click": "#go"},
    ]
    sc["steps"][0]["annotate"] = [{"box": {"target": "#go", "label": "Done"}}]

    # Dry-run skips cursor glide and chunked typing
    runner.run(sc, tmp_path / "dry", record=False, hold=0)
    assert typed == []
    assert not any("__ann.cursorMove" in e for e in evals)

    # Record enables smooth cursor glide, click ripple, chunked typing, spotlight and annotate zoom-in/out
    tl = runner.run(sc, tmp_path / "rec", record=True, hold=0)
    assert "".join(v for _, v in typed) == "ORDER-123"
    assert len(typed) > 1
    assert any("__ann.cursorMove" in e for e in evals)
    assert any("__ann.cursorClick" in e for e in evals)
    assert any("__ann.spotlight()" in e for e in evals)
    assert tl["theme"]["accent"] == "#ff00aa"
    z = tl["steps"][0]["zoom"]
    assert z["rect"] == [90, 110, 260, 70] and z["out"] is True


def test_annotated_pdf_xlsx_image_previews_and_compose(tmp_path):
    pymupdf = pytest.importorskip("pymupdf")
    openpyxl = pytest.importorskip("openpyxl")
    PIL_Image = pytest.importorskip("PIL.Image")

    # 1. Create a real 1-page PDF with values to annotate
    pdf_path = tmp_path / "sample.pdf"
    doc = pymupdf.open()
    page = doc.new_page(width=595, height=420)
    page.insert_text((72, 90), "Order No: 1800000001", fontsize=16)
    page.insert_text((72, 140), "Ship Date: 2018/09/20", fontsize=14)
    page.insert_text((320, 220), "Total: 27,000", fontsize=16)
    doc.save(str(pdf_path))
    doc.close()

    pdf_pages = previews.render_pdf_preview(
        pdf_path,
        tmp_path / "pdf_out",
        previews.normalize_preview_annotations(
            [
                {"arrow": {"text": "2018/09/20", "label": "Ngày giao mới", "from": "top"}},
                {"box": {"text": "27,000", "label": "合計 27,000"}},
            ]
        ),
        theme={"accent": "#e11d48"},
        spotlight=True,
    )
    assert len(pdf_pages) == 1
    assert pdf_pages[0]["image"].is_file()
    assert pdf_pages[0]["rect"] is not None

    # 2. Create a real Excel workbook and render annotated sheet preview
    xlsx_path = tmp_path / "sample.xlsx"
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Orders"
    ws.append(["OrderNo", "Qty", "Amount"])
    ws.append(["1800000001", 15, "27,000"])
    wb.save(str(xlsx_path))
    wb.close()

    xlsx_pages = previews.render_xlsx_preview(
        xlsx_path,
        tmp_path / "xlsx_out",
        previews.normalize_preview_annotations(
            [
                {"box": {"cell": "B2", "label": "SL = 15"}},
                {"arrow": {"text": "27,000", "label": "Tổng 27,000", "from": "right"}},
            ]
        ),
        spotlight=True,
    )
    assert len(xlsx_pages) == 1
    assert xlsx_pages[0]["image"].is_file()
    assert xlsx_pages[0]["rect"] is not None

    # 3. Create a real PNG and annotate with normalized coords
    png_path = tmp_path / "sample.png"
    PIL_Image.new("RGB", (640, 360), (245, 247, 250)).save(str(png_path))
    chk = filescheck.check_image(png_path, {"path": "sample.png"})
    assert chk["ok"] and chk["actual"]["size"] == [640, 360]

    img_pages = previews.render_image_preview(
        png_path,
        tmp_path / "img_out",
        previews.normalize_preview_annotations([{"box": {"x": 0.2, "y": 0.3, "w": 0.3, "h": 0.2, "label": "Target"}}]),
    )
    assert len(img_pages) == 1 and img_pages[0]["image"].is_file() and img_pages[0]["rect"] is not None

    # 4. Compose a short video appending both annotated PDF (zoomed) and Excel previews
    if not compose.ffmpeg_bin() or not compose.find_font():
        pytest.skip("needs ffmpeg and a font")
    seg = tmp_path / "seg-01-app.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-loglevel",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "color=c=navy:s=640x360:d=3:r=15",
            "-pix_fmt",
            "yuv420p",
            str(seg),
        ],
        check=True,
    )
    tl = {
        "scenario": "Annotated preview demo",
        "mode": "record",
        "created": "2026-01-01 00:00:00",
        "theme": {"subtitle_height": 84, "accent": "#e11d48"},
        "tabs": {"app": {"label": "APP"}},
        "segments": [{"file": "seg-01-app.mp4"}],
        "steps": [
            {
                "id": "S1",
                "tab": "app",
                "title": "Done",
                "subtitle": "Kiểm tra xong — xem preview PDF & Excel",
                "status": "passed",
                "segment": "seg-01-app.mp4",
                "start": 0.5,
                "end": 2.0,
                "checks": [{"type": "pdf", "ok": True}],
            }
        ],
        "previews": [
            {
                "step": "S1",
                "kind": "pdf",
                "file": "sample.pdf",
                "path": "sample.pdf",
                "ok": True,
                "annotate": [{"arrow": {"text": "27,000", "label": "27,000 ✓", "from": "top"}}],
                "zoom": True,
                "spotlight": True,
                "hold": 2.5,
                "title": "PDF Preview (annotated)",
                "subtitle": "Tổng tiền 27,000 khớp DB",
            },
            {
                "step": "S1",
                "kind": "xlsx",
                "file": "sample.xlsx",
                "path": "sample.xlsx",
                "ok": True,
                "annotate": [{"box": {"cell": "C2", "label": "27,000"}}],
                "zoom": True,
                "hold": 2.0,
            },
        ],
    }
    (tmp_path / "timeline.json").write_text(json.dumps(tl))
    final, _ = compose.compose(tmp_path / "timeline.json", title_seconds=1.0)
    assert final.is_file()
    dur = compose.video_duration(final)
    assert dur >= 6.0  # title (1s) + step (~1.8s) + pdf preview (2.5s) + xlsx preview (2.0s)
    tl_final = json.loads((tmp_path / "timeline.final.json").read_text(encoding="utf-8"))
    assert all(p.get("appended") for p in tl_final["previews"])


def test_validate_step_by_step_action_annotate_and_expect_labels():
    ok = _base_scenario(
        settings={
            "pace": "human",
            "camera": "action",
            "action_annotate": True,
            "action_zoom": 1.65,
            "action_hold": 0.3,
            "show_expects": True,
            "expect_pos": "top-right",
        }
    )
    ok["steps"][0]["action_annotate"] = True
    ok["steps"][0]["show_expects"] = True
    ok["steps"][0]["zoom"] = "action"
    ok["steps"][0]["actions"] = [
        {"clear": {"selector": "#qty", "label": "Xóa SL cũ"}},
        {"fill": {"selector": "#qty", "value": "10", "label": "Nhập SL = 10", "zoom": 1.8}},
        {"click": {"selector": "#go", "label": "Nhấn Lưu"}},
    ]
    ok["steps"][0]["expect"] = [
        {"visible": {"selector": "#ok", "label": "Hiển thị thông báo OK"}},
        {"not_visible": {"selector": "#err", "label": "Không có lỗi"}},
        {"url_contains": {"text": "/done", "label": "Chuyển sang trang /done"}},
        {"value": {"selector": "#qty", "equals": "10", "label": "SL hiển thị = 10"}},
    ]
    assert validate(ok) == []

    bad = _base_scenario(
        settings={
            "action_annotate": "yes",
            "action_zoom": 0.5,
            "action_hold": -1,
            "show_expects": 1,
            "expect_pos": "center",
        }
    )
    bad["steps"][0]["actions"] = [{"click": {"label": "missing selector"}}]
    bad["steps"][0]["expect"] = [
        {"visible": {"label": "missing selector"}},
        {"url_contains": {"label": "missing text"}},
    ]
    errs = validate(bad)
    assert any("settings.action_annotate" in e for e in errs)
    assert any("settings.action_zoom" in e for e in errs)
    assert any("settings.action_hold" in e for e in errs)
    assert any("settings.show_expects" in e for e in errs)
    assert any("settings.expect_pos" in e for e in errs)
    assert any("click mapping is missing selector" in e for e in errs)
    assert any("visible mapping is missing selector" in e for e in errs)
    assert any("url_contains mapping is missing text" in e for e in errs)


def test_follow_filter_supports_action_zoom_out():
    step = {
        "zoom": {
            "follow": [
                {"t": 0.6, "rect": [100, 120, 160, 40], "viewport": [1280, 720]},
                {"t": 1.8, "rect": [400, 220, 120, 36], "viewport": [1280, 720]},
            ],
            "factor": 1.65,
            "out": True,
            "out_at": 2.6,
        }
    }
    filt = compose.zoom_filter(step, (1280, 720), clip_start=0.2, clip_dur=4.5)
    assert "zoompan=" in filt
    assert "*(1-" in filt  # eases back out to 1.0x for expects/result HUD


def test_runner_action_annotate_zoom_and_expect_hud(monkeypatch, tmp_path):
    from test_runner import FakeDriver

    d = FakeDriver()
    evals = []

    def eval_fn(tab, expr):
        evals.append(expr)
        if "innerWidth,innerHeight" in expr:
            return [120, 140, 180, 40, 1280, 720]
        if "targetLabel" in expr:
            return "Lưu đơn"
        if "type==='password'" in expr:
            return False
        if "__ann.actionCallout" in expr:
            return [114, 134, 192, 52, 1280, 720]
        if "__ann.expectHud" in expr:
            return True
        if "e.value" in expr:
            return [False, "15"]
        return [True, "ok"]

    monkeypatch.setattr(d, "evaluate", eval_fn)
    monkeypatch.setattr(runner, "make_driver", lambda *a, **k: d)
    monkeypatch.setattr(runner.Runner, "pause", lambda self, s: None)
    monkeypatch.setattr(runner.time, "sleep", lambda s: None)

    sc = _base_scenario(
        settings={
            "pace": "human",
            "camera": "action",
            "action_annotate": True,
            "show_expects": True,
            "spotlight": True,
        }
    )
    sc["steps"][0]["actions"] = [
        {"fill": {"selector": "#qty", "value": "10", "label": "Sửa SL = 10"}},
        {"click": {"selector": "#go"}},
    ]
    sc["steps"][0]["expect"] = [
        {"visible": {"selector": "#ok", "label": "Hiện nút OK"}},
        {"value": {"selector": "#qty", "equals": "10", "label": "SL = 10"}},
    ]
    sc["steps"][0]["annotate"] = [{"box": {"target": "#ok", "label": "Kết quả"}}]

    # Dry-run stays fast: no actionCallout or expectHud
    runner.run(sc, tmp_path / "dry", record=False, hold=0)
    assert not any("__ann.actionCallout" in e for e in evals)
    assert not any("__ann.expectHud" in e for e in evals)

    # Record draws action callouts, clears them, renders per-expect HUD (including FAIL detail),
    # keeps HUD alive during step annotate, and records camera follow + ease-out at expect start.
    evals.clear()
    tl = runner.run(sc, tmp_path / "rec", record=True, hold=0)
    assert any("__ann.actionCallout" in e and "Sửa SL = 10" in e for e in evals)
    assert any("__ann.actionCallout" in e and "Click: Lưu đơn" in e for e in evals)
    assert any("__ann.clearAction" in e for e in evals)
    assert any("__ann.expectHud" in e and "Hiện nút OK" in e for e in evals)
    assert any("__ann.expectHud" in e and "actual: 15" in e for e in evals)
    assert any("keepHud:true" in e for e in evals)
    st = tl["steps"][0]
    assert st["status"] == "failed"
    assert st["checks"][0]["label"] == "Hiện nút OK"
    assert st["zoom"]["out"] is True
    assert st["zoom"]["out_at"] is not None
    assert len(st["zoom"]["follow"]) == 2


def test_dry_run_performance_skips_overhead_and_keeps_fail_screenshots(monkeypatch, tmp_path):
    from test_runner import FakeDriver

    d = FakeDriver()
    evals = []
    shots = []

    def eval_fn(tab, expr):
        evals.append(expr)
        if "#missing" in expr:
            return [False, "not found"]
        return [True, "ok"]

    monkeypatch.setattr(d, "evaluate", eval_fn)
    monkeypatch.setattr(d, "screenshot", lambda tab, path: shots.append(path))
    monkeypatch.setattr(runner, "make_driver", lambda *a, **k: d)
    monkeypatch.setattr(runner.time, "sleep", lambda s: None)

    sc = _base_scenario()
    sc["steps"].append(
        {
            "id": "S2",
            "tab": "app",
            "title": "Failing step",
            "actions": [{"click": "#go"}],
            "expect": [{"visible": "#missing"}],
        }
    )
    sc["settings"] = {"expect_timeout": 0.01}

    tl = runner.run(sc, tmp_path / "dry", record=False)
    # Dry-run skips annotate.js injection and skips screenshots on PASS steps, but still screenshots FAIL steps.
    assert not any("__ann.clear" in e for e in evals)
    assert tl["steps"][0]["status"] == "passed"
    assert "screenshot" not in tl["steps"][0]
    assert tl["steps"][1]["status"] == "failed"
    assert tl["steps"][1]["screenshot"] == "step-S2.png"
    assert len(shots) == 1
    assert tl["hold"] == 0.0


def test_agentbrowser_avoids_redundant_tab_resets(monkeypatch):
    from tirai.agentbrowser import AgentBrowser

    ab = AgentBrowser(session="s1")
    ab.active = "t1"
    monkeypatch.setattr(ab, "run", lambda *a, **k: {})

    # With expect_popups=False, click and press keep active tab cached
    ab.expect_popups = False
    ab.click("t1", "#btn")
    assert ab.active == "t1"
    ab.press("t1", "Enter")
    assert ab.active == "t1"

    # With expect_popups=True, non-nav keys like Tab keep active tab, while Enter/click reset it
    ab.expect_popups = True
    ab.press("t1", "Tab")
    assert ab.active == "t1"
    ab.press("t1", "Enter")
    assert ab.active is None


def test_step_voice_field_validation_and_pick_voice():
    """step.voice is validated like subtitle and preferred by compose.pick_voice over subtitle."""
    from tirai.compose import pick_voice
    from tirai.scenario import validate

    sc = {
        "name": "Voice test",
        "tabs": {"app": {"url": "https://example.test"}},
        "steps": [
            {
                "id": "S1",
                "tab": "app",
                "title": "Step 1",
                "subtitle": {"vi": "AB03001 受注入力: 得意先=010001"},
                "voice": {"vi": "Bước 1, mở màn hình nhập đơn hàng và chọn khách hàng."},
                "actions": [{"wait": 10}],
                "expect": [{"visible": "#ok"}],
            }
        ],
    }
    assert validate(sc) == []

    bad = {**sc, "steps": [{**sc["steps"][0], "voice": {}}]}
    assert any("voice must be text or a non-empty map" in e for e in validate(bad))

    step_with_voice = sc["steps"][0]
    assert pick_voice(step_with_voice, "vi") == "Bước 1, mở màn hình nhập đơn hàng và chọn khách hàng."
    assert pick_voice({"title": "T", "subtitle": "On-screen note", "voice": "Spoken note"}, "en") == "Spoken note"
    assert pick_voice({"title": "T", "subtitle": "Fallback note"}, "en") == "Fallback note"
