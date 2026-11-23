"""Voice-over: speak each step's subtitle with the OS speech engine and mix it under the final video.

Engines (auto order): $TIRAI_TTS_CMD template, macOS `say`, Windows SAPI (PowerShell System.Speech),
`espeak-ng`/`espeak`. Template placeholders: {text} (UTF-8 text file), {out} (wav to write), {lang}.
"""

import os
import shlex
import shutil
from pathlib import Path

from tirai.system import IS_MAC, IS_WINDOWS, run_text

ENGINES = ("cmd", "say", "sapi", "espeak")


def available(engine="auto"):
    """Return the engine name to use, or None."""
    order = ENGINES if engine in (None, "auto", True) else (engine,)
    for name in order:
        if name == "cmd" and os.environ.get("TIRAI_TTS_CMD"):
            return name
        if name == "say" and IS_MAC and shutil.which("say"):
            return name
        if name == "sapi" and IS_WINDOWS and shutil.which("powershell"):
            return name
        if name == "espeak" and (shutil.which("espeak-ng") or shutil.which("espeak")):
            return name
    return None


def synth(text, out, lang=None, engine="auto"):
    """Write speech for `text` to `out` (wav/aiff). Raises RuntimeError when no engine works."""
    name = available(engine)
    if not name:
        raise RuntimeError("no speech engine: install espeak-ng (Linux), or set TIRAI_TTS_CMD")
    out = Path(out)
    txt = out.with_suffix(".txt")
    txt.write_text(text, encoding="utf-8")
    voice = os.environ.get("TIRAI_TTS_VOICE")
    if name == "cmd":
        cmd = [a.format(text=txt, out=out, lang=lang or "en") for a in shlex.split(os.environ["TIRAI_TTS_CMD"])]
    elif name == "say":
        out = out.with_suffix(".aiff")
        cmd = ["say", *(["-v", voice] if voice else []), "-o", str(out), "-f", str(txt)]
    elif name == "sapi":
        ps = (
            "Add-Type -AssemblyName System.Speech;"
            "$s=New-Object System.Speech.Synthesis.SpeechSynthesizer;"
            + (f"$s.SelectVoice('{voice}');" if voice else "")
            + f"$s.SetOutputToWaveFile('{out}');$s.Speak([IO.File]::ReadAllText('{txt}'));$s.Dispose()"
        )
        cmd = ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps]
    else:
        exe = shutil.which("espeak-ng") or shutil.which("espeak")
        cmd = [exe, "-v", voice or (lang or "en").split("-")[0], "-s", "160", "-w", str(out), "-f", str(txt)]
    p = run_text(cmd, timeout=120)
    if p.returncode or not out.is_file():
        raise RuntimeError(f"speech engine {name} failed: {(p.stderr or p.stdout).strip()[:300]}")
    return out


def mix_args(clips):
    """ffmpeg -filter_complex for [(audio_path, start, max_seconds)] placed on the video timeline."""
    parts = []
    for i, (_, start, length) in enumerate(clips, 1):
        ms = int(start * 1000)
        parts.append(
            f"[{i}:a]atrim=0:{length:.3f},afade=t=out:st={max(0, length - 0.15):.3f}:d=0.15,adelay={ms}|{ms}[a{i}]"
        )
    inputs = "".join(f"[a{i}]" for i in range(1, len(clips) + 1))
    parts.append(f"{inputs}amix=inputs={len(clips)}:normalize=0,apad[voice]")
    return ";".join(parts)
