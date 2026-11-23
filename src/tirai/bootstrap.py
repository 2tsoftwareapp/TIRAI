"""`tirai setup`: install ffmpeg, BrowserSkill and the agent skills on Linux, macOS or Windows."""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

from tirai import install, tts
from tirai.system import (
    DBX_IMAGE,
    HOME,
    IS_MAC,
    IS_WINDOWS,
    MIN_FFMPEG,
    TIRAI_BIN,
    agent_browser_bin,
    bsk_bin,
    dbx_docker,
    dbx_web_bin,
    dbx_web_dir,
    ffmpeg_bin,
    ffmpeg_version,
    find_dbx,
    find_font,
    platform_arch,
    run_text,
    tesseract_bin,
)

BSK_INSTALLER = "https://raw.githubusercontent.com/Tencent/BrowserSkill/main/install.{ext}"
# Downloads are pinned to versions verified with TIRAI and checked against SHA-256 digests.
# Override a version with TIRAI_AGENT_BROWSER_VERSION / TIRAI_DBX_VERSION (digest then comes from the release).
AGENT_BROWSER_REPO = "vercel-labs/agent-browser"
AGENT_BROWSER_VERSION = "0.43.0"
AGENT_DESKTOP_REPO = "vercel-labs/agent-desktop"
AGENT_DESKTOP_VERSION = "1.3.1"
AGENT_DESKTOP_SHA256 = {
    "aarch64-apple-darwin": "9b7b7cfc74892eab46c2c85d6cb7dc4863bf8dab0a222cfcfb8ae4604c69c86c",
    "aarch64-pc-windows-msvc": "805f1f61890f9983fceaf38cda94a37a049c379435d65607db5cedd22c8ef97b",
    "aarch64-unknown-linux-gnu": "438990a703fbeb19775596c341c3701435e80adbfa1b2f64b82ff17567d5573b",
    "x86_64-apple-darwin": "469da10cfb68928c58caff88b92b30526e0ca895ac06bc86b7f533b1d9b309b3",
    "x86_64-pc-windows-msvc": "6ee4b1e078f4e78792e79f16e32e4a78b9919464aa3c55629b7e27ed53a08c13",
    "x86_64-unknown-linux-gnu": "ca77b6b75034eeb12e537dd8c0a4f2a3424119253f38b7e6bd79ba0d2fef1264",
}
AGENT_BROWSER_SHA256 = {
    "agent-browser-darwin-arm64": "05338a8eeddf0b3f9ebf0c87a6c21aedc10685608c68618e1a8483c43eae9c3f",
    "agent-browser-darwin-x64": "49a5ab27297213c1bc0005701a6a4542399abfc9d2cb7520ab519ebb94b8b13d",
    "agent-browser-linux-arm64": "34be55c2b92d8d199fb9d1d62a905ee5b6ac5b1f3e8c24e5b20597f370d905e5",
    "agent-browser-linux-x64": "8e69c9fb662514c9cf36e4911e94e913742ba066e55102486350e049dd847612",
    "agent-browser-win32-x64.exe": "ebcef5ebea93c7ccf0fe3f8c18eee908ae9174dfef8e52a3dda6f24a59f630dc",
}
DBX_REPO = "t8y2/dbx"
DBX_VERSION = "0.6.72"
DBX_SHA256 = {
    "DBX_0.6.72_x64-browser-static.tar.gz": "6d55cafe0cc306513733465ea1b387bf0d8ee7796bfe5c678ced3593210460d9",
    "DBX_0.6.72_arm64-browser-static.tar.gz": "afe4546c64de1a908106e3995ebfdcfe8e73dd4b3c1d33052bfdb9d900fb5850",
    "dbx-web_0.6.72_x86_64-browser-static.zip": "fb931d1fcbf34d7322601c67adb2a27b2a7ae3385b6b2bd96519dc639b611c4e",
}
# Static ffmpeg 8.1 (GPL: libx264, libvpx, freetype, libass) for platforms whose package manager may ship an old one.
# BtbN rebuilds "latest" daily, so the archive is checked against that release's checksums.sha256.
FFMPEG_RELEASE = "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest"
FFMPEG_ASSET = "ffmpeg-n8.1-latest-{plat}-gpl-8.1.{ext}"


