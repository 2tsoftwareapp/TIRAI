import shutil
import subprocess

import pytest

from tirai import tts


def test_mix_graph_places_each_clip_at_its_step():
    g = tts.mix_args([("a.wav", 3.2, 2.0), ("b.wav", 7.0, 1.5)])
    assert "[1:a]atrim=0:2.000" in g and "adelay=3200|3200" in g and "adelay=7000|7000" in g
    assert g.endswith("amix=inputs=2:normalize=0,apad[voice]")


def test_custom_command_engine(tmp_path, monkeypatch):
    py = shutil.which("python3") or shutil.which("python")
    script = tmp_path / "fake_tts.py"
    script.write_text("import sys,shutil; shutil.copyfile(sys.argv[1], sys.argv[2])")
    monkeypatch.setenv("TIRAI_TTS_CMD", f'"{py}" "{script}" {{text}} {{out}}')
    out = tts.synth("hello", tmp_path / "v.wav", engine="cmd")
    assert out.read_text(encoding="utf-8") == "hello"


@pytest.mark.skipif(not (shutil.which("espeak-ng") and shutil.which("ffprobe")), reason="espeak-ng not installed")
def test_espeak_writes_audio(tmp_path):
    out = tts.synth("Step one passed", tmp_path / "v.wav", lang="en", engine="espeak")
    p = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(out)],
                       capture_output=True, text=True)  # fmt: skip
    assert float(p.stdout) > 0.5


def test_no_engine_is_a_clear_error(tmp_path, monkeypatch):
    monkeypatch.setattr(tts, "available", lambda engine="auto": None)
    with pytest.raises(RuntimeError, match="no speech engine"):
        tts.synth("x", tmp_path / "v.wav")
