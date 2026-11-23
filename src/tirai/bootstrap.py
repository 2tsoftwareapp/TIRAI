"""`tirai setup`: install ffmpeg, BrowserSkill and the agent skills on Linux, macOS or Windows."""

import os
import shutil
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

from tirai import install
from tirai.system import (
    HOME,
    IS_MAC,
    IS_WINDOWS,
    MIN_FFMPEG,
    TIRAI_BIN,
    agent_browser_bin,
    bsk_bin,
    dbx_web_bin,
    dbx_web_dir,
    ffmpeg_bin,
    ffmpeg_version,
    find_bin,
    find_font,
    platform_arch,
)

BSK_INSTALLER = "https://raw.githubusercontent.com/Tencent/BrowserSkill/main/install.{ext}"
AGENT_BROWSER_URL = (
    "https://github.com/vercel-labs/agent-browser/releases/latest/download/agent-browser-{os}-{arch}{ext}"
)
# Static ffmpeg builds (GPL, libx264 + libvpx) for platforms whose package manager may ship an old ffmpeg.
FFMPEG_URL = "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-n8.1-latest-{plat}-gpl-8.1.{ext}"
DBX_RELEASES = "https://github.com/t8y2/dbx/releases"
DBX_IMAGE = "t8y2/dbx:latest"


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
    return FFMPEG_URL.format(plat=plat, ext="zip" if osname == "windows" else "tar.xz")


def agent_browser_asset():
    osname, arch = platform_arch()
    if osname == "windows" and arch == "arm64":
        return None
    os_id = {"linux": "linux", "macos": "darwin", "windows": "win32"}[osname]
    return AGENT_BROWSER_URL.format(os=os_id, arch=arch, ext=".exe" if osname == "windows" else "")


def dbx_asset(version):
    """DBX browser-static (dbx-web) package name for this OS/arch and release version, or None."""
    osname, arch = platform_arch()
    if osname == "linux":
        return f"DBX_{version}_{arch}-browser-static.tar.gz"
    if osname == "windows" and arch == "x64":
        return f"dbx-web_{version}_x86_64-browser-static.zip"
    return None


def latest_tag(releases_url):
    """Latest release tag via the /releases/latest redirect (no GitHub API rate limit)."""
    req = urllib.request.Request(f"{releases_url}/latest", method="HEAD", headers={"User-Agent": "tirai-setup"})
    with urllib.request.urlopen(req, timeout=60) as r:  # noqa: S310 - fixed https URL
        return r.geturl().rstrip("/").rsplit("/", 1)[-1]


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
        ids = {"ffmpeg": "Gyan.FFmpeg"}
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
        "fonts": {
            "apt-get": "fonts-dejavu-core",
            "dnf": "dejavu-sans-fonts",
            "pacman": "ttf-dejavu",
            "zypper": "dejavu-fonts",
            "apk": "font-dejavu",
        }
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
        print(f"  {'too old: ' + '.'.join(map(str, ver)) if ver else 'not found'}")
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
            archive = download(url, Path(tmp) / url.rsplit("/", 1)[-1])
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

    def agent_browser(self):
        print("- agent-browser (default browser driver)")
        found = agent_browser_bin()
        if not found:
            url = agent_browser_asset()
            if not url:
                self.problems.append("agent-browser: no prebuilt binary for this platform; use `driver: bsk`")
                return
            if not self.confirm(f"download agent-browser into {TIRAI_BIN}"):
                self.problems.append("agent-browser: not installed")
                return
            print(f"  (from {url})")
            if self.dry_run:
                return
            found = download(url, TIRAI_BIN / ("agent-browser.exe" if IS_WINDOWS else "agent-browser"))
            found.chmod(0o755)
        print(f"  ok ({found})")
        # Chrome for Testing; on Linux --with-deps also installs the browser's system libraries.
        extra = ["--with-deps"] if not (IS_WINDOWS or IS_MAC) and (os.geteuid() == 0 or shutil.which("sudo")) else []
        if not self.execute([str(found), "install", *extra]) and not self.dry_run:
            self.problems.append("agent-browser: `agent-browser install` (Chrome for Testing) failed")

    def dbx(self):
        print("- DBX web (database UI)")
        if dbx_web_bin():
            print(f"  ok ({dbx_web_bin()})")
            return
        try:
            tag = latest_tag(DBX_RELEASES)
            name = dbx_asset(tag.lstrip("v"))
        except OSError as e:
            name = None
            print(f"  could not read DBX releases: {e}")
        if not name:
            docker = find_bin("docker")
            if docker:
                print(f"  no dbx-web build for this platform; using Docker image {DBX_IMAGE}")
                if self.confirm(f"docker pull {DBX_IMAGE}"):
                    self.execute([docker, "pull", DBX_IMAGE])
            else:
                self.problems.append("DBX: no dbx-web build for this platform; install Docker, then `tirai dbx`")
            return
        if not self.confirm(f"download DBX web ({name}) into {dbx_web_dir()}"):
            self.problems.append("DBX: not installed")
            return
        url = f"{DBX_RELEASES}/download/{tag}/{name}"
        print(f"  (from {url})")
        if self.dry_run:
            return
        import tarfile
        import zipfile

        with tempfile.TemporaryDirectory() as tmp:
            archive = download(url, Path(tmp) / name)
            want = download(url + ".sha256", Path(tmp) / "sum").read_text().split()[0].lower()
            if sha256(archive) != want:
                self.problems.append("DBX: SHA-256 mismatch; download discarded")
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

    def browserskill(self):
        print("- BrowserSkill CLI (bsk)")
        if bsk_bin():
            print(f"  ok ({bsk_bin()})")
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
        harness = [a for a in agents if a in ("claude", "codex", "cursor")]
        if bsk_skill and bsk and harness:
            ids = {"claude": "claude-code", "codex": "codex", "cursor": "cursor"}
            args = [x for a in harness for x in ("--harness", ids[a])]
            self.execute([bsk, "install-skill", *args, "--yes", "--force"])


def run(agents=None, project=None, yes=False, dry_run=False, skip=()):
    s = Setup(yes=yes, dry_run=dry_run)
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
        s.browserskill()
    if "skills" not in skip:
        s.skills(agents if agents is not None else detect_agents(), project, "browserskill" not in skip)
    if "browserskill" not in skip:
        print("- BrowserSkill browser extension (only for `driver: bsk` and `tirai capture`)")
        print("  install 'BrowserSkill' from the Chrome Web Store / Edge Add-ons and enable it (manual step)")
    if s.problems:
        print("\nsetup incomplete:\n  - " + "\n  - ".join(s.problems))
        return 1
    print("\nsetup done; check with `tirai doctor`")
    return 0
