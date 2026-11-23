"""Environment checks for evidence recording."""

import importlib.util

from tirai.system import bsk_bin, ffmpeg_bin, ffprobe_bin, find_bin, find_font, run_text


def bsk_doctor(bsk):
    try:
        p = run_text([bsk, "doctor"], timeout=60)
    except (OSError, ValueError) as e:
        return False, f"bsk not runnable: {e}"
    except Exception as e:  # noqa: BLE001 - subprocess.TimeoutExpired and friends
        return False, str(e)
    bad = [ln.strip() for ln in p.stdout.splitlines() if ln.strip().lower().startswith("fail")]
    if bad:
        return False, "; ".join(bad) + " (install/enable the BrowserSkill browser extension)"
    return True, "extension connected" if "extension connected" in p.stdout else "ok"


def checks():
    """Yield (name, ok, detail, required)."""
    ff, fp = ffmpeg_bin(), ffprobe_bin()
    yield "ffmpeg", bool(ff), ff or "missing: run `tirai setup` or set FFMPEG_BIN", True
    yield "ffprobe", bool(fp), fp or "missing: installed with ffmpeg, or set FFPROBE_BIN", True
    bsk = bsk_bin()
    yield "bsk (BrowserSkill CLI)", bool(bsk), bsk or "missing: run `tirai setup` or set BSK_BIN", True
    if bsk:
        ok, detail = bsk_doctor(bsk)
        yield "bsk doctor", ok, detail, True
    font = find_font()
    yield "subtitle font", bool(font), font or "missing: set TIRAI_FONT to a Unicode .ttf", True
    for mod, extra in (("psycopg", "postgres"), ("pymysql", "mysql")):
        found = importlib.util.find_spec(mod) is not None
        yield f"{mod} (expect: db)", found, "installed" if found else f"optional: pip install 'tirai[{extra}]'", False
    docker = find_bin("docker")
    yield "docker (demo stack)", bool(docker), docker or "optional, for examples/demo", False


def run() -> int:
    failed = 0
    for name, ok, detail, required in checks():
        mark = "ok  " if ok else ("FAIL" if required else "warn")
        failed += (not ok) and required
        print(f"{mark}  {name:<26} {detail}")
    print("\nready" if not failed else f"\n{failed} required check(s) failed")
    return 1 if failed else 0
