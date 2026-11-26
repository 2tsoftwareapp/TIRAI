"""Scenario loading, validation and `${ENV}` interpolation."""

import copy
import itertools
import os
import re
from pathlib import Path

import yaml

ACTIONS = {
    "navigate", "fill", "click", "press", "wait", "wait_for", "sql", "dbx_login",
    "select", "hover", "scroll", "upload", "dialog", "save", "eval", "expect",
    "clear", "download",
}  # fmt: skip
EXPECTS = {
    "visible", "not_visible", "text_contains", "text_matches", "url_contains",
    "value", "attribute", "count", "request", "no_console_errors", "db",
    "pdf", "xlsx", "image",
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
    "download": ("selector",),
    "pdf": ("path",),
    "xlsx": ("path",),
    "image": ("path",),
}
PREVIEW_COMMON_KEYS = {"annotate", "preview", "zoom", "spotlight", "hold", "title", "subtitle", "label"}
PDF_KEYS = {"path", "pages", "contains", *PREVIEW_COMMON_KEYS}
XLSX_KEYS = {"path", "sheets", "contains", "sheet", "max_rows", "max_cols", *PREVIEW_COMMON_KEYS}
IMAGE_KEYS = {"path", "contains", *PREVIEW_COMMON_KEYS}
PREVIEW_ANNOTATIONS = {"box", "arrow", "highlight", "circle", "badge"}
ANNOTATIONS = {
    "box", "circle", "underline", "strike", "arrow", "callout", "magnify", "text", "badge", "highlight", "blur",
}  # fmt: skip
ANNOTATION_STYLES = {"error", "warning", "info", "success"}
BADGE_POS = {"top-left", "top-right", "bottom-left", "bottom-right", "left", "right"}
SETTINGS = {
    "hold", "timing_scale", "expect_timeout", "camera", "camera_factor", "fast_forward",
    "viewport", "auto_scroll", "strict_network", "ignore_requests", "trim_still",
    "single_tab", "pace", "action_delay", "typing_delay", "cursor_glide", "spotlight", "theme",
    "action_annotate", "action_zoom", "action_hold", "show_expects", "expect_pos", "summary_card",
    "device", "locale", "timezone", "color_scheme",
}  # fmt: skip
# Shell commands per database: reset before a full recording, snapshot before each write step, restore on
# `record --from-step` (the data as it was before the replaced steps wrote).
DB_HOOKS = ("reset", "snapshot", "restore")
# Browser emulation (agent-browser only); the runner reads the values back from the page before step 1.
EMULATION = ("device", "locale", "timezone", "color_scheme")
LOCALE_RE = re.compile(r"^[A-Za-z]{2,3}(-[A-Za-z0-9]{2,8})*$")
TIMEZONE_RE = re.compile(r"^(UTC|[A-Za-z_]+(/[A-Za-z0-9_+-]+)+)$")
PACE_MODES = {"fast", "human", "slow"}
CAMERA_MODES = {"follow", "annotate", "action"}
EXPECT_POS_MODES = {"top-right", "top-left", "bottom-right", "bottom-left"}
THEME_KEYS = {
    "font", "header_size", "header_height", "subtitle_size", "subtitle_height",
    "subtitle_bg", "subtitle_color", "tab_colors", "pass_color", "fail_color",
    "accent", "cursor_color", "ripple_color", "spotlight_opacity", "label_font",
}  # fmt: skip
HEX_COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")
DB_KEYS = {"database", "sql", "rows", "columns", "save", "label"}
STEP_KEYS = {
    "id", "tab", "title", "subtitle", "voice", "actions", "expect", "annotate", "hold", "zoom", "spotlight",
    "layout", "split_with", "once", "case", "save", "writes", "for_each", "as",
    "action_annotate", "show_expects",
}  # fmt: skip
# Playwright-only selector syntax: agent-browser/bsk take CSS, so these never match.
PLAYWRIGHT_RE = re.compile(
    r":has-text\(|:text-is\(|:text\(|:text-matches\(|:nth-match\(|:visible\b|>>|^internal:|^xpath="
)
WRITE_SQL_RE = re.compile(
    r"^\s*(insert|update|delete|merge|upsert|replace|create|alter|drop|truncate|grant|revoke|call|exec)\b", re.I | re.M
)
PII_RULES = {"email", "phone", "card", "token"}
PRIVACY_KEYS = {"mask", "patterns", "selectors", "keep", "inputs", "ocr"}
OCR_MODES = {"off", "warn", "fix", "fail"}
DBX_KEYS = {"new_query", "editor", "password", "run_key", "connect", "connection", "error"}
DBX_CONNECT_KEYS = {"name", "database", "host", "password_env"}
ENV_RE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")
VAR_RE = re.compile(r"\{\{\s*([A-Za-z_][A-Za-z0-9_]*)\s*\}\}")


