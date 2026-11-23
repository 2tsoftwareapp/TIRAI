import json

import pytest

from tirai import capture, dbxconn, mcp
from tirai.scenario import validate


def test_capture_events_become_steps(tmp_path):
    polls = [
        {"events": [], "url": "http://a/login", "texts": ["Sign in"], "t": 1000},
        {
            "events": [
                {"op": "fill", "selector": "#email", "role": "input", "name": "Email", "value": "a", "t": 1100},
                {"op": "fill", "selector": "#email", "role": "input", "name": "Email", "value": "al", "t": 1200},
                {"op": "fill", "selector": "#pw", "role": "input", "name": "Password", "redacted": True, "t": 1300},
                {"op": "click", "selector": "#go", "role": "button", "name": "Sign in", "t": 1400},
            ],
            "url": "http://a/login",
            "texts": ["Sign in"],
            "t": 1500,
        },
        {"events": [], "url": "http://a/home", "texts": ["Sign in", "Welcome, Al"], "t": 3500},
    ]
    trace, selectors, texts = capture.to_trace("http://a/login", "Login", polls)
    out = tmp_path / "s.yaml"
    sc, env, skipped = capture.write_scenario(trace, selectors, texts, out)
    assert env == ["PASSWORD"] and not skipped
    step = sc["steps"][1]
    assert step["actions"] == [
        {"fill": {"selector": "#email", "value": "al"}},
        {"fill": {"selector": "#pw", "value": "${PASSWORD}"}},
        {"click": "#go"},
    ]
    assert {"url_contains": "/home"} in step["expect"]
    assert {"text_contains": {"text": "Welcome, Al"}} in step["expect"]
    assert out.read_text().startswith("name: Login")


def test_dsn_config():
    c = dbxconn.dsn_config("postgresql://ro:p%40ss@127.0.0.1:6543/shop", "shop", host="evpg")
    assert (c["db_type"], c["host"], c["port"], c["username"], c["password"], c["database"]) == (
        "postgres",
        "evpg",
        6543,
        "ro",
        "p@ss",
        "shop",
    )
    assert dbxconn.dsn_config("mysql+pymysql://u@h/db", "x")["port"] == 3306
    with pytest.raises(dbxconn.DbxError):
        dbxconn.dsn_config("sqlite:///x.db", "x")


def test_dbx_ensure_adds_then_updates(monkeypatch):
    sent = []
    store = []

    def request(self, path, body=None):
        sent.append((path, body))
        if path == "api/connection/list":
            return store
        if path == "api/connection/mcp/add":
            store.append({**body["config"], "database_info": {}})
            return body["config"]
        return None

    monkeypatch.setattr(dbxconn.DbxClient, "request", request)
    cfg = dbxconn.dsn_config("postgresql://ro:x@h/shop", "shop")
    client = dbxconn.DbxClient("http://dbx")
    action, cid = client.ensure(cfg)
    assert action == "added" and cid
    action2, cid2 = client.ensure({**cfg, "host": "evpg"})
    assert (action2, cid2) == ("updated", cid)
    saved = sent[-1][1]["configs"][0]
    assert sent[-1][0] == "api/connection/save" and saved["host"] == "evpg" and "database_info" not in saved


def base(**tab):
    return {
        "name": "x",
        "databases": {"default": {"dsn": "postgresql://u@h/d"}},
        "tabs": {"db": {"url": "http://dbx/", "kind": "dbx", **tab}},
        "steps": [{"id": "S1", "tab": "db", "title": "t", "expect": [{"visible": "canvas"}]}],
    }


def test_validate_dbx_connect():
    assert not [e for e in validate(base(dbx={"connect": {"name": "shop"}})) if "connect" in e]
    errs = validate(base(dbx={"connect": {"name": "shop", "database": "nope", "bogus": 1}}))
    assert any("connect.bogus" in e for e in errs) and any("connect.database" in e for e in errs)
    assert any("needs at least" in e for e in validate(base(dbx={"connect": {}})))


def test_mcp_driver_and_new_tools():
    tools = mcp.TOOLS
    assert tools["record"][2]({"scenario": "s.yaml", "driver": "bsk", "headed": True})[-3:] == [
        "--driver",
        "bsk",
        "--headed",
    ]
    assert tools["dry_run"][1]["properties"]["driver"]["enum"] == ["agent-browser", "bsk"]
    assert tools["dbx_connect"][2]({"name": "shop", "dsn_env": "EV_DB_DSN"}) == [
        "dbx-connect",
        "--dsn-env",
        "EV_DB_DSN",
        "--name",
        "shop",
    ]
    assert tools["capture"][2]({"url": "http://a", "output": "o.yaml", "timeout": 30})[-2:] == ["--timeout", "30"]
    assert "agent-browser" in tools["doctor"][0]
    json.dumps({n: t[1] for n, t in tools.items()})
