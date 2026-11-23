"""Execute a scenario through a browser driver (agent-browser or BrowserSkill).

dry-run: run every step and check expectations (no video) to find failing steps.
record:  same flow, one MP4 per contiguous tab block, plus timeline.json for `tirai compose`.
"""

import json
import os
import re
import time
from pathlib import Path
from urllib.parse import urlsplit

from tirai import db as dbq
from tirai.agentbrowser import make_driver
from tirai.bsk import DriverError
from tirai.desktop import MixedDriver, is_desktop
from tirai.resources import annotate_js
from tirai.scenario import ScenarioError, interpolate, render
from tirai.system import primary_modifier

DBX_DEFAULTS = {
    "new_query": "New Query",  # button text that opens a SQL editor
    "editor": ".cm-content",
    "password": "input[type=password]",
    "run_key": None,  # default: Meta+Enter on macOS, Ctrl+Enter elsewhere
    "error": ".cm-statement-execution-badge--error",  # DBX marks a failed statement in the editor
}


def js(v):
    return json.dumps(v, ensure_ascii=False)


def _origin(url):
    u = urlsplit(url)
    return f"{u.scheme}://{u.netloc}"


def _privacy_summary(cfg):
    """What the OCR pass needs from `privacy:` (rules, patterns, keep, mode); selectors stay out."""
    return {k: cfg[k] for k in ("mask", "patterns", "keep", "ocr") if cfg.get(k) is not None}


