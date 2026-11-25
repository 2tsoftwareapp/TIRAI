"""Cross-platform discovery of external tools and fonts (Linux, macOS, Windows)."""

import functools
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
DBX_IMAGE = "t8y2/dbx"
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


def tesseract_bin():
    extra = [Path(os.environ.get("ProgramFiles", "C:/Program Files")) / "Tesseract-OCR"] if IS_WINDOWS else []
    return find_bin("tesseract", "TESSERACT_BIN", extra)


def agent_browser_bin():
    return find_bin("agent-browser", "AGENT_BROWSER_BIN", [TIRAI_BIN, HOME / ".local" / "bin"])


def dbx_web_dir():
    return Path(os.environ.get("DBX_WEB_DIR") or TIRAI_HOME / "dbx")


def dbx_web_bin():
    """DBX_WEB_BIN, the browser-static package `tirai setup` installed, else a dbx-web already on PATH."""
    if os.environ.get("DBX_WEB_BIN"):
        return os.environ["DBX_WEB_BIN"]
    d = dbx_web_dir()
    for p in (d / "dbx-web.exe", d / "bin" / "dbx-web-bin"):
        if p.is_file():
            return str(p)
    return find_bin("dbx-web") or find_bin("dbx-web-bin")


def dbx_package_root(binary):
    """Package directory of a dbx-web binary (holds the web assets)."""
    p = Path(binary).resolve().parent
    return p.parent if p.name == "bin" else p


def dbx_url():
    return os.environ.get("DBX_URL") or f"http://127.0.0.1:{os.environ.get('DBX_PORT') or 4224}/"


def dbx_running(url=None, timeout=2):
    """True when a DBX web server answers at `url` (its auth-check endpoint returns JSON)."""
    import json
    import urllib.request

    check = (url or dbx_url()).rstrip("/") + "/api/auth/check"
    try:
        with urllib.request.urlopen(check, timeout=timeout) as r:  # noqa: S310 - local/user-configured URL
            return "authenticated" in json.loads(r.read().decode("utf-8") or "{}")
    except (OSError, ValueError):
        return False


def dbx_docker():
    """(docker, containers, has_image) for the DBX image; containers is [(name, running)]. None without Docker."""
    docker = find_bin("docker")
    if not docker:
        return None
    try:
        ps = run_text([docker, "ps", "-a", "--format", "{{.Names}}\t{{.Image}}\t{{.State}}"], timeout=15)
        img = run_text([docker, "images", "-q", DBX_IMAGE], timeout=15)
    except (OSError, subprocess.SubprocessError):
        return None
    if ps.returncode != 0:  # daemon down or no permission
        return None
    containers = []
    for line in ps.stdout.splitlines():
        parts = line.split("\t")
        if len(parts) == 3 and parts[1].split(":")[0] == DBX_IMAGE:
            containers.append((parts[0], parts[2] == "running"))
    return docker, containers, bool(img.stdout.strip())


def dbx_auth(url=None, timeout=2):
    """(reachable, authenticated, auth_required) from DBX's /api/auth/check; (False, False, False) when down."""
    import json
    import urllib.request

    check = (url or dbx_url()).rstrip("/") + "/api/auth/check"
    try:
        with urllib.request.urlopen(check, timeout=timeout) as r:  # noqa: S310 - local/user-configured URL
            data = json.loads(r.read().decode("utf-8") or "{}")
    except (OSError, ValueError):
        return False, False, False
    return True, bool(data.get("authenticated")), bool(data.get("required"))


def find_dbx():
    """How DBX web is already available here, or None: ('running', url) | ('binary', path) | ('docker', what)."""
    if dbx_running():
        return "running", dbx_url()
    binary = dbx_web_bin()
    if binary:
        return "binary", binary
    d = dbx_docker()
    if d and d[1]:
        name, running = d[1][0]
        return "docker", f"container {name} ({'running' if running else 'stopped'})"
    if d and d[2]:
        return "docker", f"image {DBX_IMAGE}"
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
    else:
        dirs += ["/usr/local/bin", "/home/linuxbrew/.linuxbrew/bin", HOME / ".linuxbrew" / "bin", "/snap/bin"]
    return dirs


def _ffmpeg_candidates():
    """Every ffmpeg on this machine TIRAI knows about: setup's copy, each PATH entry, package-manager dirs."""
    seen, out = set(), []
    dirs = [TIRAI_BIN, *os.environ.get("PATH", "").split(os.pathsep), *_ffmpeg_dirs()]
    for d in dirs:
        if not d:
            continue
        p = Path(d).expanduser() / _exe("ffmpeg")
        key = str(p.resolve()) if p.is_file() else None
        if key and key not in seen:
            seen.add(key)
            out.append(str(p))
    return out


def _tirai_tool(name):
    p = TIRAI_BIN / _exe(name)
    return str(p) if p.is_file() else None


def ffmpeg_bin():
    """FFMPEG_BIN, else the first ffmpeg >= MIN_FFMPEG (setup's copy, PATH, package dirs), else the first found."""
    if os.environ.get("FFMPEG_BIN"):
        return os.environ["FFMPEG_BIN"]
    found = _ffmpeg_candidates()
    good = next((p for p in found if (ffmpeg_version(p) or (0, 0)) >= MIN_FFMPEG), None)
    return good or (found[0] if found else None)


def ffprobe_bin():
    """FFPROBE_BIN, else the ffprobe next to the chosen ffmpeg, else PATH."""
    if os.environ.get("FFPROBE_BIN"):
        return os.environ["FFPROBE_BIN"]
    ff = ffmpeg_bin()
    if ff:
        p = Path(ff).parent / _exe("ffprobe")
        if p.is_file():
            return str(p)
    return _tirai_tool("ffprobe") or find_bin("ffprobe", None, _ffmpeg_dirs())


def tool_env():
    """Environment for child tools (agent-browser records through `ffmpeg` on PATH): chosen ffmpeg's dir first."""
    env = dict(os.environ)
    ff = ffmpeg_bin()
    if ff and os.path.isabs(ff):
        env["PATH"] = str(Path(ff).parent) + os.pathsep + env.get("PATH", "")
    return env


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
    return _ffmpeg_version(str(path), _mtime(path))


def _mtime(path):
    try:
        return os.stat(path).st_mtime
    except OSError:
        return 0


@functools.lru_cache(maxsize=32)
def _ffmpeg_version(path, _mtime):
    try:
        return parse_ffmpeg_version(run_text([path, "-version"], timeout=30).stdout)
    except (OSError, subprocess.SubprocessError):
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
