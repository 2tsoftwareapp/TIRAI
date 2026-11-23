"""Thin wrapper over the Tencent BrowserSkill CLI (`bsk`)."""

import json
import os
import shutil
import subprocess
import time

BSK = os.environ.get("BSK_BIN") or shutil.which("bsk") or os.path.expanduser("~/.local/bin/bsk")


class BskError(RuntimeError):
    pass


class Bsk:
    def __init__(self, session=None):
        self.session = session

    def open_session(self, url, scope):
        """Start a fresh scoped session (own Agent Window) on `url`; returns the first tab id."""
        p = subprocess.run([BSK, "open", url, "--scope", scope, "--json"], capture_output=True, text=True, timeout=90)
        if p.returncode != 0:
            raise BskError(f"bsk open failed: {p.stderr.strip() or p.stdout.strip()}")
        data = json.loads(p.stdout)
        self.session = data["session_id"]
        return data["tab_id"]

    def close_session(self):
        if self.session:
            subprocess.run([BSK, "close", "--session", self.session, "--json"], capture_output=True, timeout=60)

    def run(self, *args, tab=None, timeout=90):
        cmd = [BSK, *args, "--session", self.session, "--json"]
        if tab is not None:
            cmd += ["--tab-id", str(tab)]
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
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
        p = subprocess.run(
            [BSK, "video", "stop", "--recording", recording, "--out", out, "--overwrite", "--json"],
            capture_output=True,
            text=True,
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