class VerifyError(Exception):
    pass


def release_url(repo, tag, name):
    return f"https://github.com/{repo}/releases/download/{tag}/{name}"


def release_digest(repo, tag, name):
    """SHA-256 GitHub records for a release asset (API), or None."""
    url = f"https://api.github.com/repos/{repo}/releases/tags/{tag}"
    headers = {"User-Agent": "tirai-setup", "Accept": "application/vnd.github+json"}
    if os.environ.get("GITHUB_TOKEN"):
        headers["Authorization"] = f"Bearer {os.environ['GITHUB_TOKEN']}"
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=60) as r:  # noqa: S310
            assets = json.load(r).get("assets", [])
    except OSError:
        return None
    digest = next((a.get("digest") or "" for a in assets if a.get("name") == name), "")
    return digest.split(":", 1)[1] if digest.startswith("sha256:") else None


def fetch_verified(url, dest, expected):
    """Download `url` to `dest` and check its SHA-256; TIRAI_ALLOW_UNVERIFIED=1 skips a missing digest."""
    if not expected and os.environ.get("TIRAI_ALLOW_UNVERIFIED") != "1":
        raise VerifyError(f"no SHA-256 known for {url} (set TIRAI_ALLOW_UNVERIFIED=1 to accept)")
    download(url, dest)
    if expected and sha256(dest) != expected.lower():
        dest.unlink()
        raise VerifyError(f"SHA-256 mismatch for {url}; download discarded")
    return dest


def download(url, dest):
    dest.parent.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(url, headers={"User-Agent": "tirai-setup"})
    with urllib.request.urlopen(req, timeout=600) as r, open(dest, "wb") as f:  # noqa: S310 - fixed https URLs
        shutil.copyfileobj(r, f)
    return dest


def sha256(path):
    import hashlib

    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def ffmpeg_asset():
    """Static ffmpeg archive URL for this OS/arch, or None (macOS: use Homebrew)."""
    osname, arch = platform_arch()
    if osname == "macos":
        return None
    plat = {"linux": "linux", "windows": "win"}[osname] + ("arm64" if arch == "arm64" else "64")
    return f"{FFMPEG_RELEASE}/" + FFMPEG_ASSET.format(plat=plat, ext="zip" if osname == "windows" else "tar.xz")


def agent_browser_asset():
    """(url, expected sha256 or None) for this OS/arch, or None when there is no prebuilt binary."""
    osname, arch = platform_arch()
    if osname == "windows" and arch == "arm64":
        return None
    os_id = {"linux": "linux", "macos": "darwin", "windows": "win32"}[osname]
    name = f"agent-browser-{os_id}-{arch}" + (".exe" if osname == "windows" else "")
    version = os.environ.get("TIRAI_AGENT_BROWSER_VERSION") or AGENT_BROWSER_VERSION
    tag = f"v{version}"
    sha = AGENT_BROWSER_SHA256.get(name) if version == AGENT_BROWSER_VERSION else None
    return release_url(AGENT_BROWSER_REPO, tag, name), sha or (lambda: release_digest(AGENT_BROWSER_REPO, tag, name))


def agent_desktop_asset():
    """(url, sha256 or digest lookup) of the agent-desktop CLI archive for this OS/arch."""
    osname, arch = platform_arch()
    cpu = "aarch64" if arch == "arm64" else "x86_64"
    triple = f"{cpu}-" + {"linux": "unknown-linux-gnu", "macos": "apple-darwin", "windows": "pc-windows-msvc"}[osname]
    version = os.environ.get("TIRAI_AGENT_DESKTOP_VERSION") or AGENT_DESKTOP_VERSION
    tag, name = f"v{version}", f"agent-desktop-v{version}-{triple}.tar.gz"
    sha = AGENT_DESKTOP_SHA256.get(triple) if version == AGENT_DESKTOP_VERSION else None
    return release_url(AGENT_DESKTOP_REPO, tag, name), sha or (lambda: release_digest(AGENT_DESKTOP_REPO, tag, name))


