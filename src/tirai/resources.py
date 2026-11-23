"""Locate files bundled with the package (annotation script, agent skill)."""

import os
import shutil
import sys
from importlib.resources import files
from pathlib import Path

from tirai import __version__

_REPO_ROOT = Path(__file__).resolve().parents[2]


def tirai_home() -> Path:
    return Path(os.environ.get("TIRAI_HOME") or Path.home() / ".tirai")


def annotate_js_path() -> Path:
    path = Path(str(files("tirai") / "assets" / "annotate.js"))
    if not getattr(sys, "frozen", False):
        return path
    # A one-file binary unpacks into a temp dir that is deleted on exit; hand out a stable copy.
    stable = tirai_home() / "cache" / f"annotate-{__version__}.js"
    if not stable.is_file() or stable.read_bytes() != path.read_bytes():
        stable.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, stable)
    return stable


def annotate_js() -> str:
    return annotate_js_path().read_text(encoding="utf-8")


def skill_dir() -> Path:
    """Skill bundled in the wheel, or `skills/tirai-evidence` of a source checkout."""
    bundled = Path(str(files("tirai") / "skill" / "tirai-evidence"))
    if (bundled / "SKILL.md").is_file():
        return bundled
    return _REPO_ROOT / "skills" / "tirai-evidence"
