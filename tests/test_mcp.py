import io
import json

from tirai import mcp


def rpc(*msgs):
    out = io.StringIO()
    mcp.serve(io.StringIO("".join(json.dumps(m) + "\n" for m in msgs)), out)
    return [json.loads(x) for x in out.getvalue().splitlines()]


def test_initialize_list_and_unknown():
    init, listed, bad, missing = rpc(
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-03-26"}},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "nope"}},
        {"jsonrpc": "2.0", "id": 4, "method": "nope"},
    )
    assert init["result"]["serverInfo"]["name"] == "tirai" and init["result"]["protocolVersion"] == "2025-03-26"
    names = {t["name"] for t in listed["result"]["tools"]}
    assert {"validate", "dry_run", "record", "compose", "verify", "from_trace"} <= names
    assert bad["error"]["code"] == -32602 and missing["error"]["code"] == -32601


def test_validate_tool_runs_cli(tmp_path):
    sc = tmp_path / "s.yaml"
    sc.write_text("name: x\n")
    (reply,) = rpc(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": "validate", "arguments": {"scenario": str(sc)}},
        }
    )
    assert reply["result"]["isError"] is True and "tabs" in reply["result"]["content"][0]["text"]
