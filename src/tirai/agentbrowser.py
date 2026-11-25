"""Browser driver over vercel-labs agent-browser (Chrome for Testing via CDP; headless by default).

Same surface as `tirai.bsk.Bsk`, so the runner can use either. agent-browser commands act on the session's
active tab, so every call first switches to the tab it targets. Recording (`record start`) captures the
active tab only, like bsk; the runner already records one segment per tab.
"""

import json
import os
import re
import shutil
import tempfile
from pathlib import Path

from tirai.bsk import DriverError
from tirai.system import agent_browser_bin, run_text, tool_env


class AgentBrowserError(DriverError):
    pass


def _bin():
    path = agent_browser_bin()
    if not path:
        raise AgentBrowserError("agent-browser not found; run `tirai setup` or set AGENT_BROWSER_BIN")
    return path


def _key(key):
    """bsk-style `Ctrl+Enter` / `Cmd+K` -> agent-browser `Control+Enter` / `Meta+K`."""
    names = {"ctrl": "Control", "control": "Control", "cmd": "Meta", "meta": "Meta", "alt": "Alt", "shift": "Shift"}
    return "+".join(names.get(p.lower(), p) for p in key.split("+"))


def _ms(timeout):
    m = re.fullmatch(r"(\d+(?:\.\d+)?)(ms|s)?", str(timeout).strip())
    if not m:
        return "10000"
    n = float(m.group(1))
    return str(int(n if m.group(2) == "ms" else n * 1000))