def dbx_asset(version):
    """DBX browser-static (dbx-web) package name for this OS/arch and release version, or None."""
    osname, arch = platform_arch()
    if osname == "linux":
        return f"DBX_{version}_{arch}-browser-static.tar.gz"
    if osname == "windows" and arch == "x64":
        return f"dbx-web_{version}_x86_64-browser-static.zip"
    return None


# Agents detected by their config directory (Devin skills are per repository: use --project).
AGENT_HOMES = {
    "claude": HOME / ".claude",
    "codex": HOME / ".codex",
    "antigravity": HOME / ".gemini" / "antigravity",
    "cursor": HOME / ".cursor",
}


def detect_agents():
    return [a for a, d in AGENT_HOMES.items() if d.is_dir()]


def _sudo():
    if IS_WINDOWS or os.geteuid() == 0:
        return []
    return ["sudo"] if shutil.which("sudo") else []


def package_install_cmd(packages):
    """Command that installs `packages` with the platform package manager, or None."""
    if IS_WINDOWS:
        ids = {"ffmpeg": "Gyan.FFmpeg", "tesseract": "UB-Mannheim.TesseractOCR"}
        if shutil.which("winget"):
            return [
                "winget",
                "install",
                "--id",
                ids[packages[0]],
                "-e",
                "--silent",
                "--accept-source-agreements",
                "--accept-package-agreements",
            ]
        if shutil.which("choco"):
            return ["choco", "install", "-y", *packages]
        if shutil.which("scoop"):
            return ["scoop", "install", *packages]
        return None
    if IS_MAC:
        return ["brew", "install", *packages] if shutil.which("brew") else None
    linux = {
        "apt-get": ["apt-get", "install", "-y"],
        "dnf": ["dnf", "install", "-y"],
        "pacman": ["pacman", "-S", "--noconfirm"],
        "zypper": ["zypper", "--non-interactive", "install"],
        "apk": ["apk", "add"],
    }
    names = {
        "tesseract": {
            "apt-get": "tesseract-ocr",
            "dnf": "tesseract",
            "pacman": "tesseract",
            "zypper": "tesseract-ocr",
            "apk": "tesseract-ocr",
        },
        "fonts": {
            "apt-get": "fonts-dejavu-core",
            "dnf": "dejavu-sans-fonts",
            "pacman": "ttf-dejavu",
            "zypper": "dejavu-fonts",
            "apk": "font-dejavu",
        },
    }
    for pm, cmd in linux.items():
        if shutil.which(pm):
            pkgs = [names.get(p, {}).get(pm, p) for p in packages]
            return [*_sudo(), *cmd, *pkgs]
    return None


