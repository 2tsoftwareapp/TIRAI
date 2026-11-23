import pytest

from tirai.scenario import ScenarioError, env_vars, interpolate, load, validate


def base():
    return {
        "name": "x",
        "tabs": {"app": {"url": "http://a"}, "db": {"url": "http://d", "kind": "dbx"}},
        "databases": {"default": {"dsn": "sqlite:///x.db"}},
        "steps": [
            {
                "id": "S1",
                "tab": "app",
                "title": "t",
                "actions": [{"navigate": "${APP_URL}"}],
                "expect": [{"visible": "#a"}],
                "annotate": [{"box": {"target": "#a"}}, {"blur": "#p"}],
            }
        ],
    }


def test_valid_scenario_has_no_problems():
    assert validate(base()) == []


@pytest.mark.parametrize(
    "mutate, fragment",
    [
        (lambda s: s["steps"][0].pop("expect"), "expect is required"),
        (lambda s: s["steps"][0].update(tab="nope"), "tab must be one of"),
        (lambda s: s["steps"].append(dict(s["steps"][0])), "duplicate id"),
        (lambda s: s["steps"][0]["actions"].append({"teleport": 1}), "unknown 'teleport'"),
        (lambda s: s["steps"][0]["actions"].append({"sql": "select 1"}), "requires a tab with kind: dbx"),
        (lambda s: s["steps"][0]["expect"].append({"db": {"sql": "s", "rows": [], "database": "x"}}), "not defined"),
        (lambda s: s["steps"][0]["annotate"].append({"arrow": {"label": "x"}}), "needs a target"),
        (lambda s: s["steps"][0]["actions"].append({"select": {"selector": "#s"}}), "select is missing value"),
        (lambda s: s["steps"][0]["actions"].append({"upload": "#f"}), "upload needs a mapping"),
        (lambda s: s["steps"][0]["actions"].append({"dialog": "maybe"}), "dialog must be accept or dismiss"),
        (lambda s: s["steps"][0]["expect"].append({"count": {"selector": "li"}}), "count is missing equals"),
        (lambda s: s["steps"][0]["expect"].append({"attribute": {"selector": "a", "equals": 1}}), "missing name"),
        (lambda s: s["steps"][0]["expect"].append({"text_matches": {"pattern": "("}}), "invalid pattern"),
        (lambda s: s["steps"][0]["expect"].append({"request": {"status": 200}}), "missing url_contains"),
        (lambda s: s["steps"][0].update(zoom={"factor": 2}), "zoom needs a selector"),
        (lambda s: s["steps"][0].update(layout="grid"), "layout must be split"),
        (lambda s: s["steps"][0].update(subtitle={}), "subtitle must be text"),
        (lambda s: s.update(privacy={"mask": ["ssn"]}), "unknown rule 'ssn'"),
        (lambda s: s.update(privacy={"patterns": ["("]}), "invalid pattern"),
        (lambda s: s.update(privacy={"blur": []}), "privacy.blur: unknown"),
    ],
)
def test_validation_problems(mutate, fragment):
    sc = base()
    mutate(sc)
    assert any(fragment in p for p in validate(sc))


def test_extended_vocabulary_is_valid():
    sc = base()
    sc["steps"][0]["actions"] += [
        {"select": {"selector": "#country", "value": "VN"}},
        {"hover": "#menu"},
        {"scroll": "#footer"},
        {"upload": {"selector": "#file", "file": "fixtures/a.pdf"}},
        {"dialog": "accept"},
    ]
    sc["steps"][0]["expect"] += [
        {"not_visible": "#error"},
        {"text_matches": {"selector": "#total", "pattern": "^\\d+ items$"}},
        {"value": {"selector": "#email", "equals": "a@b.c"}},
        {"attribute": {"selector": "#save", "name": "disabled", "equals": ""}},
        {"count": {"selector": "tr.row", "equals": 3}},
        {"request": {"url_contains": "/api/save", "status": 200}},
        {"no_console_errors": None},
    ]
    assert validate(sc) == []


def test_interpolate_and_missing_var(monkeypatch):
    monkeypatch.setenv("APP_URL", "http://x")
    assert interpolate("${APP_URL}/login") == "http://x/login"
    monkeypatch.delenv("APP_URL")
    with pytest.raises(ScenarioError):
        interpolate("${APP_URL}")
    assert interpolate(5) == 5


def test_env_vars_collects_nested():
    assert env_vars(base()) == {"APP_URL"}


def test_load_rejects_invalid(tmp_path):
    p = tmp_path / "s.yaml"
    p.write_text("name: x\ntabs: {}\nsteps: []\n")
    with pytest.raises(ScenarioError):
        load(p)


def test_example_scenarios_are_valid():
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    load(root / "examples/demo/login-lock.yaml")
    load(root / "src/tirai/assets/scenario.template.yaml")