class ScenarioError(ValueError):
    pass


def _is_num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


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


def read_yaml(path):
    """Parse a YAML file; syntax errors become a ScenarioError with the line and a hint, not a traceback."""
    path = Path(path)
    text = path.read_text(encoding="utf-8")
    try:
        return yaml.safe_load(text)
    except yaml.YAMLError as e:
        mark = getattr(e, "problem_mark", None)
        where = f"{path}:{mark.line + 1}:{mark.column + 1}" if mark else str(path)
        problem = getattr(e, "problem", None) or str(e).splitlines()[0]
        msg = f"{where}: YAML syntax error: {problem}"
        line = text.splitlines()[mark.line] if mark and mark.line < len(text.splitlines()) else ""
        if mark and line.strip():
            msg += f"\n    {line.strip()}"
        if re.search(r"[:,\[{]\s*(\$\{|\{\{)", line):
            msg += '\n  hint: quote values that start with ${...} or {{...}}, e.g. value: "${APP_USER}"'
        raise ScenarioError(msg) from None


def _include(item, base, stack):
    path = (base / item["include"]).resolve()
    if path in stack:
        raise ScenarioError(f"include cycle: {' -> '.join(p.name for p in [*stack, path])}")
    if not path.is_file():
        raise ScenarioError(f"include not found: {item['include']} (relative to {base})")
    data = read_yaml(path)
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


def _repeat(st, variables):
    """`for_each:` -> one step per item (`{{field}}` per mapping item, `{{item}}`/`{{<as>}}` for scalars)."""
    if not isinstance(st, dict) or st.get("for_each") is None:
        return [render(st, variables)]
    items = st["for_each"]
    if isinstance(items, str):
        name = VAR_RE.fullmatch(items.strip())
        name = name.group(1) if name else items.strip()
        if name not in variables:
            raise ScenarioError(f"steps[{st.get('id')}].for_each: {items!r} is not a list in vars/cases")
        items = variables[name]
    if not isinstance(items, list) or not items:
        raise ScenarioError(f"steps[{st.get('id')}].for_each: must be a non-empty list (or the name of one)")
    base = {k: v for k, v in st.items() if k not in ("for_each", "as")}
    out = []
    for i, item in enumerate(items, 1):
        local = dict(item) if isinstance(item, dict) else {st.get("as") or "item": item}
        step = render(base, {**variables, **local, "index": i})
        step["id"] = f"{step.get('id')}-{i}"
        out.append(step)
    return out


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
        sc["steps"] = [x for st in steps for x in _repeat(st, variables)]
        return sc
    expanded = []
    for n, case in enumerate(cases, 1):
        label = str(case.get("name") or ", ".join(f"{k}={v}" for k, v in case.items()))
        for st in steps:
            if not isinstance(st, dict):
                expanded.append(st)
                continue
            once = st.get("once")
            if once == "last" and n < len(cases) or once and once != "last" and n > 1:
                continue
            for x in _repeat(st, {**variables, **case}):
                if not once:
                    x = {**x, "id": f"{x.get('id')}-{n}", "title": f"[{label}] {x.get('title', '')}", "case": label}
                expanded.append(x)
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


