"""Minimal MCP server (stdio, JSON-RPC 2.0, newline-delimited) exposing the tirai CLI as tools.

No SDK dependency: it implements initialize, tools/list and tools/call. Every tool runs the matching
`tirai` subcommand in a subprocess and returns its output, so behaviour is identical to the CLI.
"""

import json
import os
import subprocess
import sys

from tirai import __version__

PROTOCOL = "2024-11-05"


def _obj(props, required=()):
    return {"type": "object", "properties": props, "required": list(required)}


S = {"type": "string"}
B = {"type": "boolean"}
CWD = {"type": "string", "description": "working directory (default: the server's)"}
DRIVER = {"type": "string", "enum": ["agent-browser", "bsk"], "description": "browser driver (default: agent-browser)"}
HEADED = {"type": "boolean", "description": "show the agent-browser window (default: headless)"}

TOOLS = {
    "doctor": (
        "Check ffmpeg (>= 6), agent-browser (default driver), BrowserSkill (optional), DBX, fonts and DB drivers.",
        _obj({}),
        lambda a: ["doctor"],
    ),
    "init": (
        "Write a scenario template to `path`.",
        _obj({"path": S, "force": B, "cwd": CWD}, ["path"]),
        lambda a: ["init", a["path"], *(["--force"] if a.get("force") else [])],
    ),
    "validate": (
        "Validate a scenario file and list the env vars it needs.",
        _obj({"scenario": S, "cwd": CWD}, ["scenario"]),
        lambda a: ["validate", a["scenario"]],
    ),
    "dry_run": (
        "Run every step without recording; reports which step/expectation fails. Always do this before record.",
        _obj({"scenario": S, "out": S, "driver": DRIVER, "headed": HEADED, "cwd": CWD}, ["scenario"]),
        lambda a: ["run", a["scenario"], "--dry-run", *_out(a), *_driver(a)],
    ),
    "record": (
        "Dry-run, record and compose the final video + reports (stops at the first failing phase).",
        _obj(
            {
                "scenario": S,
                "out": S,
                "lang": {"type": "string", "description": "subtitle language to burn in"},
                "record_failures": {"type": "boolean", "description": "still record/compose when a step fails"},
                "driver": DRIVER,
                "headed": HEADED,
                "cwd": CWD,
            },
            ["scenario"],
        ),
        lambda a: [
            "record",
            a["scenario"],
            *_out(a),
            *(["--lang", a["lang"]] if a.get("lang") else []),
            *(["--record-failures"] if a.get("record_failures") else []),
            *_driver(a),
        ],
    ),
    "compose": (
        "Rebuild final.mp4, subtitles and reports from a recorded timeline.json.",
        _obj({"timeline": S, "lang": S, "cwd": CWD}, ["timeline"]),
        lambda a: ["compose", a["timeline"], *(["--lang", a["lang"]] if a.get("lang") else [])],
    ),
    "verify": (
        "Check an evidence folder against its manifest.sha256 (and its signature; `pubkey` = trusted SSH key).",
        _obj({"dir": S, "pubkey": S, "cwd": CWD}, ["dir"]),
        lambda a: ["verify", a["dir"], *(["--pubkey", a["pubkey"]] if a.get("pubkey") else [])],
    ),
    "sign": (
        "Sign manifest.sha256 with an SSH private key (default $TIRAI_SIGN_KEY); `tsa` adds an RFC 3161 timestamp.",
        _obj({"dir": S, "key": S, "tsa": S, "cwd": CWD}, ["dir"]),
        lambda a: [
            "sign",
            a["dir"],
            *(["--key", a["key"]] if a.get("key") else []),
            *(["--tsa", a["tsa"]] if a.get("tsa") else []),
        ],
    ),
    "export": (
        "Write junit.xml, xray.json (Xray import) and testrail.csv (TestRail import) from an evidence folder. "
        "Nothing is uploaded.",
        _obj({"dir": S, "formats": {"type": "array", "items": S}, "cwd": CWD}, ["dir"]),
        lambda a: ["export", a["dir"], *(["--format", *a["formats"]] if a.get("formats") else [])],
    ),
    "scan_pii": (
        "OCR the final video for PII (email, phone, card, token), incl. text drawn on canvas; `fix` pixelates hits.",
        _obj({"dir": S, "rules": {"type": "array", "items": S}, "fix": B, "cwd": CWD}, ["dir"]),
        lambda a: [
            "scan-pii",
            a["dir"],
            *(["--rules", *a["rules"]] if a.get("rules") else []),
            *(["--fix"] if a.get("fix") else []),
        ],
    ),
    "index": (
        "Write one filterable HTML page listing every evidence run found under `dirs`.",
        _obj({"dirs": {"type": "array", "items": S}, "out": S, "cwd": CWD}, ["dirs"]),
        lambda a: ["index", *a["dirs"], *(["--out", a["out"]] if a.get("out") else [])],
    ),
    "from_spec": (
        "Draft a scenario YAML from a Gherkin .feature, Markdown table or CSV of test cases; `url` resolves element "
        "names to selectors on the live page. Review TODO(...) selectors with the user before recording.",
        _obj({"spec": S, "output": S, "url": S, "cwd": CWD}, ["spec"]),
        lambda a: [
            "from-spec",
            a["spec"],
            *(["--output", a["output"]] if a.get("output") else []),
            *(["--url", a["url"]] if a.get("url") else []),
        ],
    ),
    "from_trace": (
        "Convert a `bsk record` trace (trace.json or its folder) into a scenario YAML.",
        _obj({"trace": S, "output": S, "no_resolve": B, "cwd": CWD}, ["trace", "output"]),
        lambda a: ["from-trace", a["trace"], "-o", a["output"], *(["--no-resolve"] if a.get("no_resolve") else [])],
    ),
    "capture": (
        "Open a visible browser at `url`; the user clicks through the flow once and closes the window (or the "
        "timeout ends it); writes a draft scenario YAML. Default driver agent-browser; bsk uses `bsk record`.",
        _obj(
            {"url": S, "output": S, "purpose": S, "driver": DRIVER, "timeout": {"type": "number"}, "cwd": CWD},
            ["url", "output"],
        ),
        lambda a: [
            "capture",
            a["url"],
            "-o",
            a["output"],
            *(["--purpose", a["purpose"]] if a.get("purpose") else []),
            *(["--driver", a["driver"]] if a.get("driver") else []),
            *(["--timeout", str(a["timeout"])] if a.get("timeout") else []),
        ],
    ),
    "dbx_connect": (
        "Create or update a DBX web connection from a DSN held in an environment variable (read-only user advised).",
        _obj(
            {
                "name": S,
                "dsn_env": {"type": "string", "description": "env var with the DSN, e.g. EV_DB_DSN"},
                "url": {"type": "string", "description": "DBX web URL (default DBX_URL or http://127.0.0.1:4224/)"},
                "db_host": {"type": "string", "description": "database host as DBX sees it (Docker service name)"},
                "cwd": CWD,
            },
            ["name", "dsn_env"],
        ),
        lambda a: [
            "dbx-connect",
            "--dsn-env",
            a["dsn_env"],
            "--name",
            a["name"],
            *(["--url", a["url"]] if a.get("url") else []),
            *(["--db-host", a["db_host"]] if a.get("db_host") else []),
        ],
    ),
    "annotate_js": ("Path of the injectable annotate.js overlay.", _obj({}), lambda a: ["annotate-js"]),
}


