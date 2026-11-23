"""Cross-platform discovery of external tools and fonts (Linux, macOS, Windows)."""

import os
import shutil
import subprocess
import sys
from pathlib import Path

IS_WINDOWS = os.name == "nt"
IS_MAC = sys.platform == "darwin"
HOME = Path.home()
TIRAI_HOME = Path(os.environ.get("TIRAI_HOME") or HOME / ".tirai")
TIRAI_BIN = TIRAI_HOME / "bin"  # tools `tirai setup` downloads (ffmpeg, agent-browser)
MIN_FFMPEG = (6, 0)  # agent-browser recording fails with ffmpeg 4.4; 7.0 verified


def _exe(name):
    return f"{name}.exe" if IS_WINDOWS else name


def find_bin(name, env_var=None, extra=()):
    """Env override, then PATH, then well-known install locations that may not be on PATH yet."""
    if env_var and os.environ.get(env_var):
        return os.environ[env_var]
    found = shutil.which(name)
    if found:
        return found
    for d in extra:
        p = Path(d).expanduser() / _exe(name)
        if p.is_file():
            return str(p)
    return None


def platform_arch():
    """('linux' | 'macos' | 'windows', 'x64' | 'arm64')."""
    import platform

    osname = "windows" if IS_WINDOWS else "macos" if IS_MAC else "linux"
    machine = platform.machine().lower()
    return osname, "arm64" if machine in ("arm64", "aarch64") else "x64"


def agent_browser_bin():
    return find_bin("agent-browser", "AGENT_BROWSER_BIN", [TIRAI_BIN, HOME / ".local" / "bin"])


def dbx_web_dir():
    return Path(os.environ.get("DBX_WEB_DIR") or TIRAI_HOME / "dbx")


def dbx_web_bin():
    """dbx-web server binary from the DBX browser-static package installed by `tirai setup`."""
    if os.environ.get("DBX_WEB_BIN"):
        return os.environ["DBX_WEB_BIN"]
    d = dbx_web_dir()
    for p in (d / "dbx-web.exe", d / "bin" / "dbx-web-bin"):
        if p.is_file():
            return str(p)
    return None


def bsk_bin():
    dirs = [os.environ.get("BSK_INSTALL_DIR", ""), HOME / ".local" / "bin"]
    return find_bin("bsk", "BSK_BIN", [d for d in dirs if d])


def _ffmpeg_dirs():
    dirs = []
    if IS_WINDOWS:
        local = os.environ.get("LOCALAPPDATA")
        if local:
            dirs.append(Path(local) / "Microsoft" / "WinGet" / "Links")  # winget shims, before PATH refresh
        dirs += [Path("C:/ProgramData/chocolatey/bin"), HOME / "scoop" / "shims"]
    elif IS_MAC:
        dirs += ["/opt/homebrew/bin", "/usr/local/bin"]
    return dirs


def _tirai_tool(name):
    p = TIRAI_BIN / _exe(name)
    return str(p) if p.is_file() else None


def ffmpeg_bin():
    """FFMPEG_BIN, then the build `tirai setup` downloaded, then PATH / package-manager locations."""
    if os.environ.get("FFMPEG_BIN"):
        return os.environ["FFMPEG_BIN"]
    return _tirai_tool("ffmpeg") or find_bin("ffmpeg", None, _ffmpeg_dirs())


def ffprobe_bin():
    if os.environ.get("FFPROBE_BIN"):
        return os.environ["FFPROBE_BIN"]
    return _tirai_tool("ffprobe") or find_bin("ffprobe", None, _ffmpeg_dirs())


def parse_ffmpeg_version(text):
    """(major, minor) from `ffmpeg -version`; git/master builds (N-xxxxx) count as new."""
    import re

    m = re.search(r"ffmpeg version n?(\d+)\.(\d+)", text)
    if m:
        return int(m.group(1)), int(m.group(2))
    return (99, 0) if re.search(r"ffmpeg version (N-|git-)", text) else None


def ffmpeg_version(path=None):
    path = path or ffmpeg_bin()
    if not path:
        return None
    try:
        return parse_ffmpeg_version(run_text([path, "-version"], timeout=30).stdout)
    except OSError:
        return None


def run_text(cmd, **kw):
    """subprocess.run with UTF-8 decoding everywhere (Windows consoles default to a legacy code page)."""
    return subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", **kw)


def _font_candidates(bold):
    if IS_WINDOWS:
        fonts = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"
        names = ["arialbd.ttf", "segoeuib.ttf"] if bold else ["arial.ttf", "segoeui.ttf"]
        return [fonts / n for n in names]
    if IS_MAC:
        sup = Path("/System/Library/Fonts/Supplemental")
        if bold:
            return [sup / "Arial Bold.ttf", Path("/Library/Fonts/Arial Bold.ttf")]
        return [sup / "Arial Unicode.ttf", Path("/Library/Fonts/Arial Unicode.ttf"), sup / "Arial.ttf"]
    name = "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"
    roots = [
        "/usr/share/fonts/truetype/dejavu",
        "/usr/share/fonts/dejavu-sans-fonts",
        "/usr/share/fonts/TTF",
        "/usr/share/fonts/dejavu",
        "/usr/local/share/fonts",
    ]
    return [Path(r) / name for r in roots]


def _fc_match(bold):
    if not shutil.which("fc-match"):
        return None
    p = run_text(["fc-match", "-f", "%{file}", "DejaVu Sans:bold" if bold else "DejaVu Sans"])
    return p.stdout.strip() if p.returncode == 0 and p.stdout.strip().lower().endswith((".ttf", ".otf")) else None


def find_font(bold=False):
    """TIRAI_FONT / TIRAI_FONT_BOLD, else a platform font with Vietnamese/Unicode glyphs."""
    env = os.environ.get("TIRAI_FONT_BOLD" if bold else "TIRAI_FONT")
    for p in ([Path(env)] if env else []) + _font_candidates(bold):
        if p.is_file():
            return str(p)
    found = _fc_match(bold)
    if found:
        return found
    return find_font(False) if bold else None


def subtitle_font_name():
    """Family name libass looks up for burned subtitles."""
    if os.environ.get("TIRAI_SUBTITLE_FONT"):
        return os.environ["TIRAI_SUBTITLE_FONT"]
    font = find_font() or ""
    return "DejaVu Sans" if "DejaVu" in font else "Arial Unicode MS" if "Unicode" in font else "Arial"


def primary_modifier():
    """Modifier for editor shortcuts like Run (Cmd on macOS, Ctrl elsewhere)."""
    return "Meta" if IS_MAC else "Ctrl"
