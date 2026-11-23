"""Regenerate llms-full.txt: llms.txt followed by the docs, skill and demo scenario inlined.

Run after editing any of the sources: `python scripts/build_llms_full.py` (tests fail if it is stale).
"""

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOURCES = [
    "docs/getting-started.md",
    "docs/scenario-format.md",
    "docs/annotations.md",
    "docs/configuration.md",
    "docs/agents.md",
    "docs/architecture.md",
    "docs/troubleshooting.md",
    "skills/tirai-evidence/SKILL.md",
    "skills/tirai-evidence/references/setup.md",
    "examples/demo/login-lock.yaml",
]


def cli_help():
    """Top-level and per-command help, at a fixed width so the output is the same on every machine."""
    sys.path.insert(0, str(ROOT / "src"))
    os.environ["COLUMNS"] = "100"
    from tirai.cli import build_parser

    parser = build_parser()
    parser.prog = "tirai"
    sub = next(a for a in parser._actions if a.choices and isinstance(a.choices, dict))
    blocks = [parser.format_help().strip()]
    for name, cmd in sub.choices.items():
        cmd.prog = f"tirai {name}"
        blocks.append(cmd.format_help().strip())
    return "\n\n".join(blocks)


def build():
    parts = [(ROOT / "llms.txt").read_text(encoding="utf-8").strip()]
    parts.append(f"## Source: `tirai --help`\n\n```text\n{cli_help()}\n```")
    for rel in SOURCES:
        text = (ROOT / rel).read_text(encoding="utf-8").strip()
        if rel.endswith((".yaml", ".yml")):
            text = f"```yaml\n{text}\n```"
        parts.append(f"## Source: {rel}\n\n{text}")
    return "\n\n---\n\n".join(parts) + "\n"


if __name__ == "__main__":
    (ROOT / "llms-full.txt").write_text(build(), encoding="utf-8", newline="\n")
    print("wrote llms-full.txt")