class Runner:
    def __init__(
        self, scenario, out, session=None, record=False, hold=0.3, stop_on_fail=False, scope="tirai", driver=None
    ):
        self.sc = scenario
        self.out = out
        self.scope = scope
        if any("app" in (cfg or {}) for cfg in scenario["tabs"].values()):
            self.b = MixedDriver(lambda: make_driver(driver or scenario.get("driver"), session))
        else:
            self.b = make_driver(driver or scenario.get("driver"), session)
        self.record = record
        self.hold = hold
        self.stop_on_fail = stop_on_fail
        self.tabs = {}
        self.dbx_editor_ready = set()
        self.console_since = {}
        self.vars = {}
        self.segments = []
        self.seg = None
        settings = scenario.get("settings") or {}
        self.timing = float(os.environ.get("TIRAI_TIMING_SCALE") or settings.get("timing_scale", 1.0))
        self.expect_timeout = float(os.environ.get("TIRAI_EXPECT_TIMEOUT") or settings.get("expect_timeout", 6))

    def pause(self, seconds):
        """Settle delay after UI actions; scale with TIRAI_TIMING_SCALE / settings.timing_scale on slow machines."""
        time.sleep(seconds * self.timing)

    def dbx(self, tab):
        cfg = {**DBX_DEFAULTS, **(self.sc["tabs"][tab].get("dbx") or {})}
        cfg["run_key"] = cfg["run_key"] or f"{primary_modifier()}+Enter"
        return cfg

    # ---------- tabs / setup ----------
    def provision_dbx(self, cfg):
        """`dbx.connect`: create/update the DBX connection from the scenario's database DSN before the tab opens."""
        conn = (cfg.get("dbx") or {}).get("connect")
        if not conn:
            return
        from tirai.dbxconn import DbxError, connect

        url = interpolate(cfg["url"])
        dsn = interpolate(self.sc["databases"][conn.get("database", "default")]["dsn"])
        password = os.environ.get(conn.get("password_env", "DBX_PASSWORD"))
        try:
            connect(_origin(url) + "/", dsn, interpolate(conn["name"]), password, conn.get("host"))
        except DbxError as e:
            raise RuntimeError(f"dbx.connect {conn['name']}: {e}") from None

    def open_tabs(self):
        for name, cfg in self.sc["tabs"].items():
            if "app" in cfg:
                self.tabs[name] = self.b.desk.launch(name, {**cfg, "app": interpolate(cfg["app"])})
                self.pause(1.0)
                for action in cfg.get("setup", []):
                    self.do_action(name, action)
                continue
            self.provision_dbx(cfg)
            if not self.b.session:
                self.tabs[name] = self.b.open_session(interpolate(cfg["url"]), self.scope)
            else:
                self.tabs[name] = self.b.tab_create(interpolate(cfg["url"]))
            self.pause(1.5)
            self.b.sync(self.tabs[name])
            self.check_loaded(name, interpolate(cfg["url"]))
            for action in cfg.get("setup", []):
                self.do_action(name, action)

    def check_loaded(self, name, url):
        """Fail fast when a tab shows the browser's own error page (server down, wrong port)."""
        try:
            href = self.b.evaluate(self.tabs[name], "location.href") or ""
        except DriverError:
            return
        if isinstance(href, str) and href.startswith(("chrome-error:", "about:neterror")):
            raise RuntimeError(f"tab {name}: {url} did not load (is the server running?)")

    # ---------- recording ----------
    def ensure_segment(self, tab):
        if self.seg and self.seg["tab"] == tab:
            return
        self.close_segment()
        self.b.tab_select(self.tabs[tab])
        self.pause(0.8)
        if not self.record:
            self.seg = {"tab": tab}
            return
        idx = len(self.segments) + 1
        rid = self.b.video_start(self.tabs[tab])
        self.seg = {"tab": tab, "recording": rid, "t0": time.monotonic(), "file": f"seg-{idx:02d}-{tab}.mp4"}
        self.pause(1.0)

    def close_segment(self):
        if not self.seg:
            return
        if self.record:
            self.pause(0.6)
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
            self.apply_privacy(tab)
            self.pause(1.0)
        elif kind == "fill":
            self.b.fill(tid, arg["selector"], interpolate(arg["value"]))
        elif kind == "click":
            self.b.click(tid, arg)
            self.apply_privacy(tab)
            self.pause(1.0)
        elif kind == "press":
            arg = {"key": arg} if isinstance(arg, str) else arg
            self.b.press(tid, arg["key"], arg.get("selector"))
            self.pause(0.5)
        elif kind == "wait":
            time.sleep(float(arg) / 1000)
        elif kind == "wait_for":
            self.b.wait_for(tid, arg)
        elif kind == "dbx_login":
            pw = self.dbx(tab)["password"]
            if self.b.evaluate(tid, f"!!document.querySelector({js(pw)})"):
                self.b.fill(tid, pw, interpolate(arg))
                self.b.press(tid, "Enter", pw)
                self.pause(2.0)
        elif kind == "sql":
            self.dbx_sql(tab, interpolate(arg))
        elif kind == "select":
            self.b.select(tid, arg["selector"], interpolate(arg["value"]))
            self.pause(0.5)
        elif kind == "hover":
            self.b.hover(tid, arg)
            self.pause(0.5)
        elif kind == "scroll":
            self.b.scroll_to(tid, arg)
            self.pause(0.6)
        elif kind == "upload":
            files = arg["file"] if isinstance(arg["file"], list) else [arg["file"]]
            base = Path(self.sc.get("_dir", "."))
            paths = [str((base / interpolate(f)).resolve()) for f in files]
            missing = [f for f in paths if not Path(f).is_file()]
            if missing:
                raise ScenarioError(f"upload file not found: {', '.join(missing)}")
            self.b.upload(tid, arg["selector"], paths)
            self.pause(1.0)
        elif kind == "save":
            self.save(tab, arg)
        elif kind == "dialog":
            # Pre-answer native dialogs for the rest of this page (bsk blocks on a real one).
            ok = "true" if arg == "accept" else "false"
            self.b.evaluate(
                tid,
                f"(()=>{{window.alert=()=>{{}};window.confirm=()=>{ok};"
                f"window.prompt=(m,d)=>{ok}?(d??''):null;return true}})()",
            )
        else:
            raise ValueError(f"unknown action {kind}")

    def save(self, tab, arg):
        """Store text/value/attribute of an element as `{{name}}` for later steps."""
        attr = arg.get("attribute")
        read = f"e.getAttribute({js(attr)})" if attr else "(e.matches('input,textarea,select')?e.value:e.innerText)"
        expr = f"(()=>{{const e=document.querySelector({js(arg['selector'])});return e?{read}:null}})()"
        deadline = time.time() + self.expect_timeout
        while (value := self.b.evaluate(self.tabs[tab], expr)) is None and time.time() < deadline:
            self.pause(0.5)
        if value is None:
            raise ScenarioError(f"save {arg['name']}: {arg['selector']} not found")
        value = str(value).strip()
        if arg.get("pattern"):
            m = re.search(arg["pattern"], value)
            if not m:
                raise ScenarioError(f"save {arg['name']}: pattern {arg['pattern']!r} not in {value[:80]!r}")
            value = m.group(1) if m.groups() else m.group(0)
        self.vars[arg["name"]] = value
        self.saved[arg["name"]] = value

    @property
    def camera(self):
        return (self.sc.get("settings") or {}).get("camera")

    @property
    def camera_factor(self):
        return float((self.sc.get("settings") or {}).get("camera_factor", 1.6))

    def tracked_action(self, tab, action, rec, follow):
        """Run an action; when recording, note where it happened (camera follow) and long waits (fast-forward)."""
        ((kind, arg),) = action.items()
        t0 = self.now()
        if t0 is not None and follow:
            target = arg.get("selector") if isinstance(arg, dict) else arg
            if kind in ("fill", "click", "select", "hover", "scroll", "upload", "press") and isinstance(target, str):
                rect = self.target_rect(tab, target)
                if rect:
                    rec.setdefault("camera", []).append({"t": t0, "rect": rect[:4], "viewport": rect[4:]})
        self.do_action(tab, action)
        speed = float((self.sc.get("settings") or {}).get("fast_forward", 4))
        if t0 is not None and kind in ("wait", "wait_for") and speed > 1 and (t1 := self.now()) - t0 >= 1.5:
            rec.setdefault("idle", []).append([round(t0 + 0.3, 3), round(t1 - 0.2, 3), speed])

    def target_rect(self, tab, selector):
        if is_desktop(self.tabs[tab]):
            try:
                return self.b.desk.rect(self.tabs[tab], selector)
            except DriverError:
                return None
        try:
            return self.b.evaluate(
                self.tabs[tab],
                f"(()=>{{const e=document.querySelector({js(selector)});if(!e)return null;"
                "const r=e.getBoundingClientRect();return [r.x,r.y,r.width,r.height,innerWidth,innerHeight]})()",
            )
        except DriverError:
            return None

    def zoom_rect(self, tab, zoom):
        """Viewport rect of the zoom target, consumed by `tirai compose` to ease in on it."""
        z = {"target": zoom} if isinstance(zoom, str) else dict(zoom)
        rect = (
            self.target_rect(tab, z["target"])
            if is_desktop(self.tabs[tab])
            else self.b.evaluate(
                self.tabs[tab],
                f"(()=>{{const e=document.querySelector({js(z['target'])});if(!e)return null;"
                "const r=e.getBoundingClientRect();return [r.x,r.y,r.width,r.height,innerWidth,innerHeight]})()",
            )
        )
        if not rect:
            raise ScenarioError(f"zoom target not found: {z['target']}")
        return {"rect": rect[:4], "viewport": rect[4:], **{k: z[k] for k in ("factor", "at") if k in z}}

    def dbx_sql(self, tab, sql):
        tid = self.tabs[tab]
        cfg = self.dbx(tab)
        if tab not in self.dbx_editor_ready:
            # Reuse an editor DBX restored from an earlier run instead of piling up new query tabs.
            opened = self.b.evaluate(
                tid,
                f"(()=>{{if(document.querySelector({js(cfg['editor'])}))return false;"
                "const b=[...document.querySelectorAll('button')]"
                f".find(b=>b.innerText.trim()==={js(cfg['new_query'])}); b&&b.click(); return !!b}})()",
            )
            if opened:
                self.pause(1.5)
            self.dbx_editor_ready.add(tab)
        self.b.fill(tid, cfg["editor"], sql)
        self.pause(0.6)
        self.b.press(tid, cfg["run_key"], cfg["editor"])
        self.pause(2.0)
        if cfg["error"] and self.b.evaluate(tid, f"!!document.querySelector({js(cfg['error'])})"):
            raise ScenarioError(f"sql failed in DBX: {sql[:80]}")

    # ---------- expectations ----------
    def check(self, tab, exp):
        ((kind, arg),) = exp.items()
        tid = self.tabs[tab]
        if kind == "db":
            return self.check_db(arg)
        if kind == "no_console_errors":
            return self.check_console(tab, arg)
        if is_desktop(tid):
            deadline = time.time() + self.expect_timeout
            while True:
                ok, actual = self.b.desk.check(tid, kind, arg)
                if ok or time.time() > deadline:
                    return {"type": kind, "expected": arg, "actual": actual, "ok": bool(ok)}
                self.pause(0.5)
        q = "document.querySelector"
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
        elif kind == "not_visible":
            expr = (
                f"(()=>{{const e={q}({js(arg)});if(!e)return [true,'not found'];"
                "const r=e.getBoundingClientRect();const s=getComputedStyle(e);"
                "const hidden=r.width===0||r.height===0||s.visibility==='hidden'||s.display==='none';"
                "return [hidden,'rect '+r.width+'x'+r.height]})()"
            )
        elif kind == "text_matches":
            sel = arg.get("selector")
            expr = (
                f"(()=>{{const e={(q + '(' + js(sel) + ')') if sel else 'document.body'};"
                f"if(!e)return [false,'not found'];const t=e.innerText.trim();"
                f"return [new RegExp({js(arg['pattern'])},{js(arg.get('flags', ''))}).test(t),t.slice(0,160)]}})()"
            )
        elif kind == "value":
            expr = (
                f"(()=>{{const e={q}({js(arg['selector'])});if(!e)return [false,'not found'];"
                f"return [String(e.value)===String({js(interpolate(arg['equals']))}),e.value]}})()"
            )
        elif kind == "attribute":
            expr = (
                f"(()=>{{const e={q}({js(arg['selector'])});if(!e)return [false,'not found'];"
                f"const v=e.getAttribute({js(arg['name'])});"
                f"return [v!==null&&String(v)===String({js(arg['equals'])}),v]}})()"
            )
        elif kind == "count":
            expr = (
                f"(()=>{{const n=document.querySelectorAll({js(arg['selector'])}).length;"
                f"return [n==={int(arg['equals'])},n]}})()"
            )
        elif kind == "request":
            status = arg.get("status")
            expr = (
                "(()=>{const es=[...performance.getEntriesByType('navigation'),"
                "...performance.getEntriesByType('resource')]"
                f".filter(e=>e.name.includes({js(interpolate(arg['url_contains']))}));"
                f"const st={js(status)};"
                "return [es.some(e=>st===null||e.responseStatus===st),"
                "es.slice(-5).map(e=>e.name+' '+e.responseStatus)]})()"
            )
        elif kind == "url_contains":
            expr = f"[location.href.includes({js(arg)}),location.href]"
        else:
            raise ValueError(f"unknown expect {kind}")
        deadline = time.time() + self.expect_timeout
        while True:
            ok, actual = self.b.evaluate(tid, expr)
            if ok or time.time() > deadline:
                return {"type": kind, "expected": arg, "actual": actual, "ok": bool(ok)}
            self.pause(0.5)

    def console_cursor(self, tab):
        try:
            return self.b.console(self.tabs[tab]).get("next_since")
        except DriverError:
            return None

    def check_console(self, tab, arg):
        ignore = (arg or {}).get("ignore", []) if isinstance(arg, dict) else []
        data = self.b.console(self.tabs[tab], self.console_since.get(tab))
        errors = [
            e.get("text", "")[:200]
            for e in data.get("entries", [])
            if (e.get("level") == "error" or e.get("kind") == "exception")
            and not any(i in e.get("text", "") for i in ignore)
        ]
        return {"type": "no_console_errors", "expected": arg or True, "actual": errors, "ok": not errors}

    def check_db(self, arg):
        db = self.sc["databases"][arg.get("database", "default")]
        rows = dbq.query(interpolate(db["dsn"]), arg["sql"])
        cols = arg.get("columns")
        got = [dict(zip(cols, r, strict=False)) if cols else list(r) for r in rows]
        want = arg["rows"]
        for name, col in (arg.get("save") or {}).items():
            if got and cols and col in got[0]:
                self.vars[name] = self.saved[name] = got[0][col]

        def norm(v):
            return json.loads(json.dumps(v, default=str))

        return {
            "type": "db",
            "expected": {"sql": arg["sql"], "rows": want},
            "actual": norm(got),
            "ok": norm(got) == want,
        }

    # ---------- annotations ----------
    def privacy_config(self):
        privacy = self.sc.get("privacy")
        if not privacy:
            return None
        cfg = {**privacy, "patterns": [interpolate(p) for p in privacy.get("patterns") or []]}
        cfg["keep"] = [interpolate(str(k)) for k in privacy.get("keep") or []]
        return cfg

    def privacy_init_script(self):
        """Page init script that masks PII before the page paints (drivers with init-script support)."""
        cfg = self.privacy_config()
        if not cfg:
            return None
        origins = sorted(
            {_origin(interpolate(t["url"])) for t in self.sc["tabs"].values() if t.get("privacy") is not False}
        )
        return (
            annotate_js() + f";(()=>{{if(!{js(origins)}.includes(location.origin))return;"
            f"const go=()=>{{try{{__ann.mask({js(cfg)})}}catch(e){{}}}};"
            "if(document.documentElement)go();"
            "document.addEventListener('DOMContentLoaded',go,{once:true})})()"
        )

    def apply_privacy(self, tab):
        """(Re)install auto PII masking in the tab; it keeps masking as the DOM changes until the next load."""
        cfg = self.privacy_config()
        if not cfg or self.sc["tabs"][tab].get("privacy") is False or is_desktop(self.tabs[tab]):
            return
        self.b.evaluate(self.tabs[tab], annotate_js() + f";__ann.mask({js(cfg)})")

    def annotate(self, tab, items):
        if is_desktop(self.tabs[tab]):
            if items:
                raise ScenarioError("annotate: is only available on browser tabs")
            return []
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
        if self.own_session and hasattr(self.b, "init_scripts") and (init := self.privacy_init_script()):
            self.b.init_scripts.append(init)
        try:
            return self.run_steps()
        finally:
            # Always release the browser (and its daemon), also after an error or Ctrl+C.
            if self.own_session:
                try:
                    self.b.close_session()
                except Exception:  # noqa: BLE001 - best effort; the original error matters more
                    pass

    def run_steps(self):
        self.open_tabs()
        results = []
        for step in self.sc["steps"]:
            self.saved = {}
            # Titles render leniently; actions/expectations render right before use so a value saved
            # earlier in the same step is available to the next action or check.
            step = {**step, **render({k: step[k] for k in ("title", "subtitle") if k in step}, self.vars)}
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
            for key in ("case", "layout", "split_with"):
                if step.get(key):
                    rec[key] = step[key]
            try:
                self.annotate(tab, [])
                if any("no_console_errors" in e for e in step.get("expect", [])):
                    self.console_since[tab] = self.console_cursor(tab)
                self.apply_privacy(tab)
                follow = step.get("zoom") == "follow" or (not step.get("zoom") and self.camera == "follow")
                for action in step.get("actions", []):
                    self.tracked_action(tab, render(action, self.vars, strict=True), rec, follow)
                    self.apply_privacy(tab)
                for exp in step.get("expect", []):
                    rec["checks"].append(self.check(tab, render(exp, self.vars, strict=True)))
                rec["status"] = "passed" if all(c["ok"] for c in rec["checks"]) else "failed"
                if follow and rec.get("camera"):
                    rec["zoom"] = {"follow": rec.pop("camera"), **({"factor": self.camera_factor})}
                elif step.get("zoom") and step["zoom"] != "follow":
                    rec["zoom"] = self.zoom_rect(tab, render(step["zoom"], self.vars, strict=True))
                if step.get("annotate"):
                    rec["annotations"] = self.annotate(tab, render(step["annotate"], self.vars, strict=True))
            except (DriverError, ScenarioError, KeyError, ValueError, RuntimeError) as e:
                rec["status"], rec["error"] = "error", str(e)
            if self.saved:
                rec["saved"] = dict(self.saved)
            time.sleep(step.get("hold", self.hold))
            shot = self.out / f"step-{step['id']}.png"
            try:
                self.b.screenshot(self.tabs[tab], str(shot))
                rec["screenshot"] = shot.name
            except DriverError:
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
        return results


def run(scenario, out_dir, record, session=None, scope="tirai", hold=None, driver=None):
    """Run `scenario` and write timeline.json into `out_dir`; returns the timeline dict."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    settings = scenario.get("settings") or {}
    hold = hold if hold is not None else float(settings.get("hold", 2.5) if record else 0.3)
    r = Runner(scenario, out, session, record, hold, stop_on_fail=record, scope=scope, driver=driver)
    steps = r.run()
    timeline = {
        "scenario": scenario["name"],
        "mode": "record" if record else "dry-run",
        **({"lang": scenario["lang"]} if scenario.get("lang") else {}),
        "created": time.strftime("%Y-%m-%d %H:%M:%S"),
        "driver": r.b.name,
        **({"privacy": _privacy_summary(r.privacy_config())} if scenario.get("privacy") else {}),
        "tabs": {k: {"label": v.get("label", k)} for k, v in scenario["tabs"].items()},
        "segments": r.segments,
        "steps": steps,
        "total_steps": len(scenario["steps"]),
    }
    (out / "timeline.json").write_text(json.dumps(timeline, ensure_ascii=False, indent=2), encoding="utf-8")
    return timeline
