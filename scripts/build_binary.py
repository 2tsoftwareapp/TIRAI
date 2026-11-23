"""Build a standalone `tirai` executable for this OS/arch with PyInstaller.

    python scripts/build_binary.py            # -> dist/tirai-<os>-<arch>[.exe] + .sha256

Run it once on each target machine (macOS arm64/x64, Linux x64/arm64, Windows x64) and upload the files
to a GitHub Release; `install.sh` / `install.ps1` download the asset that matches the user's machine.
"""

import hashlib
import platform
import shutil
import subprocess
import sys
import tempfile
import venv
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def asset_name():
    system = {"darwin": "macos", "linux": "linux", "windows": "windows"}[platform.system().lower()]
    machine = platform.machine().lower()
    arch = {"x86_64": "x64", "amd64": "x64", "arm64": "arm64", "aarch64": "arm64"}.get(machine, machine)
    return f"tirai-{system}-{arch}" + (".exe" if system == "windows" else "")


def main():
    out = ROOT / "dist"
    out.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        venv.create(tmp / "venv", with_pip=True)
        py = tmp / "venv" / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
        pip = [str(py), "-m", "pip", "install", "--quiet"]
        subprocess.run([*pip, "--upgrade", "pip"], check=True)
        subprocess.run([*pip, f"{ROOT}[postgres,mysql,excel]", "pyinstaller>=6"], check=True)
        subprocess.run(
            [
                str(py), "-m", "PyInstaller", "--onefile", "--name", "tirai", "--noconfirm",
                "--collect-data", "tirai", "--collect-all", "psycopg_binary",
                "--hidden-import", "psycopg", "--hidden-import", "pymysql",
                "--distpath", str(tmp / "out"), "--workpath", str(tmp / "work"), "--specpath", str(tmp),
                str(ROOT / "packaging" / "entry.py"),
            ],
            check=True,
        )  # fmt: skip
        built = next((tmp / "out").iterdir())
        target = out / asset_name()
        shutil.copy2(built, target)
    digest = hashlib.sha256(target.read_bytes()).hexdigest()
    target.with_name(target.name + ".sha256").write_text(f"{digest}  {target.name}\n", encoding="utf-8")
    subprocess.run([str(target), "--version"], check=True)
    print(f"built {target} ({target.stat().st_size // 1024 // 1024} MB)")


if __name__ == "__main__":
    main()