class Setup:
    def __init__(self, yes=False, dry_run=False):
        self.yes, self.dry_run, self.problems = yes, dry_run, []

    def confirm(self, what):
        if self.yes or self.dry_run:
            return True
        if not sys.stdin.isatty():
            print(f"  skipped (non-interactive; pass --yes to {what})")
            return False
        return input(f"  {what}? [Y/n] ").strip().lower() in ("", "y", "yes")

    def execute(self, cmd):
        print("  $ " + " ".join(str(c) for c in cmd))
        if self.dry_run:
            return True
        if "apt-get" in cmd[:2]:
            subprocess.run([*cmd[: cmd.index("apt-get")], "apt-get", "update"], check=False)
        return subprocess.run(cmd, check=False).returncode == 0

    def package(self, label, packages, present):
        print(f"- {label}")
        if present():
            print("  ok")
            return
        cmd = package_install_cmd(packages)
        if not cmd:
            self.problems.append(f"{label}: no supported package manager; install it manually")
            return
        if self.confirm(f"install {label}") and self.execute(cmd) and not self.dry_run and not present():
            self.problems.append(f"{label}: installed but not found; open a new terminal or set the *_BIN env var")

    def ffmpeg(self):
        print(f"- ffmpeg (>= {MIN_FFMPEG[0]}.{MIN_FFMPEG[1]}, with libx264)")
        ver = ffmpeg_version()
        if ver and ver >= MIN_FFMPEG:
            print(f"  ok ({ffmpeg_bin()}, {ver[0]}.{ver[1]})")
            return
        if ver:
            print(f"  {ffmpeg_bin()} is {ver[0]}.{ver[1]}: too old (agent-browser recording breaks below 6.0)")
            print(f"  a private copy goes to {TIRAI_BIN}; the system ffmpeg is left as it is")
        else:
            print("  not found")
        url = ffmpeg_asset()
        if not url:  # macOS: Homebrew ships current ffmpeg
            cmd = package_install_cmd(["ffmpeg"])
            if not cmd:
                self.problems.append("ffmpeg: install Homebrew (https://brew.sh) then `brew install ffmpeg`")
            elif self.confirm("install ffmpeg") and self.execute(cmd) and not self.dry_run:
                if (ffmpeg_version() or (0, 0)) < MIN_FFMPEG:
                    self.problems.append("ffmpeg: still missing/too old; open a new terminal or set FFMPEG_BIN")
            return
        if not self.confirm(f"download a static ffmpeg build into {TIRAI_BIN}"):
            self.problems.append("ffmpeg: not installed")
            return
        print(f"  (from {url})")
        if self.dry_run:
            return
        import tarfile
        import zipfile

        with tempfile.TemporaryDirectory() as tmp:
            sums = download(f"{FFMPEG_RELEASE}/checksums.sha256", Path(tmp) / "checksums.sha256").read_text()
            name = url.rsplit("/", 1)[-1]
            want = next((ln.split()[0] for ln in sums.splitlines() if ln.strip().endswith(name)), None)
            try:
                archive = fetch_verified(url, Path(tmp) / name, want)
            except VerifyError as e:
                self.problems.append(f"ffmpeg: {e}")
                return
            names = {"ffmpeg", "ffprobe", "ffmpeg.exe", "ffprobe.exe"}
            TIRAI_BIN.mkdir(parents=True, exist_ok=True)
            if archive.suffix == ".zip":
                with zipfile.ZipFile(archive) as z:
                    for m in z.namelist():
                        if Path(m).name in names and "/bin/" in m:
                            (TIRAI_BIN / Path(m).name).write_bytes(z.read(m))
            else:
                with tarfile.open(archive) as t:
                    for m in t.getmembers():
                        if Path(m.name).name in names and "/bin/" in m.name and m.isfile():
                            (TIRAI_BIN / Path(m.name).name).write_bytes(t.extractfile(m).read())
            for n in ("ffmpeg", "ffprobe"):
                p = TIRAI_BIN / (n + (".exe" if IS_WINDOWS else ""))
                if p.exists():
                    p.chmod(0o755)
        ver = ffmpeg_version()
        if not ver or ver < MIN_FFMPEG:
            self.problems.append("ffmpeg: download did not produce a working ffmpeg")
        else:
            print(f"  installed {ffmpeg_bin()} ({ver[0]}.{ver[1]})")

    def agent_desktop(self):
        """Desktop-app driver (tabs with `app:`); opt-in with `tirai setup --only agent-desktop`."""
        import tarfile

        from tirai.desktop import desktop_bin

        print("- agent-desktop (desktop apps through the accessibility tree)")
        found = desktop_bin()
        if not found:
            url, sha = agent_desktop_asset()
            if not self.confirm(f"download agent-desktop into {TIRAI_BIN}"):
                self.problems.append("agent-desktop: not installed")
                return
            print(f"  (from {url})")
            if self.dry_run:
                return
            with tempfile.TemporaryDirectory() as tmp:
                try:
                    archive = fetch_verified(url, Path(tmp) / "agent-desktop.tar.gz", sha() if callable(sha) else sha)
                except VerifyError as e:
                    self.problems.append(f"agent-desktop: {e}")
                    return
                TIRAI_BIN.mkdir(parents=True, exist_ok=True)
                with tarfile.open(archive) as t:
                    for m in t.getmembers():
                        if m.isfile() and Path(m.name).name.startswith("agent-desktop"):
                            dest = TIRAI_BIN / Path(m.name).name
                            dest.write_bytes(t.extractfile(m).read())
                            dest.chmod(0o755)
            found = desktop_bin()
            if not found:
                self.problems.append("agent-desktop: archive did not contain the binary")
                return
        print(f"  ok ({found})")
        st = run_text([found, "status"], timeout=30)
        try:
            perm = json.loads(st.stdout.strip().splitlines()[-1])["data"]["permissions"]["accessibility"]
        except (ValueError, KeyError, IndexError):
            perm = {}
        if perm.get("state") != "granted":
            print(
                f"  accessibility: {perm.get('state', 'unknown')} - "
                f"{perm.get('suggestion', 'run `agent-desktop status`')}"
            )
            if IS_MAC:
                print("  grant Accessibility and Screen Recording to your terminal in System Settings > Privacy")

    def agent_browser(self):
        print("- agent-browser (default browser driver)")
        found = agent_browser_bin()
        if not found:
            asset = agent_browser_asset()
            if not asset:
                self.problems.append("agent-browser: no prebuilt binary for this platform; use `driver: bsk`")
                return
            if not self.confirm(f"download agent-browser into {TIRAI_BIN}"):
                self.problems.append("agent-browser: not installed")
                return
            url, sha = asset
            print(f"  (from {url})")
            if self.dry_run:
                return
            with tempfile.TemporaryDirectory() as tmp:
                try:
                    got = fetch_verified(url, Path(tmp) / "agent-browser", sha() if callable(sha) else sha)
                except VerifyError as e:
                    self.problems.append(f"agent-browser: {e}")
                    return
                found = TIRAI_BIN / ("agent-browser.exe" if IS_WINDOWS else "agent-browser")
                TIRAI_BIN.mkdir(parents=True, exist_ok=True)
                shutil.move(str(got), found)
            found.chmod(0o755)
        print(f"  ok ({found})")
        self.agent_browser_chrome(str(found))

    def agent_browser_chrome(self, exe):
        """Download Chrome for Testing / Linux libraries only when agent-browser's own doctor says they're missing."""
        state = agent_browser_state(exe)
        if state == "ok":
            print("  browser ok (agent-browser doctor: Chrome found, headless launch works)")
            return
        if state in ("no-chrome", None):
            if state is None:
                print("  could not run `agent-browser doctor`; installing the browser to be safe")
            if not self.confirm("download Chrome for Testing (agent-browser install)"):
                self.problems.append("agent-browser: no browser; run `agent-browser install`")
                return
            if not self.execute([exe, "install"]) and not self.dry_run:
                self.problems.append("agent-browser: `agent-browser install` (Chrome for Testing) failed")
                return
            if self.dry_run:
                return
            state = agent_browser_state(exe)
        if state == "launch-failed" and not (IS_WINDOWS or IS_MAC):
            print("  Chrome is installed but does not start: system libraries are missing")
            if self.confirm("install Chrome's system libraries with the package manager (sudo)"):
                if self.execute([exe, "install", "--with-deps"]) and agent_browser_state(exe) == "ok":
                    return
            self.problems.append("agent-browser: Chrome does not start; run `agent-browser install --with-deps`")
        elif state != "ok":
            self.problems.append("agent-browser: browser check failed; run `agent-browser doctor`")

    def dbx(self):
        print("- DBX web (database UI)")
        found = find_dbx()
        if found:
            kind, what = found
            hint = {"running": "already running", "binary": "installed", "docker": "Docker"}[kind]
            print(f"  ok ({hint}: {what})")
            return
        version = os.environ.get("TIRAI_DBX_VERSION") or DBX_VERSION
        name = dbx_asset(version)
        if not name:
            d = dbx_docker()
            if d:
                print(f"  no dbx-web build for this platform; using Docker image {DBX_IMAGE}")
                if self.confirm(f"docker pull {DBX_IMAGE}"):
                    self.execute([d[0], "pull", DBX_IMAGE])
            else:
                # Optional: only scenarios with a database tab need DBX.
                print("  skipped: no dbx-web build for this platform; install Docker, then `tirai dbx`")
            return
        if not self.confirm(f"download DBX web ({name}) into {dbx_web_dir()}"):
            self.problems.append("DBX: not installed")
            return
        url = release_url(DBX_REPO, f"v{version}", name)
        print(f"  (from {url})")
        if self.dry_run:
            return
        import tarfile
        import zipfile

        with tempfile.TemporaryDirectory() as tmp:
            want = DBX_SHA256.get(name)
            if not want:
                try:
                    want = download(url + ".sha256", Path(tmp) / "sum").read_text().split()[0].lower()
                except OSError:
                    want = None
            try:
                archive = fetch_verified(url, Path(tmp) / name, want)
            except (VerifyError, OSError) as e:
                self.problems.append(f"DBX: {e}")
                return
            dest = dbx_web_dir()
            shutil.rmtree(dest, ignore_errors=True)
            extract = Path(tmp) / "x"
            if name.endswith(".zip"):
                with zipfile.ZipFile(archive) as z:
                    z.extractall(extract)
            else:
                with tarfile.open(archive) as t:
                    t.extractall(extract, filter="data") if hasattr(tarfile, "data_filter") else t.extractall(extract)
            entries = list(extract.iterdir())
            shutil.move(str(entries[0] if len(entries) == 1 and entries[0].is_dir() else extract), dest)
        if dbx_web_bin():
            Path(dbx_web_bin()).chmod(0o755)
            print(f"  installed {dbx_web_bin()}; start it with `tirai dbx`")
        else:
            self.problems.append("DBX: package extracted but dbx-web binary not found")

    def browserskill(self, optional=False):
        print("- BrowserSkill CLI (bsk)")
        if bsk_bin():
            print(f"  ok ({bsk_bin()})")
            return
        if optional:
            print("  not installed (optional, only for `driver: bsk`); later: `tirai setup --only browserskill`")
            return
        if not self.confirm("install BrowserSkill CLI from github.com/Tencent/BrowserSkill"):
            self.problems.append("bsk: not installed")
            return
        ext = "ps1" if IS_WINDOWS else "sh"
        url = BSK_INSTALLER.format(ext=ext)
        with tempfile.TemporaryDirectory() as tmp:
            script = Path(tmp) / f"install.{ext}"
            if not self.dry_run:
                urllib.request.urlretrieve(url, script)  # noqa: S310 - fixed https URL
            shell = ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File"] if IS_WINDOWS else ["sh"]
            print(f"  (from {url})")
            if not self.execute([*shell, str(script)]) or (not self.dry_run and not bsk_bin()):
                self.problems.append("bsk: installer failed")

    def skills(self, agents, project, bsk_skill):
        print("- agent skills")
        if not agents:
            print("  no agent detected; run `tirai install-skill --agent <name>` later")
            return
        if not self.dry_run:
            install.install(agents, project=project, force=True)
        else:
            print(f"  would install tirai-evidence for: {', '.join(agents)}")
        bsk = bsk_bin()
        ids = {"claude": "claude-code", "codex": "codex", "cursor": "cursor"}
        harness = [ids[a] for a in agents if a in ids]
        if bsk_skill and bsk and harness:
            have = bsk_skill_installed(bsk)
            todo = [h for h in harness if h not in have]
            if not todo:
                print(f"  browser-skill already installed for: {', '.join(harness)}")
                return
            self.execute([bsk, "install-skill", *[x for h in todo for x in ("--harness", h)], "--yes"])

    def browserskill_extension(self):
        print("- BrowserSkill browser extension (only for `driver: bsk`)")
        bsk = bsk_bin()
        if bsk:
            from tirai.doctor import bsk_doctor

            ok, detail = bsk_doctor(bsk)
            if ok:
                print(f"  ok ({detail})")
                return
        print("  install 'BrowserSkill' from the Chrome Web Store / Edge Add-ons and enable it (manual step)")


