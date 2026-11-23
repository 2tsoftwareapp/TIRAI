"""Scenario loading, validation and `${ENV}` interpolation."""

import copy
import itertools
import os
import re
from pathlib import Path

import yaml

ACTIONS = {
    "navigate", "fill", "click", "press", "wait", "wait_for", "sql", "dbx_login",
    "select", "hover", "scroll", "upload", "dialog", "save",
}  # fmt: skip
EXPECTS = {
    "visible", "not_visible", "text_contains", "text_matches", "url_contains",
    "value", "attribute", "count", "request", "no_console_errors", "db",
}  # fmt: skip
# Required keys for mapping-style arguments; validated up front so a dry-run never fails on a typo.
REQUIRED = {
    "fill": ("selector", "value"),
    "select": ("selector", "value"),
    "upload": ("selector", "file"),
    "text_contains": ("text",),
    "text_matches": ("pattern",),
    "value": ("selector", "equals"),
    "attribute": ("selector", "name", "equals"),
    "count": ("selector", "equals"),
    "request": ("url_contains",),
    "save": ("name", "selector"),
}
ANNOTATIONS = {"box", "circle", "arrow", "text", "badge", "highlight", "blur"}
SETTINGS = {"hold", "timing_scale", "expect_timeout", "camera", "camera_factor", "fast_forward"}
PII_RULES = {"email", "phone", "card", "token"}
PRIVACY_KEYS = {"mask", "patterns", "selectors", "keep", "inputs", "ocr"}
OCR_MODES = {"off", "warn", "fix", "fail"}
DBX_KEYS = {"new_query", "editor", "password", "run_key", "connect", "error"}
DBX_CONNECT_KEYS = {"name", "database", "host", "password_env"}
ENV_RE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")
VAR_RE = re.compile(r"\{\{\s*([A-Za-z_][A-Za-z0-9_]*)\s*\}\}")


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


def render(value, variables, strict=False):
    """Replace `{{name}}` from `variables` (case params, `vars:`, values saved by earlier steps).

    A string that is exactly one placeholder keeps the variable's type (so `equals: "{{n}}"` stays a number).
    Unknown names are left in place unless `strict`, so runtime variables survive load-time rendering.
    """
    if isinstance(value, dict):
        return {k: render(v, variables, strict) for k, v in value.items()}
    if isinstance(value, list):
        return [render(v, variables, strict) for v in value]
    if not isinstance(value, str):
        return value
    whole = VAR_RE.fullmatch(value.strip())
    if whole and whole.group(1) in variables:
        return variables[whole.group(1)]

    def sub(m):
        if m.group(1) in variables:
            return str(variables[m.group(1)])
        if strict:
            raise ScenarioError(f"undefined variable {{{{{m.group(1)}}}}} (set it in vars/cases or with save)")
        return m.group(0)

    return VAR_RE.sub(sub, value)


def _include(item, base, stack):
    path = (base / item["include"]).resolve()
    if path in stack:
        raise ScenarioError(f"include cycle: {' -> '.join(p.name for p in [*stack, path])}")
    if not path.is_file():
        raise ScenarioError(f"include not found: {item['include']} (relative to {base})")
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    steps = data.get("steps") if isinstance(data, dict) else data
    if not isinstance(steps, list):
        raise ScenarioError(f"{item['include']}: expected a list of steps or a mapping with steps")
    steps = render(_resolve(steps, path.parent, [*stack, path]), item.get("with") or {})
    prefix = item.get("prefix", "")
    return [
        {**st, "id": f"{prefix}{st['id']}"} if prefix and isinstance(st, dict) and "id" in st else st for st in steps
    ]


def _resolve(steps, base, stack):
    out = []
    for st in steps:
        if isinstance(st, dict) and "include" in st:
            out.extend(_include(st, base, stack))
        else:
            out.append(st)
    return out


