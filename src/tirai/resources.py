"""Locate files bundled with the package (annotation script, agent skill)."""

from importlib.resources import files
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]


def annotate_js_path() -> Path:
    return Path(str(files("tirai") / "assets" / "annotate.js"))


def annotate_js() -> str:
    return annotate_js_path().read_text(encoding="utf-8")


def skill_dir() -> Path:
    """Skill bundled in the wheel, or `skills/tirai-evidence` of a source checkout."""
    bundled = Path(str(files("tirai") / "skill" / "tirai-evidence"))
    if (bundled / "SKILL.md").is_file():
        return bundled
    return _REPO_ROOT / "skills" / "tirai-evidence"