STEPS = ("ffmpeg", "agent-browser", "dbx", "browserskill", "skills", "ocr", "voice", "agent-desktop")
OPT_IN = {"ocr", "voice", "agent-desktop"}  # only with --only: tesseract (OCR PII scan) and a speech engine (--voice)


def agent_browser_state(exe):
    """'ok' | 'no-chrome' | 'launch-failed' from `agent-browser doctor --offline --json`; None if it can't run."""
    import json

    try:
        p = run_text([exe, "doctor", "--offline", "--json"], timeout=180)
        checks = {c.get("id", ""): c.get("status") for c in json.loads(p.stdout.strip().splitlines()[-1])["checks"]}
    except (OSError, subprocess.SubprocessError, ValueError, KeyError, IndexError, TypeError):
        return None
    if checks.get("chrome.installed") not in ("pass", "warn"):
        return "no-chrome"
    if any(k.startswith("launch") and v == "fail" for k, v in checks.items()):
        return "launch-failed"
    return "ok"


def bsk_skill_installed(bsk):
    """Harness ids that already have the browser-skill skill (`bsk install-skill --list --json`)."""
    import json

    try:
        p = run_text([bsk, "install-skill", "--list", "--json"], timeout=60)
        return {h["id"] for h in json.loads(p.stdout)["harnesses"] if h.get("installed")}
    except (OSError, subprocess.SubprocessError, ValueError, KeyError, TypeError):
        return set()


