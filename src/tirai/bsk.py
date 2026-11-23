"""Thin wrapper over the Tencent BrowserSkill CLI (`bsk`)."""

import json
import re
import time

from tirai.system import bsk_bin, run_text


class BskError(RuntimeError):
    pass


def _bsk():
    path = bsk_bin()
    if not path:
        raise BskError("BrowserSkill CLI (bsk) not found; run `tirai setup` or set BSK_BIN")
    return path


class Bsk:
    def __init__(self, session=None):
        self.session = session

    def open_session(self, url, scope):
        """Start a fresh scoped session (own Agent Window) on `url`; returns the first tab id."""
        # The daemon can keep a closed session bound to the scope for a moment ("session X unknown").
        # Close it and retry; as a last resort use a scope unique to this run.
        scopes = [scope, scope, f"{scope}-{int(time.time())}"]
        for attempt, sc in enumerate(scopes):
            p = run_text([_bsk(), "open", url, "--scope", sc, "--json"], timeout=90)
            if p.returncode == 0:
                break
            err = p.stderr.strip() or p.stdout.strip()
            stale = re.search(r"session (\w+) unknown", err)
            # A previous run that stopped mid-step can leave the scope bound to a changed task tab.
            busy = "cooperation_sync_required" in err
            if not (stale or busy) or attempt == len(scopes) - 1:
                raise BskError(f"bsk open failed: {err}")
            target = ["--session", stale.group(1)] if stale else ["--scope", sc]
            run_text([_bsk(), "close", *target, "--json"], timeout=60)
            time.sleep(1 + attempt)
        data = json.loads(p.stdout)
        self.session = data["session_id"]
        return data["tab_id"]

    def close_session(self):
        if self.session:
            run_text([_bsk(), "close", "--session", self.session, "--json"], timeout=60)

    def run(self, *args, tab=None, timeout=90):
        cmd = [_bsk(), *args, "--session", self.session, "--json"]
        if tab is not None:
            cmd += ["--tab-id", str(tab)]
        p = run_text(cmd, timeout=timeout)
        out = p.stdout.strip()
        try:
            data = json.loads(out) if out else {}
        except json.JSONDecodeError:
            data = {"raw": out}
        if p.returncode != 0:
            raise BskError(f"bsk {' '.join(args[:2])} failed: {p.stderr.strip() or out}")
        return data

    def sync(self, tab, retries=20):
        for i in range(retries):
            try:
                return self.run("sync", tab=tab)
            except BskError as e:
                if "No observable document" not in str(e) or i == retries - 1:
                    raise
                time.sleep(0.5)

    # Every mutating action syncs first: bsk rejects actions on a stale control context.
    def navigate(self, tab, url):
        obs = self.sync(tab)["observation_id"]
        return self.run("navigate", url, "--observation", obs, tab=tab)

    def fill(self, tab, selector, value):
        self.sync(tab)
        return self.run("fill", "--selector", selector, "--value", value, tab=tab)

    def click(self, tab, selector):
        self.sync(tab)
        return self.run("click", "--selector", selector, tab=tab)

    def press(self, tab, key, selector=None):
        self.sync(tab)
        extra = ["--selector", selector] if selector else []
        return self.run("press", key, *extra, tab=tab)

    def select(self, tab, selector, values):
        self.sync(tab)
        vals = values if isinstance(values, list) else [values]
        return self.run("select", "--selector", selector, *[x for v in vals for x in ("--value", str(v))], tab=tab)

    def hover(self, tab, selector):
        self.sync(tab)
        return self.run("hover", "--selector", selector, tab=tab)

    def scroll_to(self, tab, selector):
        self.sync(tab)
        return self.run("scroll-to", "--selector", selector, tab=tab)

    def upload(self, tab, selector, files):
        self.sync(tab)
        files = files if isinstance(files, list) else [files]
        return self.run("upload", "--selector", selector, *[x for f in files for x in ("--file", f)], tab=tab)

    def console(self, tab, since=None):
        extra = ["--since", str(since)] if since is not None else []
        return self.run("console", "--limit", "200", *extra, tab=tab)

    def evaluate(self, tab, expr):
        # Annotation/assert scripts are read-only and throw when their targets are missing,
        # so they run unverified (bsk's documented mode for self-checking scripts on live pages).
        self.sync(tab)
        return self.run("evaluate", expr, "--unverified", tab=tab).get("value")

    def wait_for(self, tab, selector, timeout="10s"):
        return self.run("wait-for-element", "--selector", selector, "--timeout", timeout, tab=tab)

    def tab_create(self, url):
        return self.run("tab", "create", "--url", url)["tab_id"]

    def tab_select(self, tab):
        return self.run("tab", "select", str(tab))

    def screenshot(self, tab, path):
        self.run("screenshot", "--out", path, tab=tab)
        return path

    def video_start(self, tab, duration="9m"):
        self.sync(tab)
        data = self.run("video", "start", "--duration", duration, "--quality", "clear", tab=tab)
        rid = _find(data, "recording_id")
        if not rid:
            raise BskError(f"no recording id in {data}")
        return rid

    def video_stop(self, recording, out):
        p = run_text(
            [_bsk(), "video", "stop", "--recording", recording, "--out", out, "--overwrite", "--json"],
            timeout=180,
        )
        if p.returncode != 0:
            raise BskError(f"video stop failed: {p.stderr.strip() or p.stdout.strip()}")
        return out


def _find(obj, key):
    if isinstance(obj, dict):
        if key in obj:
            return obj[key]
        for v in obj.values():
            r = _find(v, key)
            if r:
                return r
    if isinstance(obj, list):
        for v in obj:
            r = _find(v, key)
            if r:
                return r
    return None
