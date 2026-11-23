"""`tirai capture` on agent-browser: a person clicks through a flow once in a visible browser; TIRAI writes it
as a scenario.

A page init script (assets/capture.js) logs clicks, field changes and Enter with a stable CSS selector, so no
replay is needed to resolve targets. The events are shaped like a `bsk record` trace and grouped into steps by
`tirai.trace.plan`, which also derives each step's expectation (new URL path or new heading/alert text).
"""

import tempfile
import time
from pathlib import Path

import yaml

from tirai.agentbrowser import AgentBrowser, AgentBrowserError
from tirai.resources import asset_text
from tirai.trace import env_name, plan

SETTLE = 1.5  # seconds after a click/Enter before the page state counts as its result


def to_trace(start_url, purpose, polls):
    """Build (trace, selectors, state texts) from drained polls: [{events, url, texts, t}, ...]."""
    snaps = [{"id": f"p{i}", "url": p["url"], "texts": p["texts"], "t": p["t"]} for i, p in enumerate(polls)]

    def before(t):
        return next((s["id"] for s in reversed(snaps) if s["t"] <= t), snaps[0]["id"] if snaps else None)

    def after(t):
        return next((s["id"] for s in snaps if s["t"] >= t + SETTLE * 1000), snaps[-1]["id"] if snaps else None)

    steps, selectors, n = [], {}, 0
    for p in polls:
        for ev in p["events"]:
            n += 1
            sid = f"e{n}"
            target = {"role": ev.get("role"), "name": ev.get("name")}
            st = {"id": sid, "op": ev["op"], "target": target, "state": before(ev["t"])}
            if ev.get("redacted"):
                st["redacted"] = True
            elif "value" in ev:
                st["value"] = ev["value"]
            if ev.get("key"):
                st["key"] = ev["key"]
            if ev["op"] in ("click", "press"):
                st["result"] = {"state": after(ev["t"])}
            # A field filled then submitted with Enter shows up twice; keep the last value only.
            if steps and ev["op"] == "fill" and steps[-1]["op"] == "fill" and steps[-1]["target"] == target:
                steps.pop()
            steps.append(st)
            selectors[sid] = ev["selector"]
    trace = {
        "purpose": purpose,
        "entry": {"start_url": start_url},
        "states": [{"id": s["id"], "url": s["url"]} for s in snaps],
        "steps": steps,
    }
    texts = {s["id"]: s["texts"] for s in snaps}
    return trace, selectors, texts


def write_scenario(trace, selectors, texts, out_path):
    with tempfile.TemporaryDirectory() as tmp:
        for sid, lines in texts.items():
            body = "\n".join(f'heading "{t}"' for t in lines)
            (Path(tmp) / f"{sid}.txt").write_text(body, encoding="utf-8")
        scenario, env, skipped = plan(trace, tmp, selectors)
    Path(out_path).write_text(yaml.safe_dump(scenario, sort_keys=False, allow_unicode=True, width=120), "utf-8")
    return scenario, env, skipped


def capture(url, out_path, purpose=None, timeout=600, headed=True, poll=0.7, driver=None, on_ready=None):
    """Record until the browser window is closed, Ctrl+C, or `timeout` seconds; returns plan() output."""
    b = driver or AgentBrowser(headed=headed, cursor=False)
    b.init_scripts.append(asset_text("capture.js"))
    tab = b.open_session(url, "tirai-capture")
    polls, failures, deadline = [], 0, time.monotonic() + timeout
    if on_ready:
        on_ready(b)
    try:
        while time.monotonic() < deadline and failures < 3:
            try:
                got = b.evaluate(tab, "window.__tiraiRec ? window.__tiraiRec.drain() : null")
                failures = 0
            except AgentBrowserError:
                failures += 1  # window closed by the user, or a navigation in flight
                time.sleep(poll)
                continue
            if got:
                polls.append(got)
            time.sleep(poll)
    except KeyboardInterrupt:
        pass
    finally:
        b.close_session()
    if not any(p["events"] for p in polls):
        raise RuntimeError("no interactions were recorded")
    trace, selectors, texts = to_trace(url, purpose or "Recorded flow", polls)
    return write_scenario(trace, selectors, texts, out_path)


__all__ = ["capture", "env_name", "to_trace", "write_scenario"]
