"""Install the `tirai-evidence` skill into agent harness skill directories."""

import shutil
from pathlib import Path

from tirai.resources import skill_dir

SKILL = "tirai-evidence"
# agent -> (user-level dir, project-level dir relative to the project root)
TARGETS = {
    "claude": ("~/.claude/skills", ".claude/skills"),
    "codex": ("~/.agents/skills", ".agents/skills"),
    "antigravity": ("~/.gemini/antigravity/skills", ".agent/skills"),
    "cursor": ("~/.cursor/skills", ".cursor/skills"),
    "devin": ("~/.agents/skills", ".agents/skills"),
    "agents": ("~/.agents/skills", ".agents/skills"),  # any harness reading the shared .agents/skills folder
}


def destinations(agents, project=None, dest=None):
    if dest:
        return [Path(dest).expanduser()]
    out = []
    for a in agents:
        user, proj = TARGETS[a]
        p = (Path(project) / proj) if project else Path(user).expanduser()
        if p not in out:
            out.append(p)
    return out


def install(agents, project=None, dest=None, force=False) -> list[Path]:
    src = skill_dir()
    if not (src / "SKILL.md").is_file():
        raise FileNotFoundError(f"bundled skill not found at {src}")
    done = []
    for base in destinations(agents, project, dest):
        target = base / SKILL
        if target.exists():
            if not force:
                print(f"skip  {target} (exists; use --force to overwrite)")
                continue
            shutil.rmtree(target)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(src, target)
        print(f"ok    {target}")
        done.append(target)
    return done