def run(agents=None, project=None, yes=False, dry_run=False, skip=(), only=()):
    s = Setup(yes=yes, dry_run=dry_run)
    if only:
        skip = set(skip) | (set(STEPS) - set(only))
    else:
        skip = set(skip) | OPT_IN
    print(f"TIRAI setup ({sys.platform})")
    if "ffmpeg" not in skip:
        s.ffmpeg()
        if not IS_WINDOWS and not IS_MAC:
            s.package("Unicode font (DejaVu)", ["fonts"], lambda: bool(find_font()))
    if "agent-browser" not in skip:
        s.agent_browser()
    if "dbx" not in skip:
        s.dbx()
    if "browserskill" not in skip:
        s.browserskill(optional=bool(agent_browser_bin()) and "browserskill" not in only)
    if "skills" not in skip:
        s.skills(agents if agents is not None else detect_agents(), project, "browserskill" not in skip)
    if "browserskill" not in skip and bsk_bin():
        s.browserskill_extension()
    if "agent-desktop" not in skip:
        s.agent_desktop()
    if "ocr" not in skip:
        s.package("tesseract (OCR scan for PII)", ["tesseract"], lambda: bool(tesseract_bin()))
    if "voice" not in skip:
        if IS_MAC or IS_WINDOWS:
            print("- speech engine\n  ok (built into the OS)")
        else:
            s.package("espeak-ng (voice-over)", ["espeak-ng"], lambda: bool(tts.available("espeak")))
    if s.problems:
        print("\nsetup incomplete:\n  - " + "\n  - ".join(s.problems))
        return 1
    print("\nsetup done; check with `tirai doctor`")
    return 0