def js_regex_problem(pattern):
    """Best-effort check of a JavaScript RegExp source with Python `re` (JS-only forms translated first)."""
    if not isinstance(pattern, str):
        return "must be a string"
    py = pattern.replace("[^]", "[\\s\\S]")
    py = re.sub(r"\(\?<(?![=!])", "(?P<", py)
    py = re.sub(r"\\k<(\w+)>", r"(?P=\1)", py)
    try:
        re.compile(py)
    except re.error as e:
        return str(e)
    return None


def _check_args(kind, arg, where, errors):
    if kind == "dialog" and arg not in ("accept", "dismiss"):
        errors.append(f"{where}: dialog must be accept or dismiss")
    if kind in ("text_matches", "save") and isinstance(arg, dict) and "pattern" in arg:
        problem = js_regex_problem(arg["pattern"])
        if problem:
            errors.append(f"{where}: invalid pattern ({problem}; JavaScript RegExp syntax)")
    if kind == "db" and isinstance(arg, dict):
        unknown = set(arg) - DB_KEYS
        if unknown:
            allowed = ", ".join(sorted(DB_KEYS))
            errors.append(f"{where}: db has unknown {', '.join(sorted(unknown))} (allowed: {allowed})")
        if arg.get("save") is not None and not isinstance(arg["save"], dict):
            errors.append(f"{where}: db save must map variable -> column")
    if kind in ("pdf", "xlsx", "image") and isinstance(arg, dict):
        allowed = PDF_KEYS if kind == "pdf" else XLSX_KEYS if kind == "xlsx" else IMAGE_KEYS
        unknown = set(arg) - allowed
        if unknown:
            allowed_s = ", ".join(sorted(allowed))
            errors.append(f"{where}: {kind} has unknown {', '.join(sorted(unknown))} (allowed: {allowed_s})")
        pages = arg.get("pages") if kind == "pdf" else None
        if pages is not None and not (
            isinstance(pages, int)
            or isinstance(pages, list)
            and len(pages) == 2
            and all(isinstance(x, int) for x in pages)
        ):
            errors.append(f"{where}: pdf pages must be an int (exact) or [min, max]")
        ann = arg.get("annotate")
        if ann is not None and ann not in (True, False, "auto"):
            if not isinstance(ann, list):
                errors.append(f"{where}: {kind}.annotate must be true, 'auto' or a list of annotations")
            else:
                for k_i, item in enumerate(ann):
                    ak = _single_key(item, f"{where}.{kind}.annotate[{k_i}]", PREVIEW_ANNOTATIONS, errors)
                    if ak and not isinstance(item[ak], (str, dict)):
                        errors.append(f"{where}.{kind}.annotate[{k_i}]: {ak} needs text/cell/x,y")
    if kind == "save" and isinstance(arg, dict) and arg.get("timeout") is not None:
        if not isinstance(arg["timeout"], int | float) or arg["timeout"] <= 0:
            errors.append(f"{where}: save timeout must be a positive number of seconds")
    if kind == "expect":
        items = arg if isinstance(arg, list) else [arg]
        for j, e in enumerate(items):
            sub = _single_key(e, f"{where}.expect[{j}]", EXPECTS, errors)
            if sub:
                _check_args(sub, e[sub], f"{where}.expect[{j}]", errors)
        return
    if kind in ("click", "clear", "hover", "scroll", "visible", "not_visible") and isinstance(arg, dict):
        if "selector" not in arg:
            errors.append(f"{where}: {kind} mapping is missing selector")
    if kind == "url_contains" and isinstance(arg, dict):
        if "text" not in arg:
            errors.append(f"{where}: url_contains mapping is missing text")
    if kind == "wait_for" and isinstance(arg, dict):
        if not (arg.get("selector") or arg.get("idle")):
            errors.append(f"{where}: wait_for needs a selector or idle: true")
    need = REQUIRED.get(kind)
    if not need:
        if kind == "save" and isinstance(arg, list):
            for x in arg:
                _check_args("save", x, where, errors)
        return
    if kind == "save" and isinstance(arg, list):
        for x in arg:
            _check_args("save", x, where, errors)
        return
    if not isinstance(arg, dict):
        errors.append(f"{where}: {kind} needs a mapping with {', '.join(need)}")
        return
    missing = [k for k in need if k not in arg]
    if missing:
        errors.append(f"{where}: {kind} is missing {', '.join(missing)}")


