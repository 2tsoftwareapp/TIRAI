"""Execute a scenario through BrowserSkill.

dry-run: run every step and check expectations (no video) to find failing steps.
record:  same flow, one MP4 per contiguous tab block, plus timeline.json for `tirai compose`.
"""

import json
import time
from pathlib import Path

from tirai import db as dbq
from tirai.bsk import Bsk, BskError
from tirai.resources import annotate_js
from tirai.scenario import ScenarioError, interpolate


def js(v):
    return json.dumps(v, ensure_ascii=False)


class Runner:
    def __init__(self, scenario, out, session=None, record=False, hold=0.3, stop_on_fail=False, scope="tirai"):
        self.sc = scenario
        self.out = out
        self.scope = scope
        self.b = Bsk(session)
        self.record = record
        self.hold = hold
        self.stop_on_fail = stop_on_fail
        self.tabs = {}
        self.dbx_editor_ready = set()
        self.segments = []
        self.seg = None

    # ---------- tabs / setup ----------
    def open_tabs(self):
        for i, (name, cfg) in enumerate(self.sc["tabs"].items()):
            if i == 0 and not self.b.session:
                self.tabs[name] = self.b.open_session(interpolate(cfg["url"]), self.scope)
            else:
                self.tabs[name] = self.b.tab_create(interpolate(cfg["url"]))
            time.sleep(1.5)
            self.b.sync(self.tabs[name])
            for action in cfg.get("setup", []):
                self.do_action(name, action)

    # ---------- recording ----------
    def ensure_segment(self, tab):
        if self.seg and self.seg["tab"] == tab:
            return
        self.close_segment()
        self.b.tab_select(self.tabs[tab])
        time.sleep(0.8)
        if not self.record:
            self.seg = {"tab": tab}
            return
        idx = len(self.segments) + 1
        rid = self.b.video_start(self.tabs[tab])
        self.seg = {"tab": tab, "recording": rid, "t0": time.monotonic(), "file": f"seg-{idx:02d}-{tab}.mp4"}
        time.sleep(1.0)

    def close_segment(self):
        if not self.seg:
            return
        if self.record:
            time.sleep(0.6)
            self.seg["duration"] = round(time.monotonic() - self.seg["t0"], 3)
            self.b.video_stop(self.seg["recording"], str(self.out / self.seg["file"]))
            self.segments.append({k: self.seg[k] for k in ("tab", "file", "duration")})
        self.seg = None

    def now(self):
        return round(time.monotonic() - self.seg["t0"], 3) if self.record else None

    # ---------- actions ----------
    def do_action(self, tab, action):
        ((kind, arg),) = action.items()
        tid = self.tabs[tab]
        if kind == "navigate":
            self.b.navigate(tid, interpolate(arg))
            time.sleep(1.0)
        elif kind == "fill":
            self.b.fill(tid, arg["selector"], interpolate(arg["value"]))
        elif kind == "click":
            self.b.click(tid, arg)
            time.sleep(1.0)
        elif kind == "press":
            arg = {"key": arg} if isinstance(arg, str) else arg
            self.b.press(tid, arg["key"], arg.get("selector"))
            time.sleep(0.5)
        elif kind == "wait":
            time.sleep(float(arg) / 1000)
        elif kind == "wait_for":
            self.b.wait_for(tid, arg)
        elif kind == "dbx_login":
            if self.b.evaluate(tid, "!!document.querySelector('input[type=password]')"):
                self.b.fill(tid, "input[type=password]", interpolate(arg))
                self.b.press(tid, "Enter", "input[type=password]")
                time.sleep(2.0)
        elif kind == "sql":
            self.dbx_sql(tab, interpolate(arg))
        else:
            raise ValueError(f"unknown action {kind}")

    def dbx_sql(self, tab, sql):
        tid = self.tabs[tab]
        if tab not in self.dbx_editor_ready:
            self.b.evaluate(
                tid,
                "(()=>{const b=[...document.querySelectorAll('button')]"
                ".find(b=>b.innerText.trim()==='New Query'); b&&b.click(); return !!b})()",
            )
            time.sleep(1.5)
            self.dbx_editor_ready.add(tab)
        self.b.fill(tid, ".cm-content", sql)
        time.sleep(0.6)
        self.b.press(tid, "Ctrl+Enter", ".cm-content")
        time.sleep(2.0)

    # ---------- expectations ----------
    def check(self, tab, exp):
        ((kind, arg),) = exp.items()
        tid = self.tabs[tab]
        if kind == "db":
            return self.check_db(arg)
        if kind == "visible":
            expr = (
                f"(()=>{{const e=document.querySelector({js(arg)});if(!e)return [false,'not found'];"
                "const r=e.getBoundingClientRect();return [r.width>0&&r.height>0,'rect '+r.width+'x'+r.height]})()"
            )
        elif kind == "text_contains":
            sel = arg.get("selector")
            expr = (
                f"(()=>{{const e={('document.querySelector(' + js(sel) + ')') if sel else 'document.body'};"
                f"if(!e)return [false,'not found'];const t=e.innerText.trim();"
                f"return [t.includes({js(arg['text'])}),t.slice(0,160)]}})()"
            )
        elif kind == "url_contains":
            expr = f"[location.href.includes({js(arg)}),location.href]"
        else:
            raise ValueError(f"unknown expect {kind}")
        deadline = time.time() + 6
        while True:
            ok, actual = self.b.evaluate(tid, expr)
            if ok or time.time() > deadline:
                return {"type": kind, "expected": arg, "actual": actual, "ok": bool(ok)}
            time.sleep(0.5)

    def check_db(self, arg):
        db = self.sc["databases"][arg.get("database", "default")]
        rows = dbq.query(interpolate(db["dsn"]), arg["sql"])
        cols = arg.get("columns")
        got = [dict(zip(cols, r, strict=False)) if cols else list(r) for r in rows]
        want = arg["rows"]

        def norm(v):
            return json.loads(json.dumps(v, default=str))

        return {
            "type": "db",
            "expected": {"sql": arg["sql"], "rows": want},
            "actual": norm(got),
            "ok": norm(got) == want,
        }

    # ---------- annotations ----------
    def annotate(self, tab, items):
        calls = ["__ann.clear()"]
        for item in items or []:
            ((kind, a),) = item.items()
            a = dict(a) if isinstance(a, dict) else {"target": a}
            target = a.pop("target")
            if kind == "text":
                calls.append(f"__ann.text({js(target)},{js(a.pop('label'))},{js(a)})")
            elif kind == "badge":
                calls.append(f"__ann.badge({js(target)},{js(a.pop('n'))},{js(a)})")
            else:
                calls.append(f"__ann.{kind}({js(target)},{js(a)})")
        expr = annotate_js() + ";(()=>{" + ";".join(calls) + ";return __ann.list()})()"
        return self.b.evaluate(self.tabs[tab], expr)

    # ---------- main loop ----------
    def run(self):
        self.own_session = not self.b.session
        self.open_tabs()
        results = []
        for step in self.sc["steps"]:
            tab = step["tab"]
            self.ensure_segment(tab)
            rec = {
                "id": step["id"],
                "title": step["title"],
                "subtitle": step.get("subtitle", step["title"]),
                "tab": tab,
                "segment": self.seg.get("file"),
                "start": self.now(),
                "checks": [],
            }
            print(f"[{step['id']}] {step['title']} ...", flush=True)
            try:
                self.annotate(tab, [])
                for action in step.get("actions", []):
                    self.do_action(tab, action)
                for exp in step.get("expect", []):
                    rec["checks"].append(self.check(tab, exp))
                rec["status"] = "passed" if all(c["ok"] for c in rec["checks"]) else "failed"
                if step.get("annotate"):
                    rec["annotations"] = self.annotate(tab, step["annotate"])
            except (BskError, ScenarioError, KeyError, ValueError, RuntimeError) as e:
                rec["status"], rec["error"] = "error", str(e)
            time.sleep(step.get("hold", self.hold))
            shot = self.out / f"step-{step['id']}.png"
            try:
                self.b.screenshot(self.tabs[tab], str(shot))
                rec["screenshot"] = shot.name
            except BskError:
                pass
            rec["end"] = self.now()
            results.append(rec)
            print(f"[{step['id']}] {rec['status'].upper()}" + (f": {rec.get('error')}" if rec.get("error") else ""))
            for c in rec["checks"]:
                if not c["ok"]:
                    print(f"     expect {c['type']} {c['expected']} -> actual {c['actual']!r}")
            if rec["status"] != "passed" and self.stop_on_fail:
                break
        self.close_segment()
        if self.own_session:
            self.b.close_session()
        return results


def run(scenario, out_dir, record, session=None, scope="tirai", hold=None):
    """Run `scenario` and write timeline.json into `out_dir`; returns the timeline dict."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    hold = hold if hold is not None else (2.5 if record else 0.3)
    r = Runner(scenario, out, session, record, hold, stop_on_fail=record, scope=scope)
    steps = r.run()
    timeline = {
        "scenario": scenario["name"],
        "mode": "record" if record else "dry-run",
        "created": time.strftime("%Y-%m-%d %H:%M:%S"),
        "tabs": {k: {"label": v.get("label", k)} for k, v in scenario["tabs"].items()},
        "segments": r.segments,
        "steps": steps,
        "total_steps": len(scenario["steps"]),
    }
    (out / "timeline.json").write_text(json.dumps(timeline, ensure_ascii=False, indent=2), encoding="utf-8")
    return timeline
