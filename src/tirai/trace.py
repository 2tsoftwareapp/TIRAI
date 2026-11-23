"""Turn a BrowserSkill `bsk record` trace (a flow a person clicked through once) into a TIRAI scenario.

bsk traces name targets by accessibility role + name, not CSS. With `resolve=True` the flow is replayed in a
fresh bsk session and every target is resolved to a stable CSS selector (id, data-testid, name, then a short
nth-of-type path). Each click/press/navigation closes a scenario step; its expectation is derived from what
changed in the next recorded state (new URL path or new on-screen text). Review the result, then dry-run it.
"""

import json
import re
from pathlib import Path
from urllib.parse import urlparse

import yaml

OPS = {"fill", "click", "press", "select", "navigate", "hover"}
CLOSES_STEP = {"click", "press", "navigate"}


TEXT_RE = re.compile(r'^\s*(?:StaticText|heading|alert|status)\s+"(.+)"', re.M)


def env_name(target):
    """Placeholder for a value bsk redacted (passwords): `Password` -> `${PASSWORD}`."""
    slug = re.sub(r"[^A-Za-z0-9]+", "_", target.get("name") or "secret").strip("_").upper()
    return slug or "SECRET"


def describe(op, target, value=None):
    name = (target or {}).get("name") or ""
    if op == "fill":
        return f"fill {name}"
    if op == "select":
        return f"select {value} in {name}"
    if op == "press":
        return f"press {value}"
    if op == "navigate":
        return f"open {value}"
    return f"{op} {name}".strip()


def placeholder(target):
    """Unresolved selector, kept readable so a reviewer can replace it."""
    return f"TODO role={target.get('role')} name={target.get('name')!r}"


def state_texts(states_dir, state):
    if not states_dir or not state:
        return []
    path = Path(states_dir) / f"{state}.txt"
    return TEXT_RE.findall(path.read_text(encoding="utf-8")) if path.is_file() else []


def plan(trace, states_dir=None, selectors=None):
    """Group trace steps into scenario steps (pure; selectors map trace step id -> CSS)."""
    selectors = selectors or {}
    urls = {s["id"]: s.get("url", "") for s in trace.get("states", [])}
    start = trace.get("entry", {}).get("start_url") or next(iter(urls.values()), "")
    steps, env, skipped = [], [], []
    first = next((s for s in trace.get("steps", []) if s.get("target")), None)
    open_expect = {"visible": selectors.get(first["id"])} if first and selectors.get(first["id"]) else None
    steps.append(
        {
            "id": "S1",
            "tab": "app",
            "title": f"Open {urlparse(start).path or '/'}",
            "actions": [{"navigate": start}],
            "expect": [open_expect or {"url_contains": urlparse(start).path or "/"}],
        }
    )
    actions, words, from_state = [], [], None
    for st in trace.get("steps", []):
        op, target = st.get("op"), st.get("target") or {}
        if op not in OPS:
            skipped.append(f"step {st.get('id')}: unsupported op {op!r}")
            continue
        from_state = from_state or st.get("state")
        sel = selectors.get(st.get("id")) or placeholder(target)
        if op == "fill":
            value = st.get("value", "")
            if st.get("redacted"):
                value = f"${{{env_name(target)}}}"
                env.append(env_name(target))
            actions.append({"fill": {"selector": sel, "value": value}})
        elif op == "select":
            actions.append({"select": {"selector": sel, "value": st.get("value")}})
        elif op == "press":
            actions.append(
                {"press": {"key": st.get("key") or st.get("value"), **({"selector": sel} if target else {})}}
            )
        elif op == "navigate":
            actions.append({"navigate": st.get("url") or st.get("value")})
        else:
            actions.append({op: sel})
        words.append(describe(op, target, st.get("key") or st.get("value") or st.get("url")))
        if op in CLOSES_STEP:
            to_state = (st.get("result") or {}).get("state")
            steps.append(_step(len(steps) + 1, actions, words, urls, from_state, to_state, states_dir, sel))
            actions, words, from_state = [], [], None
    if actions:
        steps.append(_step(len(steps) + 1, actions, words, urls, from_state, from_state, states_dir, sel))
    origin = f"{urlparse(start).scheme}://{urlparse(start).netloc}/"
    scenario = {
        "name": trace.get("purpose") or "Recorded flow",
        "tabs": {"app": {"url": origin, "label": "App"}},
        "steps": steps,
    }
    return scenario, sorted(set(env)), skipped


def _step(n, actions, words, urls, before, after, states_dir, last_sel):
    expect = []
    old, new = urls.get(before, ""), urls.get(after, "")
    if new and urlparse(new).path != urlparse(old).path:
        expect.append({"url_contains": urlparse(new).path})
    fresh = [t for t in state_texts(states_dir, after) if t not in set(state_texts(states_dir, before))]
    if fresh:
        expect.append({"text_contains": {"text": fresh[-1][:80]}})
    if not expect:
        expect.append({"visible": last_sel})
    title = ", ".join(words)
    return {"id": f"S{n}", "tab": "app", "title": title[:1].upper() + title[1:], "actions": actions, "expect": expect}


def resolve(trace, scope="tirai-trace", env=None):
    """Replay the trace in a fresh bsk session and return {trace step id: CSS selector}."""
    import os

    from tirai.bsk import Bsk
    from tirai.resources import asset_text

    env = {**os.environ, **(env or {})}
    b = Bsk()
    start = trace.get("entry", {}).get("start_url")
    tab = b.open_session(start, scope)
    out = {}
    try:
        b.sync(tab)
        for st in trace.get("steps", []):
            op, target = st.get("op"), st.get("target") or {}
            if op not in OPS or not target:
                continue
            nth = int(target.get("nth") or 0)
            args = ",".join(json.dumps(v) for v in (target.get("role"), target.get("name"), nth))
            expr = f"{asset_text('resolve-target.js')}({args})"
            sel = None
            for _ in range(20):
                sel = b.evaluate(tab, expr)
                if sel:
                    break
                b.sync(tab)
            if not sel:
                raise RuntimeError(
                    f"step {st.get('id')}: no element with role={target.get('role')} name={target.get('name')!r}"
                )
            out[st["id"]] = sel
            if op == "fill":
                value = env.get(env_name(target), "") if st.get("redacted") else st.get("value", "")
                b.fill(tab, sel, value)
            elif op == "select":
                b.select(tab, sel, st.get("value"))
            elif op == "press":
                b.press(tab, st.get("key") or st.get("value"), sel)
            elif op == "hover":
                b.hover(tab, sel)
            else:
                b.click(tab, sel)
                b.sync(tab)
    finally:
        b.close_session()
    return out


def from_trace(trace_path, out_path, do_resolve=True, scope="tirai-trace"):
    trace_path = Path(trace_path)
    trace_file = trace_path / "trace.json" if trace_path.is_dir() else trace_path
    trace = json.loads(trace_file.read_text(encoding="utf-8"))
    states_dir = trace_file.parent / "states"
    selectors = resolve(trace, scope) if do_resolve else {}
    scenario, env, skipped = plan(trace, states_dir, selectors)
    text = yaml.safe_dump(scenario, sort_keys=False, allow_unicode=True, width=120)
    Path(out_path).write_text(text, encoding="utf-8")
    return scenario, env, skipped