def _selectors(node, key=None):
    """Selector strings in an action/expectation (same positions `targets:` substitution uses)."""
    from tirai.targets import SELECTOR_ACTIONS, SELECTOR_KEYS

    if isinstance(node, str):
        return [node] if key in SELECTOR_KEYS or key in SELECTOR_ACTIONS or key == "fill" else []
    if isinstance(node, list):
        return [x for v in node for x in _selectors(v, key)]
    if isinstance(node, dict):
        return [x for k, v in node.items() for x in _selectors(v, k)]
    return []


def selector_problems(item, where):
    """Playwright-only syntax never matches (drivers take CSS): fail at validate time, not as 'not found'."""
    out = []
    for sel in _selectors(item):
        if PLAYWRIGHT_RE.search(sel):
            out.append(
                f"{where}: {sel!r} uses Playwright-only selector syntax; drivers take CSS. Use a locator instead "
                '(text=…, text*=…, role=button[name="…"], label=…, testid=…), optionally under targets: with '
                "within:, or native CSS :has()"
            )
    return out


def sql_writes(sql):
    """True when SQL text contains a data/schema-changing statement."""
    return bool(WRITE_SQL_RE.search(re.sub(r"--[^\n]*|/\*.*?\*/", "", str(sql), flags=re.S)))


def step_writes(st):
    """Why a step changes data (`writes:` text, or the write SQL it runs), else None."""
    w = st.get("writes")
    if w:
        return w if isinstance(w, str) else "writes data"
    for a in st.get("actions") or []:
        if isinstance(a, dict) and isinstance(a.get("sql"), str) and sql_writes(a["sql"]):
            return f"sql: {' '.join(a['sql'].split())[:60]}"
    return None


def _check_step_body(st, where, tabs, errors, need_expect=True):
    inline = any(isinstance(a, dict) and "expect" in a for a in st.get("actions") or [])
    if need_expect and not st.get("expect") and not inline:
        errors.append(f"{where}: expect is required (every step must state what it proves)")
    for j, a in enumerate(st.get("actions", []) or []):
        kind = _single_key(a, f"{where}.actions[{j}]", ACTIONS, errors)
        if kind:
            _check_args(kind, a[kind], f"{where}.actions[{j}]", errors)
            errors += selector_problems(a, f"{where}.actions[{j}]")
        if kind == "sql" and tabs.get(st.get("tab"), {}).get("kind") != "dbx":
            errors.append(f"{where}.actions[{j}]: sql requires a tab with kind: dbx")
    if st.get("save") is not None:
        saves = st["save"] if isinstance(st["save"], list) else [st["save"]]
        for x in saves:
            _check_args("save", x, f"{where}.save", errors)
    for j, e in enumerate(st.get("expect", []) or []):
        kind = _single_key(e, f"{where}.expect[{j}]", EXPECTS, errors)
        if kind:
            _check_args(kind, e[kind], f"{where}.expect[{j}]", errors)
            errors += selector_problems(e, f"{where}.expect[{j}]")


