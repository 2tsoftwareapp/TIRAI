"""Desktop-app tabs through vercel-labs/agent-desktop (accessibility tree), recorded with ffmpeg screen capture.

A tab with `app:` instead of `url:` is a desktop app. Selectors are `role:name` (e.g. `button:Equals`), a bare
accessible name, or a mapping of agent-desktop `find` filters (`role`, `name`, `text`, `value`, `native_id`).
"""

import json
import os
import re
import shutil
import subprocess
import tempfile
import time

from tirai.bsk import DriverError
from tirai.system import HOME, IS_MAC, IS_WINDOWS, TIRAI_BIN, ffmpeg_bin, find_bin, run_text, tool_env

PREFIX = "app:"
FIND_KEYS = ("role", "name", "text", "value", "native_id", "description", "exact")


class AgentDesktopError(DriverError):
    pass


def desktop_bin():
    return find_bin("agent-desktop", "AGENT_DESKTOP_BIN", [TIRAI_BIN, HOME / ".local" / "bin"])


def is_desktop(tab):
    return isinstance(tab, str) and tab.startswith(PREFIX)


def parse_selector(sel):
    if isinstance(sel, dict):
        unknown = set(sel) - set(FIND_KEYS)
        if unknown:
            raise AgentDesktopError(f"desktop selector: unknown key(s) {', '.join(sorted(unknown))}")
        return dict(sel)
    sel = str(sel)
    role, sep, name = sel.partition(":")
    if sep and role and " " not in role:
        return {"role": role, "name": name, "exact": True} if name else {"role": role}
    return {"name": sel, "exact": True}


def first_ref(data):
    """First element ref in an agent-desktop envelope (`find` returns matches; key names vary by command)."""
    if isinstance(data, dict):
        for k in ("ref_id", "ref"):
            if isinstance(data.get(k), str) and data[k].startswith("@"):
                return data[k]
        items = data.values()
    elif isinstance(data, list):
        items = data
    else:
        return None
    for v in items:
        if (r := first_ref(v)) is not None:
            return r
    return None


def bounds_of(data):
    """(x, y, w, h) from an agent-desktop bounds/window record."""
    if isinstance(data, dict):
        b = data.get("bounds", data)
        if isinstance(b, dict) and {"x", "y"} <= set(b) and ({"width", "height"} <= set(b) or {"w", "h"} <= set(b)):
            return tuple(int(round(b[k])) for k in ("x", "y", b.get("width") is not None and "width" or "w",
                                                   b.get("height") is not None and "height" or "h"))  # fmt: skip
        for v in data.values():
            if isinstance(v, (dict, list)) and (r := bounds_of(v)):
                return r
    elif isinstance(data, list):
        for v in data:
            if r := bounds_of(v):
                return r
    return None


def capture_input(bounds=None):
    """ffmpeg input args for the screen (X11 / Windows GDI / macOS AVFoundation) and an optional crop filter."""
    fps = ["-framerate", "30"]
    if IS_WINDOWS:
        return ["-f", "gdigrab", *fps, "-draw_mouse", "1", "-i", "desktop"], bounds
    if IS_MAC:
        # Window bounds are in points and the capture in pixels on Retina, so record the whole screen.
        return ["-f", "avfoundation", *fps, "-capture_cursor", "1", "-i", "Capture screen 0:none"], None
    display = os.environ.get("DISPLAY")
    if not display:
        raise AgentDesktopError(
            "desktop recording needs an X11 display (DISPLAY is not set; Wayland-only sessions can't be captured)"
        )
    return ["-f", "x11grab", *fps, "-draw_mouse", "1", "-i", display], bounds