def _cases(sc):
    if sc.get("cases") is not None and sc.get("matrix") is not None:
        raise ScenarioError("use either cases or matrix, not both")
    if sc.get("matrix") is not None:
        m = sc["matrix"]
        if not isinstance(m, dict) or not m or not all(isinstance(v, list) and v for v in m.values()):
            raise ScenarioError("matrix: must map names to non-empty lists")
        return [dict(zip(m, combo, strict=True)) for combo in itertools.product(*m.values())]
    cases = sc.get("cases")
    if cases is None:
        return None
    if not isinstance(cases, list) or not cases or not all(isinstance(c, dict) for c in cases):
        raise ScenarioError("cases: must be a non-empty list of mappings")
    return cases


def expand(sc, base="."):
    """Resolve `include:` steps, apply `vars:` and repeat the steps once per `cases:`/`matrix:` entry."""
    if not isinstance(sc, dict) or not isinstance(sc.get("steps"), list):
        return sc
    sc = copy.deepcopy(sc)
    variables = sc.get("vars") or {}
    if not isinstance(variables, dict):
        raise ScenarioError("vars: must be a mapping")
    steps = _resolve(sc["steps"], Path(base), [])
    cases = _cases(sc)
    if cases is None:
        sc["steps"] = render(steps, variables)
        return sc
    expanded = []
    for n, case in enumerate(cases, 1):
        label = str(case.get("name") or ", ".join(f"{k}={v}" for k, v in case.items()))
        for st in steps:
            if not isinstance(st, dict):
                expanded.append(st)
                continue
            if st.get("once") and n > 1:
                continue
            st = render(st, {**variables, **case})
            if not st.get("once"):
                st = {**st, "id": f"{st.get('id')}-{n}", "title": f"[{label}] {st.get('title', '')}", "case": label}
            expanded.append(st)
    sc["steps"] = expanded
    return sc


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


def _check_args(kind, arg, where, errors):
    if kind == "dialog" and arg not in ("accept", "dismiss"):
        errors.append(f"{where}: dialog must be accept or dismiss")
    if kind == "text_matches" and isinstance(arg, dict) and "pattern" in arg:
        try:
            re.compile(arg["pattern"])
        except re.error as e:
            errors.append(f"{where}: invalid pattern ({e})")
    need = REQUIRED.get(kind)
    if not need:
        return
    if not isinstance(arg, dict):
        errors.append(f"{where}: {kind} needs a mapping with {', '.join(need)}")
        return
    missing = [k for k in need if k not in arg]
    if missing:
        errors.append(f"{where}: {kind} is missing {', '.join(missing)}")


def _check_privacy(p, errors):
    if p is None:
        return
    if not isinstance(p, dict):
        errors.append("privacy: must be a mapping")
        return
    for key in p:
        if key not in PRIVACY_KEYS:
            errors.append(f"privacy.{key}: unknown (allowed: {', '.join(sorted(PRIVACY_KEYS))})")
    for key in ("mask", "patterns", "selectors", "keep"):
        if p.get(key) is not None and not isinstance(p[key], list):
            errors.append(f"privacy.{key}: must be a list")
    for rule in p.get("mask") or []:
        if rule not in PII_RULES:
            errors.append(f"privacy.mask: unknown rule {rule!r} (allowed: {', '.join(sorted(PII_RULES))})")
    if p.get("ocr") is not None and p["ocr"] not in OCR_MODES:
        errors.append(f"privacy.ocr: must be one of {', '.join(sorted(OCR_MODES))}")
    for pat in p.get("patterns") or []:
        try:
            re.compile(str(pat))
        except re.error as e:
            errors.append(f"privacy.patterns: invalid pattern {pat!r}: {e}")


