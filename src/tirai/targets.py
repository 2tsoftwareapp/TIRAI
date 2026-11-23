"""Scenario `targets:`: named elements (`@name`) located by ordered fallback locators and tagged in the page
with `data-tirai-id`, so actions, expectations, annotations and drivers all address them with plain CSS."""

import json
import re

from tirai.resources import asset_text

ATTR = "data-tirai-id"
NAME_RE = re.compile(r"^[A-Za-z_][\w-]*$")
REF_RE = re.compile(r"(?<![\w@.-])@([A-Za-z_][\w-]*)")
TAGGED_RE = re.compile(r'\[data-tirai-id~="([\w-]+)"\]')
LOCATOR_PREFIXES = ("testid=", "role=", "label=", "placeholder=", "text=", "text*=", "css=")
# Keys whose string values are selectors (actions, expectations, annotate/zoom targets).
SELECTOR_KEYS = {"selector", "target", "within"}
SELECTOR_ACTIONS = {"click", "hover", "scroll", "wait_for", "visible", "not_visible", "zoom"}
ANNOTATIONS = {"box", "circle", "arrow", "text", "badge", "highlight", "blur"}


def selector(name):
    return f'[{ATTR}~="{name}"]'


def normalize(raw):
    """`targets:` -> {name: {"locators": [...], "within": css|None, "nth": int|None}}."""
    out = {}
    for name, spec in (raw or {}).items():
        if isinstance(spec, str):
            spec = {"locators": [spec]}
        elif isinstance(spec, list):
            spec = {"locators": spec}
        else:
            spec = dict(spec)
            spec["locators"] = spec.pop("any", None) or spec.get("locators") or []
            if isinstance(spec["locators"], str):
                spec["locators"] = [spec["locators"]]
        locs = [str(x) for x in spec["locators"]]
        out[name] = {"locators": locs, "within": spec.get("within"), "nth": spec.get("nth")}
    return out


def check(raw, errors):
    if raw is None:
        return
    if not isinstance(raw, dict):
        errors.append("targets: must map names to locators")
        return
    for name, spec in raw.items():
        where = f"targets.{name}"
        if not NAME_RE.match(str(name)):
            errors.append(f"{where}: name must be letters, digits, _ or - (used as @{name})")
        if isinstance(spec, dict):
            unknown = set(spec) - {"any", "locators", "within", "nth"}
            if unknown:
                errors.append(f"{where}: unknown {', '.join(sorted(unknown))} (allowed: any, within, nth)")
            locs = spec.get("any") or spec.get("locators")
            if spec.get("nth") is not None and not isinstance(spec["nth"], int):
                errors.append(f"{where}.nth: must be an integer")
        else:
            locs = spec
        locs = [locs] if isinstance(locs, str) else locs
        if not isinstance(locs, list) or not locs or not all(isinstance(x, str) and x.strip() for x in locs):
            errors.append(f"{where}: needs a locator or a non-empty list of locators")


def _sub(value, names, used, missing):
    if is_locator(value.strip()):  # inline locator: an anonymous target
        loc = value.strip()
        name = names.setdefault(("loc", loc), f"_t{sum(1 for k in names if isinstance(k, tuple)) + 1}")
        names[name] = {"locators": [loc], "within": None, "nth": None}
        used.add(name)
        return selector(name)

    def repl(m):
        if m.group(1) not in names:
            missing.add(m.group(1))
            return m.group(0)
        used.add(m.group(1))
        return selector(m.group(1))

    return REF_RE.sub(repl, value)


def _annotations(items, names, used, missing):
    out = []
    for item in items or []:
        if isinstance(item, dict) and len(item) == 1:
            ((kind, arg),) = item.items()
            if kind in ANNOTATIONS and isinstance(arg, str):
                item = {kind: _sub(arg, names, used, missing)}
            elif kind in ANNOTATIONS and isinstance(arg, dict) and isinstance(arg.get("target"), str):
                item = {kind: {**arg, "target": _sub(arg["target"], names, used, missing)}}
        out.append(item)
    return out


def _walk(node, names, used, missing, key=None):
    if isinstance(node, dict) and "annotate" in node and key is None:
        rest = _walk({k: v for k, v in node.items() if k != "annotate"}, names, used, missing)
        return {**rest, "annotate": _annotations(node["annotate"], names, used, missing)}
    if isinstance(node, str):
        return _sub(node, names, used, missing) if key in SELECTOR_KEYS or key in SELECTOR_ACTIONS else node
    if isinstance(node, list):
        return [_walk(x, names, used, missing, key if key == "selector" else None) for x in node]
    if isinstance(node, dict):
        return {k: _walk(v, names, used, missing, "selector" if k == "selectors" else k) for k, v in node.items()}
    return node


def apply(sc):
    """Replace `@name` in selector positions with `[data-tirai-id="name"]`; returns (scenario, unknown refs)."""
    names = normalize(sc.get("targets"))
    used, missing = set(), set()
    out = dict(sc)
    out["steps"] = [_walk(st, names, used, missing) for st in sc.get("steps") or []]
    out["tabs"] = {
        t: {**cfg, "setup": _walk(cfg.get("setup") or [], names, used, missing)} if isinstance(cfg, dict) else cfg
        for t, cfg in (sc.get("tabs") or {}).items()
    }
    if isinstance(sc.get("privacy"), dict):
        out["privacy"] = _walk(sc["privacy"], names, used, missing)
    out["_targets"] = {k: v for k, v in names.items() if isinstance(k, str)}
    return out, missing


def used_in(value):
    """Target names a (substituted) action/expectation refers to."""
    if isinstance(value, str):
        return set(TAGGED_RE.findall(value))
    items = value.values() if isinstance(value, dict) else value if isinstance(value, list) else ()
    return set().union(*(used_in(v) for v in items))


def script():
    return asset_text("targets.js")


def tag_expr(targets):
    """Script that (re)tags every target in the page and evaluates to the per-target report."""
    return script() + f";window.__tiraiT.tag({json.dumps(targets, ensure_ascii=False)})"


def with_tags(targets, expr):
    """Prefix a page script so targets are (re)tagged first; the script still evaluates to `expr`'s value."""
    if not targets:
        return expr
    return tag_expr(targets) + ";" + expr


def init_script(targets):
    """Init script (agent-browser): tag as soon as the DOM exists, then keep tags in sync as it changes."""
    return (
        script() + f";(()=>{{const t={json.dumps(targets, ensure_ascii=False)};"
        "const go=()=>{try{window.__tiraiT.tag(t)}catch(e){}};"
        "if(document.documentElement)go();document.addEventListener('DOMContentLoaded',go,{once:true})})()"
    )


def describe_failure(name, info):
    counts = "; ".join((info or {}).get("counts") or []) or "not evaluated"
    return f"target @{name}: no locator matched exactly one element ({counts})"


def healed(name, spec, info):
    """Warning when a fallback locator was needed (the first one no longer matches exactly one element)."""
    if not info or not info.get("ok") or info.get("via", 0) <= 0:
        return None
    first = (info.get("counts") or [""])[0]
    return f"target @{name}: {first} -> used {spec['locators'][info['via']]!r}; update the target"


def is_locator(value):
    return isinstance(value, str) and value.startswith(LOCATOR_PREFIXES)