def _check_theme(th, where, errors):
    if th is None:
        return
    if not isinstance(th, dict):
        errors.append(f"{where}: must be a mapping")
        return
    for key in th:
        if key not in THEME_KEYS:
            errors.append(f"{where}.{key}: unknown (allowed: {', '.join(sorted(THEME_KEYS))})")
    for key in ("subtitle_bg", "subtitle_color", "pass_color", "fail_color", "accent", "cursor_color", "ripple_color"):
        val = th.get(key)
        if val is not None and (not isinstance(val, str) or not HEX_COLOR_RE.match(val)):
            errors.append(f"{where}.{key}: must be a #RRGGBB hex color")
    if th.get("tab_colors") is not None:
        tc = th["tab_colors"]
        if not isinstance(tc, list) or not tc or not all(isinstance(c, str) and HEX_COLOR_RE.match(c) for c in tc):
            errors.append(f"{where}.tab_colors: must be a non-empty list of #RRGGBB hex colors")
    for key in ("header_size", "header_height", "subtitle_size", "subtitle_height"):
        val = th.get(key)
        if val is not None and (not isinstance(val, int) or val <= 0):
            errors.append(f"{where}.{key}: must be a positive integer")
    op = th.get("spotlight_opacity")
    if op is not None and (not isinstance(op, int | float) or not 0 <= op <= 0.85):
        errors.append(f"{where}.spotlight_opacity: must be between 0 and 0.85")


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


