"""Environment checks for evidence recording."""

import importlib.util

from tirai.system import (
    MIN_FFMPEG,
    agent_browser_bin,
    bsk_bin,
    ffmpeg_bin,
    ffmpeg_version,
    ffprobe_bin,
    find_bin,
    find_dbx,
    find_font,
    run_text,
)


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
    ver = ffmpeg_version(ff) if ff else None
    need = ".".join(map(str, MIN_FFMPEG))
    if not ff:
        yield "ffmpeg", False, "missing: run `tirai setup` or set FFMPEG_BIN", True
    else:
        ok = bool(ver) and ver >= MIN_FFMPEG
        got = ".".join(map(str, ver)) if ver else "unknown version"
        yield "ffmpeg", ok, f"{ff} ({got})" + ("" if ok else f": need >= {need}, run `tirai setup`"), True
    yield "ffprobe", bool(fp), fp or "missing: installed with ffmpeg, or set FFPROBE_BIN", True
    ab, bsk = agent_browser_bin(), bsk_bin()
    yield "agent-browser (driver)", bool(ab), ab or "missing: run `tirai setup` or set AGENT_BROWSER_BIN", not bsk
    yield "bsk (BrowserSkill CLI)", bool(bsk), bsk or "optional: driver bsk / tirai capture", not ab
    if bsk:
        ok, detail = bsk_doctor(bsk)
        yield "bsk doctor", ok, detail, not ab
    dbx = find_dbx()
    if dbx:
        yield "DBX web", True, f"{dbx[0]}: {dbx[1]}", False
    else:
        hint = "`tirai dbx` will pull the Docker image" if find_bin("docker") else "run `tirai setup`"
        yield "DBX web", False, f"not found ({hint})", False
    font = find_font()
    yield "subtitle font", bool(font), font or "missing: set TIRAI_FONT to a Unicode .ttf", True
    for mod, extra in (("psycopg", "postgres"), ("pymysql", "mysql")):
        found = importlib.util.find_spec(mod) is not None
        yield f"{mod} (expect: db)", found, "installed" if found else f"optional: pip install 'tirai[{extra}]'", False
    from tirai.desktop import desktop_bin
    from tirai.ocr import tesseract_bin
    from tirai.system import IS_WINDOWS

    tess = tesseract_bin()
    yield "tesseract (OCR scan)", bool(tess), tess or "optional: `tirai setup --only ocr`", False
    voice = find_bin("espeak-ng") or find_bin("espeak") or find_bin("say") or ("SAPI" if IS_WINDOWS else None)
    yield "voice (--voice)", bool(voice), voice or "optional: `tirai setup --only voice` or TIRAI_TTS_CMD", False
    desk = desktop_bin()
    yield "agent-desktop (app: tabs)", bool(desk), desk or "optional: `tirai setup --only agent-desktop`", False
    keygen = find_bin("ssh-keygen")
    yield "ssh-keygen (tirai sign)", bool(keygen), keygen or "optional: OpenSSH client", False
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