def _driver(a):
    return [*(["--driver", a["driver"]] if a.get("driver") else []), *(["--headed"] if a.get("headed") else [])]


def _out(a):
    return ["--out", a["out"]] if a.get("out") else []


def tirai_cmd():
    return [sys.executable] if getattr(sys, "frozen", False) else [sys.executable, "-m", "tirai"]


def call(name, args):
    if name not in TOOLS:
        raise KeyError(name)
    argv = TOOLS[name][2](args)
    p = subprocess.run(
        [*tirai_cmd(), *argv],
        cwd=args.get("cwd") or None,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env={**os.environ, "PYTHONUNBUFFERED": "1"},
    )
    text = (p.stdout + ("\n" + p.stderr if p.stderr.strip() else "")).strip() or f"exit code {p.returncode}"
    return {"content": [{"type": "text", "text": text}], "isError": p.returncode != 0}


def handle(msg):
    method, mid = msg.get("method"), msg.get("id")
    if mid is None:
        return None  # notification (e.g. notifications/initialized)
    if method == "initialize":
        result = {
            "protocolVersion": msg.get("params", {}).get("protocolVersion", PROTOCOL),
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "tirai", "version": __version__},
        }
    elif method == "ping":
        result = {}
    elif method == "tools/list":
        result = {"tools": [{"name": n, "description": d, "inputSchema": s} for n, (d, s, _) in TOOLS.items()]}
    elif method == "tools/call":
        params = msg.get("params") or {}
        try:
            result = call(params.get("name"), params.get("arguments") or {})
        except KeyError:
            return {
                "jsonrpc": "2.0",
                "id": mid,
                "error": {"code": -32602, "message": f"unknown tool {params.get('name')}"},
            }
    else:
        return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": f"method not found: {method}"}}
    return {"jsonrpc": "2.0", "id": mid, "result": result}


def serve(stdin=None, stdout=None):
    stdin, stdout = stdin or sys.stdin, stdout or sys.stdout
    for line in stdin:
        if not line.strip():
            continue
        try:
            reply = handle(json.loads(line))
        except json.JSONDecodeError as e:
            reply = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": str(e)}}
        if reply is not None:
            stdout.write(json.dumps(reply, ensure_ascii=False) + "\n")
            stdout.flush()