class AgentBrowser:
    name = "agent-browser"

    def __init__(self, session=None, headed=None, cursor=None):
        self.session = session
        self.active = None
        env = os.environ
        self.headed = headed if headed is not None else env.get("TIRAI_HEADED", "") not in ("", "0", "false")
        self.cursor = cursor if cursor is not None else env.get("TIRAI_CURSOR", "1") not in ("0", "false")
        self.expect_popups = True  # runner sets False when scenario has no popup tabs to avoid extra tab switches
        self.init_scripts = []  # JS sources registered before any page script when the session launches
        self._init_dir = None

    def run(self, *args, timeout=90, stdin=None, launch=False):
        cmd = [_bin(), "--session", self.session, "--json"]
        if launch and self.headed:
            cmd.append("--headed")
        if launch and self.init_scripts:
            self._init_dir = self._init_dir or tempfile.mkdtemp(prefix="tirai-init-")
            for i, src in enumerate(self.init_scripts):
                f = Path(self._init_dir) / f"init-{i}.js"
                f.write_text(src, encoding="utf-8")
                cmd += ["--init-script", str(f)]
        p = run_text([*cmd, *args], timeout=timeout, input=stdin, env=tool_env())
        out = p.stdout.strip()
        try:
            data = json.loads(out.splitlines()[-1]) if out else {}
        except json.JSONDecodeError:
            data = {"success": p.returncode == 0, "error": out}
        if p.returncode != 0 or not data.get("success", False):
            err = data.get("error") or p.stderr.strip() or out
            raise AgentBrowserError(f"agent-browser {args[0]} failed: {err}")
        return data.get("data") or {}

    def open_session(self, url, scope):
        """Fresh session (own daemon + browser) named after `scope`; returns the first tab id."""
        self.session = re.sub(r"[^\w-]", "-", f"{scope}-{os.getpid()}")
        run_text([_bin(), "--session", self.session, "close"], timeout=60, env=tool_env())
        self.run("open", url, launch=True, timeout=180)
        tabs = self.run("tab", "list").get("tabs", [])
        self.active = next((t["tabId"] for t in tabs if t.get("active")), "t1")
        return self.active

    def close_session(self):
        if self.session:
            run_text([_bin(), "--session", self.session, "close"], timeout=60, env=tool_env())
        if self._init_dir:
            shutil.rmtree(self._init_dir, ignore_errors=True)
            self._init_dir = None

    def use(self, tab):
        if tab is not None and tab != self.active:
            self.run("tab", str(tab))
            self.active = tab

    def sync(self, tab, retries=None):
        self.use(tab)
        return {}

    def navigate(self, tab, url):
        self.use(tab)
        return self.run("open", url, timeout=120)

    def fill(self, tab, selector, value):
        self.use(tab)
        return self.run("fill", selector, "--", str(value))

    def type_text(self, tab, selector, value):
        self.use(tab)
        return self.run("type", selector, "--", str(value))

    def click(self, tab, selector):
        self.use(tab)
        out = self.run("click", selector)
        if self.expect_popups:
            self.active = None  # a click may open a popup that Chrome focuses; re-select next time
        return out

    def press(self, tab, key, selector=None):
        self.use(tab)
        if selector:
            self.run("focus", selector)
        k = _key(key)
        out = self.run("press", k)
        if self.expect_popups and k not in ("Tab", "Shift+Tab", "Backspace", "Delete", "Escape", "Control+A", "Meta+A"):
            self.active = None  # Enter/F-keys may open a popup tab that Chrome focuses
        return out

    def select(self, tab, selector, values):
        self.use(tab)
        vals = values if isinstance(values, list) else [values]
        return self.run("select", selector, *[str(v) for v in vals])

    def hover(self, tab, selector):
        self.use(tab)
        return self.run("hover", selector)

    def scroll_to(self, tab, selector):
        self.use(tab)
        return self.run("scrollintoview", selector)

    def upload(self, tab, selector, files):
        self.use(tab)
        return self.run("upload", selector, *(files if isinstance(files, list) else [files]))

    def download(self, tab, selector, path):
        self.use(tab)
        out = self.run("download", selector, str(path), timeout=180)
        self.active = None  # the download click may open a popup that Chrome focuses
        return out

    def console(self, tab, since=None):
        """bsk-shaped console: {'entries': [{text, level}], 'next_since': cursor}."""
        self.use(tab)
        msgs = self.run("console").get("messages", [])
        entries = [{"text": m.get("text", ""), "level": m.get("type")} for m in msgs[int(since or 0) :]]
        return {"entries": entries, "next_since": len(msgs)}

    def evaluate(self, tab, expr):
        self.use(tab)
        return self.run("eval", "--stdin", stdin=expr).get("result")

    def wait_for(self, tab, selector, timeout="10s"):
        self.use(tab)
        return self.run("wait", selector, "--timeout", _ms(timeout), timeout=120)

    def tab_list(self):
        """[{id, url}] of every page tab in the session (popups opened by the page included)."""
        tabs = self.run("tab", "list").get("tabs", [])
        return [{"id": t["tabId"], "url": t.get("url", "")} for t in tabs if t.get("type", "page") == "page"]

    def set_viewport(self, tab, width, height):
        self.use(tab)
        return self.run("set", "viewport", str(width), str(height))

    def clear_state(self, tab, cookies=True):
        """Drop cookies (whole session) and this origin's local/session storage."""
        self.use(tab)
        if cookies:
            self.run("cookies", "clear")
        self.run("storage", "local", "clear")
        self.run("storage", "session", "clear")

    def tab_create(self, url):
        self.active = self.run("tab", "new", url, timeout=120)["tabId"]
        return self.active

    def tab_select(self, tab):
        self.run("tab", str(tab))
        self.active = tab

    def screenshot(self, tab, path):
        self.use(tab)
        self.run("screenshot", path)
        return path

    def video_start(self, tab, duration=None):
        self.use(tab)
        path = str(Path(tempfile.mkdtemp(prefix="tirai-rec-")) / "rec.mp4")
        self.run("record", "start", path, *(["--cursor"] if self.cursor else []))
        return path

    def video_stop(self, recording, out):
        self.run("record", "stop", timeout=180)
        shutil.move(recording, out)
        shutil.rmtree(Path(recording).parent, ignore_errors=True)
        return out


def make_driver(name=None, session=None, headed=None):
    """`agent-browser` (default when installed) or `bsk`; TIRAI_DRIVER / scenario `driver:` override."""
    from tirai.bsk import Bsk
    from tirai.system import bsk_bin

    name = (
        name or os.environ.get("TIRAI_DRIVER") or ("bsk" if bsk_bin() and not agent_browser_bin() else "agent-browser")
    )
    if name == "bsk":
        return Bsk(session)
    if name == "agent-browser":
        return AgentBrowser(session, headed=headed)
    raise DriverError(f"unknown driver {name!r} (agent-browser | bsk)")