class AgentDesktop:
    name = "agent-desktop"

    def __init__(self, headed=None):
        env = os.environ
        self.headed = headed if headed is not None else env.get("TIRAI_HEADED", "") not in ("", "0", "false")
        self.apps = {}  # tab id -> {"app": find/launch name, "close": bool}

    def run(self, *args, timeout=60, ok_codes=None):
        exe = desktop_bin()
        if not exe:
            raise AgentDesktopError("agent-desktop not found: run `tirai setup --only agent-desktop`")
        cmd = [exe, *args] + (["--headed"] if self.headed and args[0] in ("click", "type", "press") else [])
        p = run_text(cmd, timeout=timeout, env=tool_env())
        out = (p.stdout or "").strip()
        try:
            env = json.loads(out.splitlines()[-1]) if out else {}
        except json.JSONDecodeError:
            env = {"ok": False, "error": {"message": out or p.stderr.strip()}}
        if not env.get("ok"):
            err = env.get("error") or {}
            if ok_codes and err.get("code") in ok_codes:
                return None
            msg = err.get("message") or p.stderr.strip() or out
            hint = f" ({err['suggestion']})" if err.get("suggestion") else ""
            raise AgentDesktopError(f"agent-desktop {args[0]} failed: {err.get('code', '')} {msg}{hint}".strip())
        return env.get("data") or {}

    # ---------- tabs ----------
    def launch(self, tab_name, cfg):
        app = cfg["app"]
        args = ["launch", app, "--activate"]
        for a in cfg.get("args", []):
            args.append(f"--arg={a}")
        self.run(*args, timeout=90)
        tid = PREFIX + tab_name
        self.apps[tid] = {"app": cfg.get("name", app), "launch": app, "close": cfg.get("close", True)}
        return tid

    def app(self, tab):
        return self.apps[tab]["app"]

    def close(self):
        for info in self.apps.values():
            if info["close"]:
                try:
                    self.run("close-app", info["launch"], timeout=30)
                except DriverError:
                    pass
        self.apps.clear()

    def tab_select(self, tab):
        try:
            self.run("focus-window", "--app", self.app(tab), timeout=20)
        except DriverError:
            pass  # focus is best-effort (headless semantic delivery doesn't need it)

    def sync(self, tab, retries=None):
        return {}

    # ---------- elements ----------
    def find(self, tab, selector, required=True):
        args = ["find", "--app", self.app(tab), "--first"]
        for k, v in parse_selector(selector).items():
            if k == "exact":
                args += ["--exact"] if v else []
            else:
                args += [f"--{k.replace('_', '-')}", str(v)]
        data = self.run(*args, ok_codes={"ELEMENT_NOT_FOUND", "NOT_FOUND"})
        ref = first_ref(data) if data else None
        if not ref and required:
            raise AgentDesktopError(f"desktop element not found in {self.app(tab)}: {selector}")
        return ref

    def click(self, tab, selector):
        self.run("click", self.find(tab, selector))

    def fill(self, tab, selector, value):
        ref = self.find(tab, selector)
        try:
            self.run("set-value", ref, str(value))
        except DriverError:
            self.run("clear", ref)
            self.run("type", ref, str(value))

    def press(self, tab, key, selector=None):
        if selector:
            self.run("focus", self.find(tab, selector))
        self.run("press", key.lower(), "--app", self.app(tab))

    def select(self, tab, selector, values):
        values = values if isinstance(values, list) else [values]
        self.run("select", self.find(tab, selector), str(values[0]))

    def scroll_to(self, tab, selector):
        self.run("scroll-to", self.find(tab, selector))

    def hover(self, tab, selector):
        self.run("hover", self.find(tab, selector))

    def wait_for(self, tab, selector, timeout="10s"):
        secs = float(str(timeout).rstrip("ms")) / (1000 if str(timeout).endswith("ms") else 1)
        deadline = time.time() + secs
        while not self.find(tab, selector, required=False):
            if time.time() > deadline:
                raise AgentDesktopError(f"timed out waiting for {selector} in {self.app(tab)}")
            time.sleep(0.4)

    def text(self, tab, selector, prop="text"):
        ref = self.find(tab, selector, required=False)
        if not ref:
            return None
        data = self.run("get", ref, "--property", prop)
        val = data.get("value", data.get(prop)) if isinstance(data, dict) else data
        return "" if val is None else str(val)

    def check(self, tab, kind, arg):
        """(ok, actual) for the expectations that make sense on a desktop app."""
        if kind == "visible":
            return (
                bool(self.find(tab, arg, required=False)),
                "found" if self.find(tab, arg, required=False) else "not found",
            )
        if kind == "not_visible":
            ref = self.find(tab, arg, required=False)
            return (not ref, "not found" if not ref else "found")
        if kind in ("text_contains", "text_matches"):
            sel = arg.get("selector")
            if not sel:
                ok = bool(self.find(tab, {"text": arg.get("text", "")}, required=False))
                return ok, "found" if ok else "not found"
            t = self.text(tab, sel)
            if t is None:
                return False, "not found"
            if kind == "text_contains":
                return arg["text"] in t, t[:160]
            flags = re.I if "i" in arg.get("flags", "") else 0
            return bool(re.search(arg["pattern"], t, flags)), t[:160]
        if kind == "value":
            t = self.text(tab, arg["selector"], "value")
            return (t is not None and t == str(arg["equals"])), t
        raise AgentDesktopError(f"expect {kind} is not supported on desktop tabs")

    def rect(self, tab, selector):
        """[x, y, w, h, screen_w, screen_h] of an element relative to the recorded window, for camera follow."""
        ref = self.find(tab, selector, required=False)
        win = self.capture_area(tab)
        if not ref or not win:
            return None
        b = bounds_of(self.run("get", ref, "--property", "bounds"))
        if not b:
            return None
        return [b[0] - win[0], b[1] - win[1], b[2], b[3], win[2], win[3]]

    def window_bounds(self, tab):
        try:
            return bounds_of(self.run("list-windows", "--app", self.app(tab)))
        except DriverError:
            return None

    def capture_area(self, tab, min_w=1280, min_h=720):
        """The app window grown to at least min_w x min_h (within the screen) so the header and captions fit."""
        win = self.window_bounds(tab)
        if not win:
            return None
        try:
            screen = bounds_of(self.run("list-displays")) or (0, 0, win[0] + win[2], win[1] + win[3])
        except DriverError:
            screen = (0, 0, win[0] + win[2], win[1] + win[3])
        sw, sh = screen[2], screen[3]
        w, h = min(max(win[2], min_w), sw), min(max(win[3], min_h), sh)
        x = min(max(0, win[0] + win[2] // 2 - w // 2), sw - w)
        y = min(max(0, win[1] + win[3] // 2 - h // 2), sh - h)
        return x, y, w, h

    # ---------- evidence ----------
    def screenshot(self, tab, path):
        self.run("screenshot", "--app", self.app(tab), str(path))

    def video_start(self, tab, duration=None):
        inp, crop = capture_input(self.capture_area(tab))
        vf = []
        if crop:
            x, y, w, h = (max(0, v) for v in crop)
            vf.append(f"crop={w - w % 2}:{h - h % 2}:{x}:{y}")
        vf.append("scale=trunc(iw/2)*2:trunc(ih/2)*2,format=yuv420p")
        tmp = os.path.join(tempfile.gettempdir(), f"tirai-desk-{os.getpid()}-{time.monotonic_ns()}.mp4")
        cmd = [ffmpeg_bin() or "ffmpeg", "-y", "-loglevel", "error", *inp, "-vf", ",".join(vf),
               "-c:v", "libx264", "-preset", "veryfast", "-crf", "23", tmp]  # fmt: skip
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        time.sleep(0.5)
        if proc.poll() is not None:
            raise AgentDesktopError(f"screen capture failed: {proc.stderr.read().decode(errors='replace')[-400:]}")
        return {"proc": proc, "tmp": tmp}

    def video_stop(self, recording, out):
        proc = recording["proc"]
        try:
            proc.communicate(b"q", timeout=20)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
        if not os.path.exists(recording["tmp"]):
            raise AgentDesktopError("screen capture produced no file (permission for screen recording?)")
        shutil.move(recording["tmp"], out)


class MixedDriver:
    """Browser tabs go to the browser driver (started lazily); `app:` tabs go to agent-desktop."""

    def __init__(self, browser_factory, desktop=None):
        self._factory = browser_factory
        self._browser = None
        self._init = []
        self.desk = desktop or AgentDesktop()

    @property
    def browser(self):
        if self._browser is None:
            self._browser = self._factory()
            if hasattr(self._browser, "init_scripts"):
                self._browser.init_scripts.extend(self._init)
        return self._browser

    @property
    def name(self):
        return f"{self._browser.name}+agent-desktop" if self._browser else "agent-desktop"

    @property
    def session(self):
        return self._browser.session if self._browser else None

    @property
    def init_scripts(self):
        return self._browser.init_scripts if self._browser else self._init

    def close_session(self):
        self.desk.close()
        if self._browser:
            self._browser.close_session()

    def video_stop(self, recording, out):
        target = self.desk if isinstance(recording, dict) and "proc" in recording else self.browser
        return target.video_stop(recording, out)

    def __getattr__(self, attr):
        def call(*args, **kw):
            if args and is_desktop(args[0]):
                return getattr(self.desk, attr)(*args, **kw)
            return getattr(self.browser, attr)(*args, **kw)

        return call
