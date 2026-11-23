"""Environment checks for evidence recording."""

import importlib.util
import shutil
import subprocess

from tirai.bsk import BSK
from tirai.compose import find_font


def _bsk_doctor():
    try:
        p = subprocess.run([BSK, "doctor"], capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired) as e:
        return False, f"bsk not runnable: {e}"
    bad = [ln.strip() for ln in p.stdout.splitlines() if ln.strip().startswith("fail")]
    if bad:
        return False, "; ".join(bad)
    return True, "extension connected" if "extension connected" in p.stdout else "ok"


def checks():
    """Yield (name, ok, detail, required)."""
    yield "ffmpeg", bool(shutil.which("ffmpeg")), shutil.which("ffmpeg") or "install ffmpeg (apt/brew/winget)", True
    bsk = shutil.which(BSK) or (BSK if shutil.os.path.exists(BSK) else None)
    yield "bsk (BrowserSkill CLI)", bool(bsk), bsk or "see docs/setup.md#browserskill", True
    if bsk:
        ok, detail = _bsk_doctor()
        yield "bsk doctor", ok, detail, True
    font = find_font(bold=False)
    yield "subtitle font", bool(font), font or "set TIRAI_FONT to a .ttf with Vietnamese/Unicode glyphs", True
    for mod, extra in (("psycopg", "postgres"), ("pymysql", "mysql")):
        found = importlib.util.find_spec(mod) is not None
        yield f"{mod} (expect: db)", found, "installed" if found else f"optional: pip install 'tirai[{extra}]'", False
    yield (
        "docker (demo stack)",
        bool(shutil.which("docker")),
        shutil.which("docker") or "optional, for examples/demo",
        False,
    )


def run() -> int:
    failed = 0
    for name, ok, detail, required in checks():
        mark = "ok  " if ok else ("FAIL" if required else "warn")
        failed += (not ok) and required
        print(f"{mark}  {name:<26} {detail}")
    print("\nready" if not failed else f"\n{failed} required check(s) failed")
    return 1 if failed else 0