def write_safety(sc):
    """Write steps with nothing that makes running them again safe: no `cleanup:`, no database reset/snapshot hook
    and no `{{run_id}}` in their data. Running such a step twice (dry-run --allow-writes, re-record) duplicates data."""
    dbs = [d for d in (sc.get("databases") or {}).values() if isinstance(d, dict)]
    if sc.get("cleanup") or any(d.get("reset") or d.get("snapshot") for d in dbs):
        return []
    return [st["id"] for st in sc.get("steps") or [] if step_writes(st) and "run_id" not in str(st)]


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
    vp = settings.get("viewport")
    if vp is not None and not (
        isinstance(vp, dict) and all(isinstance(vp.get(k), int) and vp[k] > 0 for k in ("width", "height"))
    ):
        errors.append("settings.viewport: needs integer width and height")
    for key, ok, hint in (
        ("device", lambda v: isinstance(v, str) and v.strip(), 'a device name, e.g. "iPhone 14" or "Pixel 7"'),
        ("locale", lambda v: isinstance(v, str) and LOCALE_RE.match(v), "a BCP 47 tag, e.g. ja-JP or vi-VN"),
        ("timezone", lambda v: isinstance(v, str) and TIMEZONE_RE.match(v), "an IANA name, e.g. Asia/Tokyo"),
        ("color_scheme", lambda v: v in ("dark", "light"), "dark or light"),
    ):
        if settings.get(key) is not None and not ok(settings[key]):
            errors.append(f"settings.{key}: must be {hint}")
    if settings.get("device") is not None and vp is not None:
        errors.append("settings.device: sets its own viewport; remove settings.viewport")
    if settings.get("device") and any((t or {}).get("kind") == "dbx" for t in (sc.get("tabs") or {}).values()):
        errors.append("settings.device: emulation applies to every tab, and a DBX grid is unreadable at phone size")
    if settings.get("ignore_requests") is not None and not isinstance(settings["ignore_requests"], list):
        errors.append("settings.ignore_requests: must be a list of URL substrings")
    if settings.get("single_tab") is not None and not isinstance(settings["single_tab"], bool):
        errors.append("settings.single_tab: must be true or false")
    if settings.get("summary_card") is not None and not isinstance(settings["summary_card"], bool):
        errors.append("settings.summary_card: must be true or false")
    meta = sc.get("meta")
    if meta is not None:
        if not isinstance(meta, dict) or not all(isinstance(v, (str, int, float)) for v in meta.values()):
            errors.append("meta: must be a mapping of short text values (ticket, env, build, ...)")
        elif any("${" in str(v) for v in meta.values()):
            # meta is printed on the title card and written to the timeline: never route env values there.
            errors.append("meta: ${ENV} is not expanded here; write the value itself (it is shown on video)")
    if settings.get("pace") is not None and settings["pace"] not in PACE_MODES:
        errors.append(f"settings.pace: must be one of {', '.join(sorted(PACE_MODES))}")
    if settings.get("camera") is not None and settings["camera"] not in CAMERA_MODES:
        errors.append(f"settings.camera: must be one of {', '.join(sorted(CAMERA_MODES))}")
    if settings.get("spotlight") is not None and not isinstance(settings["spotlight"], bool):
        errors.append("settings.spotlight: must be true or false")
    if settings.get("cursor_glide") is not None and not isinstance(settings["cursor_glide"], bool):
        errors.append("settings.cursor_glide: must be true or false")
    if settings.get("action_annotate") is not None and not isinstance(settings["action_annotate"], bool):
        errors.append("settings.action_annotate: must be true or false")
    az = settings.get("action_zoom")
    if az is not None and not (isinstance(az, bool) or (isinstance(az, int | float) and az >= 1.0)):
        errors.append("settings.action_zoom: must be true, false, or a zoom factor >= 1.0")
    ah = settings.get("action_hold")
    if ah is not None and (isinstance(ah, bool) or not isinstance(ah, int | float) or ah < 0):
        errors.append("settings.action_hold: must be a non-negative number of seconds")
    if settings.get("show_expects") is not None and not isinstance(settings["show_expects"], bool):
        errors.append("settings.show_expects: must be true or false")
    if settings.get("expect_pos") is not None and settings["expect_pos"] not in EXPECT_POS_MODES:
        errors.append(f"settings.expect_pos: must be one of {', '.join(sorted(EXPECT_POS_MODES))}")
    _check_theme(sc.get("theme"), "theme", errors)
    _check_theme(settings.get("theme"), "settings.theme", errors)
    _check_privacy(sc.get("privacy"), errors)
    from tirai import targets as tg

    tg.check(sc.get("targets"), errors)
    if not errors and isinstance(sc.get("steps"), list):
        _, missing = tg.apply(sc)
        errors += [f"@{m}: not defined under targets" for m in sorted(missing)]
    tabs = sc.get("tabs")
    if not isinstance(tabs, dict) or not tabs:
        errors.append("tabs: at least one tab is required")
        tabs = {}
    for name, cfg in tabs.items():
        if isinstance(cfg, dict) and cfg.get("popup"):
            if cfg.get("app") or cfg.get("setup"):
                errors.append(f"tabs.{name}: a popup tab is adopted from the browser; no app/setup")
            continue
        if not isinstance(cfg, dict) or not (cfg.get("url") or cfg.get("app")):
            errors.append(f"tabs.{name}: url (web page), app (desktop app) or popup: true is required")
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
    for name, db in (sc.get("databases") or {}).items():
        if not isinstance(db, dict):
            continue
        for key in DB_HOOKS:
            if db.get(key) is not None and not (isinstance(db[key], str) and db[key].strip()):
                errors.append(f"databases.{name}.{key}: must be a shell command")
        if bool(db.get("snapshot")) != bool(db.get("restore")):
            errors.append(f"databases.{name}: snapshot and restore go together")
        if db.get("snapshot") and "{snapshot}" not in db["snapshot"] + db.get("restore", ""):
            errors.append(f"databases.{name}.snapshot: use {{snapshot}} for the snapshot name")
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
        voice = st.get("voice")
        if voice is not None and not isinstance(voice, str | dict) or isinstance(voice, dict) and not voice:
            errors.append(f"{where}: voice must be text or a non-empty map of language -> text")
        if st.get("tab") not in tabs:
            errors.append(f"{where}: tab must be one of {sorted(tabs)}")
        unknown = set(st) - STEP_KEYS
        if unknown:
            errors.append(f"{where}: unknown {', '.join(sorted(unknown))} (allowed: {', '.join(sorted(STEP_KEYS))})")
        if st.get("once") not in (None, True, False, "first", "last"):
            errors.append(f"{where}: once must be true, first or last")
        _check_step_body(st, where, tabs, errors)
        inline = [x for a in st.get("actions") or [] if isinstance(a, dict) for x in _as_list(a.get("expect"))]
        for j, e in enumerate([*(st.get("expect", []) or []), *inline]):
            kind = next(iter(e), None) if isinstance(e, dict) and len(e) == 1 else None
            if kind == "db":
                arg = e["db"] or {}
                db = arg.get("database", "default")
                if db not in (sc.get("databases") or {}):
                    errors.append(f"{where}.expect[{j}]: database '{db}' is not defined under databases")
                if "sql" not in arg or "rows" not in arg:
                    errors.append(f"{where}.expect[{j}]: db needs sql and rows")
        zoom = st.get("zoom")
        if zoom is not None and not (
            isinstance(zoom, str)
            or (isinstance(zoom, dict) and ("target" in zoom or zoom.get("mode") in ("annotate", "follow", "action")))
        ):
            errors.append(
                f"{where}: zoom needs a selector, 'annotate'/'follow'/'action', or a mapping with target/mode"
            )
        if st.get("spotlight") is not None and not isinstance(st["spotlight"], bool):
            errors.append(f"{where}: spotlight must be true or false")
        if st.get("action_annotate") is not None and not isinstance(st["action_annotate"], bool):
            errors.append(f"{where}: action_annotate must be true or false")
        if st.get("show_expects") is not None and not isinstance(st["show_expects"], bool):
            errors.append(f"{where}: show_expects must be true or false")
        if st.get("layout") not in (None, "split"):
            errors.append(f"{where}: layout must be split")
        for j, a in enumerate(st.get("annotate", []) or []):
            kind = _single_key(a, f"{where}.annotate[{j}]", ANNOTATIONS, errors)
            if kind and not (isinstance(a[kind], (str, dict)) and (isinstance(a[kind], str) or "target" in a[kind])):
                errors.append(f"{where}.annotate[{j}]: {kind} needs a target")
            elif kind and isinstance(a[kind], dict):
                style = a[kind].get("style")
                if style is not None and style not in ANNOTATION_STYLES:
                    errors.append(f"{where}.annotate[{j}]: style must be one of {sorted(ANNOTATION_STYLES)}")
                pos = a[kind].get("pos")
                if kind == "badge" and pos is not None and pos not in BADGE_POS:
                    errors.append(f"{where}.annotate[{j}]: badge pos must be one of {sorted(BADGE_POS)}")
                if kind == "callout" and not a[kind].get("label"):
                    errors.append(f"{where}.annotate[{j}]: callout needs a label")
                factor = a[kind].get("factor")
                if kind == "magnify" and factor is not None and not (_is_num(factor) and 1.2 <= factor <= 6):
                    errors.append(f"{where}.annotate[{j}]: magnify factor must be a number from 1.2 to 6")
                curve = a[kind].get("curve")
                if kind == "arrow" and curve is not None and not (_is_num(curve) and -1 <= curve <= 1):
                    errors.append(f"{where}.annotate[{j}]: arrow curve must be a number from -1 to 1")
    cleanup = sc.get("cleanup")
    if cleanup is not None:
        if not isinstance(cleanup, list) or not all(isinstance(c, dict) for c in cleanup):
            errors.append("cleanup: must be a list of steps (tab + actions)")
        else:
            for i, st in enumerate(cleanup):
                where = f"cleanup[{st.get('id') or i}]"
                if st.get("tab") not in tabs:
                    errors.append(f"{where}: tab must be one of {sorted(tabs)}")
                _check_step_body(st, where, tabs, errors, need_expect=False)
    return errors


def _as_list(v):
    return [] if v is None else v if isinstance(v, list) else [v]


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
    sc = expand(read_yaml(path), Path(path).resolve().parent)
    problems = validate(sc)
    if problems:
        raise ScenarioError("invalid scenario:\n  - " + "\n  - ".join(problems))
    from tirai import targets as tg

    sc, _ = tg.apply(sc)
    sc["_dir"] = str(Path(path).resolve().parent)  # relative upload files resolve against the scenario
    return sc
