"""Scenario loading, validation and `${ENV}` interpolation."""

import os
import re
from pathlib import Path

import yaml

ACTIONS = {"navigate", "fill", "click", "press", "wait", "wait_for", "sql", "dbx_login"}
EXPECTS = {"visible", "text_contains", "url_contains", "db"}
ANNOTATIONS = {"box", "circle", "arrow", "text", "badge", "highlight", "blur"}
ENV_RE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


class ScenarioError(ValueError):
    pass


def interpolate(value):
    """Replace `${VAR}` with the environment value; a missing variable is an error, never empty."""
    if not isinstance(value, str):
        return value

    def sub(m):
        if m.group(1) not in os.environ:
            raise ScenarioError(f"missing environment variable {m.group(1)}")
        return os.environ[m.group(1)]

    return ENV_RE.sub(sub, value)


def env_vars(scenario) -> set[str]:
    """Every `${VAR}` referenced anywhere in the scenario."""
    found = set()

    def walk(v):
        if isinstance(v, str):
            found.update(ENV_RE.findall(v))
        elif isinstance(v, dict):
            for x in v.values():
                walk(x)
        elif isinstance(v, list):
            for x in v:
                walk(x)

    walk(scenario)
    return found


def _single_key(item, where, allowed, errors):
    if not isinstance(item, dict) or len(item) != 1:
        errors.append(f"{where}: expected a mapping with exactly one key")
        return None
    (kind,) = item
    if kind not in allowed:
        errors.append(f"{where}: unknown '{kind}' (allowed: {', '.join(sorted(allowed))})")
        return None
    return kind


def validate(sc) -> list[str]:
    """Return a list of human-readable problems; empty means the scenario is runnable."""
    errors = []
    if not isinstance(sc, dict):
        return ["scenario must be a mapping"]
    if not sc.get("name"):
        errors.append("name: required")
    tabs = sc.get("tabs")
    if not isinstance(tabs, dict) or not tabs:
        errors.append("tabs: at least one tab is required")
        tabs = {}
    for name, cfg in tabs.items():
        if not isinstance(cfg, dict) or not cfg.get("url"):
            errors.append(f"tabs.{name}: url is required")
            continue
        for i, a in enumerate(cfg.get("setup", []) or []):
            _single_key(a, f"tabs.{name}.setup[{i}]", ACTIONS, errors)
    steps = sc.get("steps")
    if not isinstance(steps, list) or not steps:
        errors.append("steps: at least one step is required")
        steps = []
    seen = set()
    for i, st in enumerate(steps):
        where = f"steps[{i}]"
        if not isinstance(st, dict):
            errors.append(f"{where}: must be a mapping")
            continue
        sid = st.get("id")
        if not sid:
            errors.append(f"{where}: id is required")
        elif sid in seen:
            errors.append(f"{where}: duplicate id {sid}")
        seen.add(sid)
        where = f"steps[{sid or i}]"
        if not st.get("title"):
            errors.append(f"{where}: title is required")
        if st.get("tab") not in tabs:
            errors.append(f"{where}: tab must be one of {sorted(tabs)}")
        if not st.get("expect"):
            errors.append(f"{where}: expect is required (every step must state what it proves)")
        for j, a in enumerate(st.get("actions", []) or []):
            kind = _single_key(a, f"{where}.actions[{j}]", ACTIONS, errors)
            if kind == "sql" and tabs.get(st.get("tab"), {}).get("kind") != "dbx":
                errors.append(f"{where}.actions[{j}]: sql requires a tab with kind: dbx")
        for j, e in enumerate(st.get("expect", []) or []):
            kind = _single_key(e, f"{where}.expect[{j}]", EXPECTS, errors)
            if kind == "db":
                arg = e["db"] or {}
                db = arg.get("database", "default")
                if db not in (sc.get("databases") or {}):
                    errors.append(f"{where}.expect[{j}]: database '{db}' is not defined under databases")
                if "sql" not in arg or "rows" not in arg:
                    errors.append(f"{where}.expect[{j}]: db needs sql and rows")
        for j, a in enumerate(st.get("annotate", []) or []):
            kind = _single_key(a, f"{where}.annotate[{j}]", ANNOTATIONS, errors)
            if kind and not (isinstance(a[kind], (str, dict)) and (isinstance(a[kind], str) or "target" in a[kind])):
                errors.append(f"{where}.annotate[{j}]: {kind} needs a target")
    return errors


def load(path) -> dict:
    sc = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    problems = validate(sc)
    if problems:
        raise ScenarioError("invalid scenario:\n  - " + "\n  - ".join(problems))
    return sc