def validate(sc) -> list[str]:
    """Return a list of human-readable problems; empty means the scenario is runnable."""
    errors = []
    if not isinstance(sc, dict):
        return ["scenario must be a mapping"]
    if not sc.get("name"):
        errors.append("name: required")
    if sc.get("driver") not in (None, "agent-browser", "bsk"):
        errors.append("driver: must be agent-browser or bsk")
    settings = sc.get("settings") or {}
    if not isinstance(settings, dict):
        errors.append("settings: must be a mapping")
        settings = {}
    for key in settings:
        if key not in SETTINGS:
            errors.append(f"settings.{key}: unknown (allowed: {', '.join(sorted(SETTINGS))})")
    _check_privacy(sc.get("privacy"), errors)
    tabs = sc.get("tabs")
    if not isinstance(tabs, dict) or not tabs:
        errors.append("tabs: at least one tab is required")
        tabs = {}
    for name, cfg in tabs.items():
        if not isinstance(cfg, dict) or not (cfg.get("url") or cfg.get("app")):
            errors.append(f"tabs.{name}: url (web page) or app (desktop app) is required")
            continue
        for key in cfg.get("dbx") or {}:
            if key not in DBX_KEYS:
                errors.append(f"tabs.{name}.dbx.{key}: unknown (allowed: {', '.join(sorted(DBX_KEYS))})")
        conn = (cfg.get("dbx") or {}).get("connect")
        if conn is not None:
            if not isinstance(conn, dict) or not conn.get("name"):
                errors.append(f"tabs.{name}.dbx.connect: needs at least `name`")
            else:
                for key in conn:
                    if key not in DBX_CONNECT_KEYS:
                        errors.append(f"tabs.{name}.dbx.connect.{key}: unknown")
                db = conn.get("database", "default")
                if db not in (sc.get("databases") or {}):
                    errors.append(f"tabs.{name}.dbx.connect.database: {db!r} not in databases")
        for i, a in enumerate(cfg.get("setup", []) or []):
            kind = _single_key(a, f"tabs.{name}.setup[{i}]", ACTIONS, errors)
            if kind:
                _check_args(kind, a[kind], f"tabs.{name}.setup[{i}]", errors)
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
        sub = st.get("subtitle")
        if sub is not None and not isinstance(sub, str | dict) or isinstance(sub, dict) and not sub:
            errors.append(f"{where}: subtitle must be text or a non-empty map of language -> text")
        if st.get("tab") not in tabs:
            errors.append(f"{where}: tab must be one of {sorted(tabs)}")
        if not st.get("expect"):
            errors.append(f"{where}: expect is required (every step must state what it proves)")
        for j, a in enumerate(st.get("actions", []) or []):
            kind = _single_key(a, f"{where}.actions[{j}]", ACTIONS, errors)
            if kind:
                _check_args(kind, a[kind], f"{where}.actions[{j}]", errors)
            if kind == "sql" and tabs.get(st.get("tab"), {}).get("kind") != "dbx":
                errors.append(f"{where}.actions[{j}]: sql requires a tab with kind: dbx")
        for j, e in enumerate(st.get("expect", []) or []):
            kind = _single_key(e, f"{where}.expect[{j}]", EXPECTS, errors)
            if kind:
                _check_args(kind, e[kind], f"{where}.expect[{j}]", errors)
            if kind == "db":
                arg = e["db"] or {}
                db = arg.get("database", "default")
                if db not in (sc.get("databases") or {}):
                    errors.append(f"{where}.expect[{j}]: database '{db}' is not defined under databases")
                if "sql" not in arg or "rows" not in arg:
                    errors.append(f"{where}.expect[{j}]: db needs sql and rows")
        zoom = st.get("zoom")
        if zoom is not None and not (isinstance(zoom, str) or (isinstance(zoom, dict) and "target" in zoom)):
            errors.append(f"{where}: zoom needs a selector or a mapping with target")
        if st.get("layout") not in (None, "split"):
            errors.append(f"{where}: layout must be split")
        for j, a in enumerate(st.get("annotate", []) or []):
            kind = _single_key(a, f"{where}.annotate[{j}]", ANNOTATIONS, errors)
            if kind and not (isinstance(a[kind], (str, dict)) and (isinstance(a[kind], str) or "target" in a[kind])):
                errors.append(f"{where}.annotate[{j}]: {kind} needs a target")
    return errors


def load_env_file(path):
    """Minimal .env reader (KEY=VALUE, # comments, optional quotes); existing env vars are not overridden."""
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.removeprefix("export ").strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
            value = value[1:-1]
        os.environ.setdefault(key, value)


def load(path) -> dict:
    sc = expand(yaml.safe_load(Path(path).read_text(encoding="utf-8")), Path(path).resolve().parent)
    problems = validate(sc)
    if problems:
        raise ScenarioError("invalid scenario:\n  - " + "\n  - ".join(problems))
    sc["_dir"] = str(Path(path).resolve().parent)  # relative upload files resolve against the scenario
    return sc
