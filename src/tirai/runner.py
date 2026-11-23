"""Execute a scenario through a browser driver (agent-browser or BrowserSkill).

dry-run: run every step and check expectations (no video) to find failing steps.
record:  same flow, one MP4 per contiguous tab block, plus timeline.json for `tirai compose`.
"""

import json
import os
import time
from pathlib import Path
from urllib.parse import urlsplit

from tirai import db as dbq
from tirai import targets as tg
from tirai.agentbrowser import make_driver
from tirai.bsk import DriverError
from tirai.desktop import MixedDriver, is_desktop
from tirai.resources import annotate_js
from tirai.scenario import ScenarioError, interpolate, render, step_writes
from tirai.system import primary_modifier

DBX_DEFAULTS = {
    "new_query": "New Query",  # button text that opens a SQL editor
    "editor": ".cm-content",
    "password": "input[type=password]",
    "run_key": None,  # default: Meta+Enter on macOS, Ctrl+Enter elsewhere
    "error": ".cm-statement-execution-badge--error",  # DBX marks a failed statement in the editor
}


DBX_NO_CONNECTION = "Select connection"
# The editor toolbar's connection picker: the popover trigger showing a connection name or the placeholder.
DBX_CONN_TRIGGER = (
    "(()=>{const n=new Set([...document.querySelectorAll('.tree-connection-label')].map(e=>e.innerText.trim()));"
    "return [...document.querySelectorAll('button[data-slot=popover-trigger]')]"
    f".find(b=>{{const x=b.innerText.trim();return x==={json.dumps(DBX_NO_CONNECTION)}||n.has(x)}})}})()"
)


def js(v):
    return json.dumps(v, ensure_ascii=False)


def _origin(url):
    u = urlsplit(url)
    return f"{u.scheme}://{u.netloc}"


def _matches(step_id, ref):
    """`ref` names this step, or the family of steps expanded from it (`LINES` -> `LINES-1`, `LINES-2`)."""
    return bool(ref) and (step_id == ref or str(step_id).startswith(f"{ref}-"))


def _listify(v):
    return [] if v is None else v if isinstance(v, list) else [v]


SCROLL_IF_NEEDED = (
    "(()=>{{const e=document.querySelector({sel});if(!e)return false;const r=e.getBoundingClientRect();"
    "if(r.top>=0&&r.left>=0&&r.bottom<=innerHeight&&r.right<=innerWidth)return false;"
    "e.scrollIntoView({{block:'center',inline:'center'}});return true}})()"
)
_BUFFER = "try{performance.setResourceTimingBufferSize(10000)}catch(e){}"
STEP_MARK = "(()=>{" + _BUFFER + "return performance.timeOrigin+performance.now()})()"
FAILED_REQUESTS = (
    "(()=>{{const m={mark};return [...performance.getEntriesByType('navigation'),"
    "...performance.getEntriesByType('resource')]"
    ".filter(e=>e.responseStatus>=400&&performance.timeOrigin+e.startTime>=m-50)"
    ".map(e=>e.responseStatus+' '+e.name)}})()"
)
IDLE_PROBE = "[document.readyState,performance.getEntriesByType('resource').length]"


def _privacy_summary(cfg):
    """What the OCR pass needs from `privacy:` (rules, patterns, keep, mode); selectors stay out."""
    return {k: cfg[k] for k in ("mask", "patterns", "keep", "ocr") if cfg.get(k) is not None}


