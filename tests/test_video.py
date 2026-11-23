from pathlib import Path

import pytest

from tirai import compose


def zstep(**zoom):
    return {"zoom": {"rect": [100, 100, 200, 40], "viewport": [1000, 500], **zoom}}


def test_zoom_filter_off_without_target():
    assert compose.zoom_filter({}, (1000, 500)) == ""


def test_zoom_filter_eases_to_target_center():
    f = compose.zoom_filter(zstep(factor=2), (1000, 500))
    assert "zoompan" in f and "1+1.000*" in f
    assert "clip(400.0-iw/zoom/2" in f and "clip(240.0-ih/zoom/2" in f  # centre (200,120) upscaled 2x


def test_zoom_factor_clamped_so_target_fits():
    f = compose.zoom_filter({"zoom": {"rect": [0, 0, 900, 40], "viewport": [1000, 500]}}, (1000, 500))
    assert f == ""  # a 900px-wide target can't be zoomed and still fit


def test_chapters_follow_final_times(tmp_path):
    tl = {
        "scenario": "Demo",
        "steps": [{"id": "S1", "title": "Open", "status": "passed", "final_start": 3.0, "final_end": 7.5}],
    }
    text = (tmp_path / compose.chapters_file(tmp_path, tl, 3.0)).read_text()
    assert text.startswith(";FFMETADATA1") and "START=3000\nEND=7500\ntitle=S1 Open (PASSED)" in text


def test_subtitle_languages_and_pick():
    tl = {"steps": [{"title": "t", "subtitle": {"en": "Hi", "vi": "Chào"}}, {"title": "u", "subtitle": "plain"}]}
    assert compose.subtitle_languages(tl) == ["en", "vi"]
    assert compose.subtitle_languages(tl, "vi") == ["vi", "en"]
    assert compose.subtitle_languages({**tl, "lang": "vi"}) == ["vi", "en"]
    assert compose.pick_subtitle(tl["steps"][0], "vi") == "Chào"
    assert compose.pick_subtitle(tl["steps"][0], "ja") == "Hi"
    assert compose.pick_subtitle(tl["steps"][1], "vi") == "plain"
    with pytest.raises(ValueError, match="no subtitles in 'ja'"):
        compose.subtitle_languages(tl, "ja")
    assert compose.subtitle_languages({"steps": [{"title": "t"}]}) == []


def test_split_source_defaults_to_previous_step(tmp_path):
    (tmp_path / "step-S1.png").write_bytes(b"png")
    tl = {"steps": [{"id": "S1", "screenshot": "step-S1.png"}, {"id": "S2", "layout": "split"}]}
    assert compose.split_source(tmp_path, tl, 2, tl["steps"][1]) == Path(tmp_path / "step-S1.png")
    assert compose.split_source(tmp_path, tl, 1, tl["steps"][0]) is None
