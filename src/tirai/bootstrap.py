"""`tirai setup`: install ffmpeg, BrowserSkill and the agent skills on Linux, macOS or Windows."""

import os
import shutil
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

from tirai import install
from tirai.system import HOME, IS_MAC, IS_WINDOWS, bsk_bin, ffmpeg_bin, find_font

BSK_INSTALLER = "https://raw.githubusercontent.com/Tencent/BrowserSkill/main/install.{ext}"
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
        s.package("ffmpeg", ["ffmpeg"], lambda: bool(ffmpeg_bin()))
        if not IS_WINDOWS and not IS_MAC:
            s.package("Unicode font (DejaVu)", ["fonts"], lambda: bool(find_font()))
    if "browserskill" not in skip:
        s.browserskill()
    if "skills" not in skip:
        s.skills(agents if agents is not None else detect_agents(), project, "browserskill" not in skip)
    print("- BrowserSkill browser extension")
    print("  install 'BrowserSkill' from the Chrome Web Store / Edge Add-ons and enable it (manual step)")
    if s.problems:
        print("\nsetup incomplete:\n  - " + "\n  - ".join(s.problems))
        return 1
    print("\nsetup done; check with `tirai doctor`")
    return 0