class Runner:
    def __init__(
        self,
        scenario,
        out,
        session=None,
        record=False,
        hold=0.3,
        stop_on_fail=False,
        scope="tirai",
        driver=None,
        allow_writes=True,
        until=None,
        from_step=None,
        keep_session=False,
        fresh=False,
        resume_vars=None,
    ):
        self.sc = scenario
        self.allow_writes = allow_writes
        self.until = until
        self.from_step = from_step
        self.keep_session = keep_session
        self.fresh = fresh
        self.stopped = None
        self.wrote = []
        self.cleanup_results = []
        self.seen_tabs = set()
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
        self.vars = dict(resume_vars or {})
        self.targets = scenario.get("_targets") or tg.normalize(scenario.get("targets"))
        self.warnings = []
        self.inspect = False
        self.inspected = []
        self.segments = []
        self.seg = None
        settings = scenario.get("settings") or {}
        self.timing = float(os.environ.get("TIRAI_TIMING_SCALE") or settings.get("timing_scale", 1.0))
        self.expect_timeout = float(os.environ.get("TIRAI_EXPECT_TIMEOUT") or settings.get("expect_timeout", 6))
        self.settings = settings

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
        resume = self.from_step and self.b.session and hasattr(self.b, "tab_list")
        existing = self.b.tab_list() if resume else []
        cleared = False
        for name, cfg in self.sc["tabs"].items():
            if cfg.get("popup"):
                continue  # adopted from the browser when a step first uses it
            if "app" in cfg:
                self.tabs[name] = self.b.desk.launch(name, {**cfg, "app": interpolate(cfg["app"])})
                self.pause(1.0)
                for action in cfg.get("setup", []):
                    self.do_action(name, action)
                continue
            url = interpolate(cfg["url"])
            if resume:
                # --from-step: continue on the page the earlier run left open (state, login) instead of a new tab.
                taken = set(self.tabs.values())
                hits = [t["id"] for t in existing if t["url"].startswith(_origin(url)) and t["id"] not in taken]
                if hits:
                    self.tabs[name] = hits[-1]
                    self.prepare_tab(name)
                    continue
            self.provision_dbx(cfg)
            if not self.b.session:
                self.tabs[name] = self.b.open_session(url, self.scope)
            else:
                self.tabs[name] = self.b.tab_create(url)
            self.pause(1.5)
            self.b.sync(self.tabs[name])
            self.check_loaded(name, url)
            if self.fresh and hasattr(self.b, "clear_state"):
                # Cookies are per browser session: clear them once, before any tab's setup logs in.
                self.b.clear_state(self.tabs[name], cookies=not cleared)
                cleared = True
                self.b.navigate(self.tabs[name], url)
                self.pause(1.0)
            self.prepare_tab(name)
            for action in cfg.get("setup", []):
                self.do_action(name, action)
        if hasattr(self.b, "tab_list"):
            try:
                self.seen_tabs = {t["id"] for t in self.b.tab_list()}
            except DriverError:
                self.seen_tabs = set()

    def prepare_tab(self, name):
        vp = self.settings.get("viewport")
        if vp and hasattr(self.b, "set_viewport") and not is_desktop(self.tabs[name]):
            self.b.set_viewport(self.tabs[name], vp["width"], vp["height"])

    def bind_popup(self, name):
        """Point a `popup: true` tab at the browser tab the page opened (window.open / target=_blank)."""
        if not hasattr(self.b, "tab_list"):
            raise ScenarioError(f"tab {name}: popup tabs need a driver that lists tabs")
        match = self.sc["tabs"][name].get("match")
        deadline = time.time() + self.expect_timeout
        while True:
            tabs = self.b.tab_list()
            current = self.tabs.get(name)
            if current is not None and any(t["id"] == current for t in tabs):
                return
            others = {v for k, v in self.tabs.items() if k != name}
            new = [t for t in tabs if t["id"] not in others and t["id"] not in self.seen_tabs or t["id"] == current]
            new = [t for t in new if not match or match in t["url"]]
            if new:
                self.tabs[name] = new[-1]["id"]
                self.seen_tabs.add(new[-1]["id"])
                self.prepare_tab(name)
                return
            if time.time() > deadline:
                where = f" with URL containing {match!r}" if match else ""
                raise ScenarioError(f"tab {name}: no new browser tab{where} opened (popup)")
            self.pause(0.5)

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
        if self.sc["tabs"][tab].get("popup"):
            self.bind_popup(tab)
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
            if isinstance(arg, dict) and arg.get("idle"):
                self.wait_idle(tab, float(arg.get("timeout", 15000)) / 1000)
            elif isinstance(arg, dict):
                self.b.wait_for(tid, arg["selector"], timeout=f"{float(arg.get('timeout', 10000)) / 1000:g}s")
            else:
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
        elif kind == "eval":
            # Page-side setup the vocabulary has no action for (cookies, localStorage, feature flags).
            if self.b.evaluate(tid, interpolate(arg)) is False:
                raise ScenarioError(f"eval returned false: {arg[:80]}")
            self.apply_privacy(tab)
            self.pause(0.5)
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
        # `pattern` is a JavaScript RegExp, like text_matches, so it runs in the page.
        expr = (
            f"(()=>{{const e=document.querySelector({js(arg['selector'])});if(!e)return null;"
            f"const v=String({read}??'').trim();const p={js(arg.get('pattern'))};if(!p)return {{v}};"
            f"let r;try{{r=new RegExp(p,{js(arg.get('flags', ''))})}}catch(x){{return {{err:x.message}}}}"
            "const m=r.exec(v);return m?{v:m.length>1?m[1]:m[0]}:{miss:v.slice(0,80)}})()"
        )
        deadline = time.time() + self.expect_timeout
        while not isinstance(res := self.page(tab, expr), dict) and time.time() < deadline:
            self.pause(0.5)
        if not isinstance(res, dict):
            raise ScenarioError(f"save {arg['name']}: {arg['selector']} not found")
        if "err" in res:
            raise ScenarioError(f"save {arg['name']}: invalid pattern {arg['pattern']!r}: {res['err']}")
        if "miss" in res:
            raise ScenarioError(f"save {arg['name']}: pattern {arg['pattern']!r} not in {res['miss']!r}")
        value = res["v"]
        self.vars[arg["name"]] = value
        self.saved[arg["name"]] = value

    @property
    def camera(self):
        return (self.sc.get("settings") or {}).get("camera")

    @property
    def camera_factor(self):
        return float((self.sc.get("settings") or {}).get("camera_factor", 1.6))

    def page(self, tab, expr):
        """Evaluate a page script with `targets:` (re)tagged first."""
        return self.b.evaluate(self.tabs[tab], tg.with_tags(self.targets, expr))

    def retarget(self, tab, names):
        """Tag the targets an action uses, waiting for them like an expectation; fail with what each locator matched."""
        if not names or is_desktop(self.tabs[tab]):
            return
        deadline = time.time() + self.expect_timeout
        while True:
            report = self.b.evaluate(self.tabs[tab], tg.tag_expr(self.targets)) or {}
            if all((report.get(n) or {}).get("ok") for n in names) or time.time() > deadline:
                break
            self.pause(0.5)
        for n in sorted(names):
            info = report.get(n)
            if not (info or {}).get("ok"):
                hint = self.nearby(tab, " ".join(self.targets[n]["locators"]))
                raise ScenarioError(tg.describe_failure(n, info) + hint)
            warn = tg.healed(n, self.targets[n], info)
            if warn and warn not in self.warnings:
                self.warnings.append(warn)
                print(f"     warning: {warn}")

    def nearby(self, tab, selector):
        """'; nearby: …' suggestions for a selector/locator that matched nothing."""
        try:
            hits = self.b.evaluate(self.tabs[tab], tg.script() + f";window.__tiraiT.near({js(selector)})")
        except DriverError:
            return ""
        hits = [h for h in hits if isinstance(h, str)] if isinstance(hits, list) else []
        return f"; nearby: {', '.join(hits)}" if hits else ""

    def tracked_action(self, tab, action, rec, follow):
        """Run an action; when recording, note where it happened (camera follow) and long waits (fast-forward)."""
        ((kind, arg),) = action.items()
        self.retarget(tab, tg.used_in(action))
        target = arg.get("selector") if isinstance(arg, dict) else arg
        if (
            kind in ("fill", "click", "select", "hover", "upload", "press")
            and isinstance(target, str)
            and self.settings.get("auto_scroll", True)
            and not is_desktop(self.tabs[tab])
        ):
            try:
                if self.page(tab, SCROLL_IF_NEEDED.format(sel=js(target))):
                    self.pause(0.4)
            except DriverError:
                pass
        t0 = self.now()
        if t0 is not None and follow:
            target = arg.get("selector") if isinstance(arg, dict) else arg
            if kind in ("fill", "click", "select", "hover", "scroll", "upload", "press") and isinstance(target, str):
                rect = self.target_rect(tab, target)
                if rect:
                    rec.setdefault("camera", []).append({"t": t0, "rect": rect[:4], "viewport": rect[4:]})
        try:
            self.do_action(tab, action)
        except DriverError as e:
            target = arg.get("selector") if isinstance(arg, dict) else arg
            if (
                kind in ("fill", "click", "select", "hover", "scroll", "upload", "press", "wait_for")
                and isinstance(target, str)
                and not tg.used_in(target)
                and not is_desktop(self.tabs[tab])
            ):
                raise DriverError(f"{e}{self.nearby(tab, target)}") from None
            raise
        speed = float((self.sc.get("settings") or {}).get("fast_forward", 4))
        if t0 is not None and kind in ("wait", "wait_for") and speed > 1 and (t1 := self.now()) - t0 >= 1.5:
            rec.setdefault("idle", []).append([round(t0 + 0.3, 3), round(t1 - 0.2, 3), speed])

    def wait_idle(self, tab, timeout):
        """Wait until the document is loaded and no new requests started for 1 s (SPA settled)."""
        deadline = time.time() + timeout
        last, since = None, time.time()
        while time.time() < deadline:
            state = self.page(tab, IDLE_PROBE)
            if state != last:
                last, since = state, time.time()
            elif isinstance(state, list) and state[0] == "complete" and time.time() - since >= 1.0:
                return
            self.pause(0.25)
        msg = f"wait_for idle: page still loading after {timeout:g}s; continuing"
        self.warnings.append(msg)
        print(f"     warning: {msg}")

    def target_rect(self, tab, selector):
        if is_desktop(self.tabs[tab]):
            try:
                return self.b.desk.rect(self.tabs[tab], selector)
            except DriverError:
                return None
        try:
            return self.page(
                tab,
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
            else self.page(
                tab,
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
            self.dbx_select_connection(tab, cfg)
            self.dbx_editor_ready.add(tab)
        self.b.fill(tid, cfg["editor"], sql)
        self.pause(0.6)
        self.b.press(tid, cfg["run_key"], cfg["editor"])
        self.pause(2.0)
        if cfg["error"] and self.b.evaluate(tid, f"!!document.querySelector({js(cfg['error'])})"):
            raise ScenarioError(f"sql failed in DBX: {sql[:80]}")

    def dbx_select_connection(self, tab, cfg):
        """Point the query editor at `dbx.connection` (default: `dbx.connect.name`); fail clearly when none is set."""
        tid = self.tabs[tab]
        want = cfg.get("connection") or (cfg.get("connect") or {}).get("name")
        want = interpolate(want) if want else None
        current = self.b.evaluate(tid, f"(()=>{{const t={DBX_CONN_TRIGGER};return t?t.innerText.trim():null}})()")
        if current is None or current == want or (not want and current != DBX_NO_CONNECTION):
            return
        if not want:
            raise ScenarioError(
                f"DBX query editor has no connection selected; set tabs.{tab}.dbx.connection to a DBX connection name"
            )
        self.b.evaluate(tid, f"{DBX_CONN_TRIGGER}.click()")
        self.pause(0.5)
        picked = self.b.evaluate(
            tid,
            "(()=>{const p=document.querySelector('[data-slot=popover-content]');"
            f"const o=p&&[...p.querySelectorAll('button')].find(b=>b.innerText.trim()==={js(want)});"
            "if(!o){document.activeElement&&document.activeElement.dispatchEvent("
            "new KeyboardEvent('keydown',{key:'Escape',bubbles:true}));return false}o.click();return true})()",
        )
        if not picked:
            raise ScenarioError(f"DBX connection not found: {want}")
        self.pause(1.0)

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
                f"let r;try{{r=new RegExp({js(arg['pattern'])},{js(arg.get('flags', ''))})}}"
                "catch(x){return [false,'invalid pattern: '+x.message]}"
                "return [r.test(t),t.slice(0,160)]})()"
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
            ok, actual = self.page(tab, expr)
            if ok or time.time() > deadline:
                break
            self.pause(0.5)
        if not ok and actual == "not found":
            names = tg.used_in(arg)
            if names:
                report = self.b.evaluate(tid, tg.tag_expr(self.targets)) or {}
                actual = "; ".join(tg.describe_failure(n, report.get(n)) for n in sorted(names))
            else:
                sel = arg if isinstance(arg, str) else arg.get("selector", "")
                actual += self.nearby(tab, sel)
        return {"type": kind, "expected": arg, "actual": actual, "ok": bool(ok)}

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
        want = arg["rows"]
        cols = arg.get("columns") or (list(want[0]) if want and isinstance(want[0], dict) else None)
        got = [dict(zip(cols, r, strict=False)) if cols else list(r) for r in rows]
        for name, col in (arg.get("save") or {}).items():
            if not got:
                raise ScenarioError(f"db save {name}: the query returned no rows")
            if not cols or col not in got[0]:
                raise ScenarioError(f"db save {name}: no column {col!r} (columns: {cols}); save maps variable: column")
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
        self.page(tab, annotate_js() + f";__ann.mask({js(cfg)})")

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
        return self.page(tab, expr) if items else self.b.evaluate(self.tabs[tab], expr)

    # ---------- main loop ----------
    def run(self):
        self.own_session = not self.b.session
        if self.own_session and hasattr(self.b, "init_scripts") and (init := self.privacy_init_script()):
            self.b.init_scripts.append(init)
        if self.own_session and hasattr(self.b, "init_scripts") and self.targets:
            self.b.init_scripts.insert(0, tg.init_script(self.targets))  # before privacy: masks may use @targets
        try:
            return self.run_steps()
        finally:
            try:
                self.run_cleanup()
            except Exception as e:  # noqa: BLE001 - report, but keep the run's own result/error
                print(f"[cleanup] ERROR: {e}")
            # Always release the browser (and its daemon), also after an error or Ctrl+C.
            if self.own_session and self.keep_session and self.b.session:
                print(f"session kept: {self.b.session} (continue with --session {self.b.session} --from-step <id>)")
            elif self.own_session:
                try:
                    self.b.close_session()
                except Exception:  # noqa: BLE001 - best effort; the original error matters more
                    pass

    def run_cleanup(self):
        """`cleanup:` steps after the run (not recorded); skipped when the dry-run stopped before any write."""
        steps = self.sc.get("cleanup") or []
        if not steps or not self.tabs:
            return
        declared = any(step_writes(st) for st in self.sc["steps"])
        if declared and not self.wrote:
            return
        self.close_segment()
        self.record = False
        for st in steps:
            st = render(st, self.vars)
            rec = {"id": st.get("id", "cleanup"), "tab": st["tab"], "checks": []}
            try:
                self.ensure_segment(st["tab"])
                for action in st.get("actions") or []:
                    self.tracked_action(st["tab"], render(action, self.vars, strict=True), rec, False)
                for exp in st.get("expect") or []:
                    rec["checks"].append(self.check(st["tab"], render(exp, self.vars, strict=True)))
                rec["status"] = "passed" if all(c["ok"] for c in rec["checks"]) else "failed"
            except (DriverError, ScenarioError, KeyError, ValueError, RuntimeError) as e:
                rec["status"], rec["error"] = "error", str(e)
            self.cleanup_results.append(rec)
            print(f"[cleanup {rec['id']}] {rec['status'].upper()}" + (f": {rec['error']}" if rec.get("error") else ""))

    def diag_start(self, tab):
        """Remember where the console and the page's request log stand when the step starts."""
        if is_desktop(self.tabs[tab]):
            return None
        try:
            return {"console": self.console_cursor(tab), "mark": self.b.evaluate(self.tabs[tab], STEP_MARK)}
        except DriverError:
            return None

    def diag_end(self, tab, mark, rec):
        """Failed requests (4xx/5xx) and console errors raised during the step, reported even when it passes."""
        if not mark:
            return
        ignore = ["favicon", *(self.settings.get("ignore_requests") or [])]
        try:
            reqs = self.b.evaluate(self.tabs[tab], FAILED_REQUESTS.format(mark=js(mark["mark"]))) or []
            reqs = [r for r in reqs if isinstance(r, str) and not any(i in r for i in ignore)]
        except DriverError:
            reqs = []
        try:
            data = self.b.console(self.tabs[tab], mark["console"])
            errs = [
                e.get("text", "")[:200]
                for e in data.get("entries", [])
                if e.get("level") == "error" or e.get("kind") == "exception"
            ]
        except DriverError:
            errs = []
        if reqs:
            rec["failed_requests"] = list(dict.fromkeys(reqs))[:20]
            print("     network: " + "; ".join(rec["failed_requests"][:5]))
            if self.settings.get("strict_network"):
                rec["checks"].append(
                    {"type": "network", "expected": "no 4xx/5xx", "actual": rec["failed_requests"], "ok": False}
                )
        if errs:
            rec["console_errors"] = list(dict.fromkeys(errs))[:20]
            print("     console: " + "; ".join(rec["console_errors"][:3]))

    def planned(self):
        steps = self.sc["steps"]
        if self.from_step:
            idx = next((i for i, st in enumerate(steps) if _matches(st["id"], self.from_step)), None)
            if idx is None:
                raise ScenarioError(f"--from-step {self.from_step}: no such step")
            steps = steps[idx:]
        return steps

    def run_steps(self):
        steps = self.planned()
        self.open_tabs()
        results = []
        for i, step in enumerate(steps):
            self.saved = {}
            self.warnings = []
            why = step_writes(step)
            if why and not self.allow_writes:
                self.stopped = {"before": step["id"], "reason": f"writes data ({why})"}
                print(f"[{step['id']}] not run: {self.stopped['reason']}; pass --allow-writes to run it in a dry-run")
                break
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
            if why:
                rec["writes"] = why
                self.wrote.append(step["id"])
            try:
                self.annotate(tab, [])
                inline = [e for a in step.get("actions", []) for e in _listify(a.get("expect"))]
                if any("no_console_errors" in e for e in [*step.get("expect", []), *inline]):
                    self.console_since[tab] = self.console_cursor(tab)
                mark = self.diag_start(tab)
                self.apply_privacy(tab)
                follow = step.get("zoom") == "follow" or (not step.get("zoom") and self.camera == "follow")
                halted = False
                for action in step.get("actions", []):
                    if "expect" in action:
                        # A check between actions, e.g. before a tab switch unmounts what it looks at.
                        for exp in _listify(action["expect"]):
                            rec["checks"].append(self.check(tab, render(exp, self.vars, strict=True)))
                        if not all(c["ok"] for c in rec["checks"]):
                            halted = True
                            break
                        continue
                    self.tracked_action(tab, render(action, self.vars, strict=True), rec, follow)
                    self.apply_privacy(tab)
                if not halted:
                    for x in _listify(step.get("save")):
                        self.save(tab, render(x, self.vars, strict=True))
                    for exp in step.get("expect", []):
                        rec["checks"].append(self.check(tab, render(exp, self.vars, strict=True)))
                self.diag_end(tab, mark, rec)
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
            if self.warnings:
                rec["warnings"] = list(self.warnings)
            if self.inspect and not is_desktop(self.tabs[tab]):
                try:
                    url = self.b.evaluate(self.tabs[tab], "location.href")
                    els = self.page(tab, tg.script() + ";window.__tiraiT.elements()")
                    self.inspected.append({"step": step["id"], "title": step["title"], "url": url, "elements": els})
                except DriverError as e:
                    print(f"     inspect failed: {e}")
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
            if _matches(step["id"], self.until) and not (
                i + 1 < len(steps) and _matches(steps[i + 1]["id"], self.until)
            ):
                self.stopped = {"after": step["id"], "reason": "--until"}
                break
        self.close_segment()
        return results


def previous_vars(out_dir):
    """Values saved by an earlier run into the same folder (for --from-step)."""
    f = Path(out_dir) / "timeline.json"
    if not f.is_file():
        return {}
    try:
        tl = json.loads(f.read_text(encoding="utf-8"))
    except ValueError:
        return {}
    return {k: v for st in tl.get("steps", []) for k, v in (st.get("saved") or {}).items()}


def run(
    scenario,
    out_dir,
    record,
    session=None,
    scope="tirai",
    hold=None,
    driver=None,
    allow_writes=None,
    until=None,
    from_step=None,
    keep_session=False,
    fresh=False,
):
    """Run `scenario` and write timeline.json into `out_dir`; returns the timeline dict.

    A dry-run stops before the first step that writes data unless `allow_writes`; a recording always runs it.
    """
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    settings = scenario.get("settings") or {}
    hold = hold if hold is not None else float(settings.get("hold", 2.5) if record else 0.3)
    r = Runner(
        scenario,
        out,
        session,
        record,
        hold,
        stop_on_fail=record,
        scope=scope,
        driver=driver,
        allow_writes=record or bool(allow_writes),
        until=until,
        from_step=from_step,
        keep_session=keep_session,
        fresh=fresh,
        resume_vars=previous_vars(out) if from_step else None,
    )
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
        "total_steps": len(r.planned()),
        **({"stopped": r.stopped} if r.stopped else {}),
        **({"from_step": from_step} if from_step else {}),
        **({"cleanup": r.cleanup_results} if r.cleanup_results else {}),
        "hold": hold,
        **({"trim_still": True} if settings.get("trim_still") else {}),
    }
    (out / "timeline.json").write_text(json.dumps(timeline, ensure_ascii=False, indent=2), encoding="utf-8")
    return timeline
