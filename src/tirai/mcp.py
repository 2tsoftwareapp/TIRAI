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

TOOLS = {
    "doctor": ("Check ffmpeg, BrowserSkill, fonts and optional drivers.", _obj({}), lambda a: ["doctor"]),
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
        _obj({"scenario": S, "out": S, "cwd": CWD}, ["scenario"]),
        lambda a: ["run", a["scenario"], "--dry-run", *_out(a)],
    ),
    "record": (
        "Dry-run, record and compose the final video + reports (stops at the first failing phase).",
        _obj(
            {
                "scenario": S,
                "out": S,
                "lang": {"type": "string", "description": "subtitle language to burn in"},
                "record_failures": {"type": "boolean", "description": "still record/compose when a step fails"},
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
        ],
    ),
    "compose": (
        "Rebuild final.mp4, subtitles and reports from a recorded timeline.json.",
        _obj({"timeline": S, "lang": S, "cwd": CWD}, ["timeline"]),
        lambda a: ["compose", a["timeline"], *(["--lang", a["lang"]] if a.get("lang") else [])],
    ),
    "verify": (
        "Check an evidence folder against its manifest.sha256.",
        _obj({"dir": S, "cwd": CWD}, ["dir"]),
        lambda a: ["verify", a["dir"]],
    ),
    "from_trace": (
        "Convert a `bsk record` trace (trace.json or its folder) into a scenario YAML.",
        _obj({"trace": S, "output": S, "no_resolve": B, "cwd": CWD}, ["trace", "output"]),
        lambda a: ["from-trace", a["trace"], "-o", a["output"], *(["--no-resolve"] if a.get("no_resolve") else [])],
    ),
    "annotate_js": ("Path of the injectable annotate.js overlay.", _obj({}), lambda a: ["annotate-js"]),
}


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
