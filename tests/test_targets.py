import json

import pytest
from test_runner import FakeDriver

from tirai import inspect, mcp, runner, scenario
from tirai import targets as tg
from tirai.scenario import ScenarioError


def base(**extra):
    sc = {
        "name": "t",
        "tabs": {"app": {"url": "http://app.test/"}},
        "targets": {
            "email": ["testid=email", "#email"],
            "submit": 'role=button[name="Sign in"]',
            "row": {"any": ["text=Bob"], "within": "#users", "nth": 0},
        },
        "steps": [
            {
                "id": "S1",
                "tab": "app",
                "title": "Login",
                "actions": [
                    {"fill": {"selector": "@email", "value": "write @email here"}},
                    {"click": "@submit"},
                    {"press": {"key": "Enter", "selector": "@email"}},
                ],
                "expect": [
                    {"visible": "@row"},
                    {"text_contains": {"selector": "@row", "text": "mail @submit"}},
                ],
                "annotate": [{"box": "@email"}, {"arrow": {"target": "@submit", "label": "@submit"}}],
                "zoom": "@submit",
            }
        ],
    }
    sc.update(extra)
    return sc


def test_normalize_accepts_string_list_and_mapping():
    t = tg.normalize(base()["targets"])
    assert t["email"]["locators"] == ["testid=email", "#email"]
    assert t["submit"] == {"locators": ['role=button[name="Sign in"]'], "within": None, "nth": None}
    assert t["row"] == {"locators": ["text=Bob"], "within": "#users", "nth": 0}


def test_apply_replaces_refs_only_in_selector_positions():
    out, missing = tg.apply(base())
    st = out["steps"][0]
    assert not missing
    assert st["actions"][0]["fill"] == {"selector": '[data-tirai-id~="email"]', "value": "write @email here"}
    assert st["actions"][1] == {"click": '[data-tirai-id~="submit"]'}
    assert st["actions"][2]["press"]["selector"] == '[data-tirai-id~="email"]'
    assert st["expect"][1]["text_contains"] == {"selector": '[data-tirai-id~="row"]', "text": "mail @submit"}
    assert st["annotate"] == [
        {"box": '[data-tirai-id~="email"]'},
        {"arrow": {"target": '[data-tirai-id~="submit"]', "label": "@submit"}},
    ]
    assert st["zoom"] == '[data-tirai-id~="submit"]'
    assert set(out["_targets"]) == {"email", "submit", "row"}


def test_inline_locator_becomes_anonymous_target():
    sc = base()
    sc["steps"][0]["actions"].append({"click": "text=Forgot password?"})
    out, _ = tg.apply(sc)
    assert out["steps"][0]["actions"][-1] == {"click": '[data-tirai-id~="_t1"]'}
    assert out["_targets"]["_t1"]["locators"] == ["text=Forgot password?"]


def test_plain_css_and_email_like_text_untouched():
    sc = base()
    sc["steps"][0]["actions"] += [{"click": "a[href='mailto:x@y.z']"}, {"fill": {"selector": "#q", "value": "@x"}}]
    out, missing = tg.apply(sc)
    assert out["steps"][0]["actions"][-2] == {"click": "a[href='mailto:x@y.z']"}
    assert not missing


def test_validate_reports_bad_targets_and_unknown_refs():
    sc = base(targets={"bad name": "#x", "empty": [], "odd": {"any": ["#a"], "foo": 1, "nth": "x"}})
    errs = scenario.validate(sc)
    text = "\n".join(errs)
    assert "targets.bad name: name must be" in text
    assert "targets.empty: needs a locator" in text
    assert "targets.odd: unknown foo" in text and "targets.odd.nth" in text
    errs = scenario.validate(base(targets={"email": "#email"}))
    assert "@submit: not defined under targets" in errs and "@row: not defined under targets" in errs


def test_load_substitutes(tmp_path):
    p = tmp_path / "s.yaml"
    p.write_text(json.dumps(base()))
    sc = scenario.load(p)
    assert sc["steps"][0]["actions"][1] == {"click": '[data-tirai-id~="submit"]'}
    assert scenario.validate(base()) == []


def test_used_in_and_scripts():
    assert tg.used_in({"press": {"key": "a", "selector": '[data-tirai-id~="email"]'}}) == {"email"}
    assert tg.used_in({"click": "#x"}) == set()
    t = tg.normalize({"a": "#a"})
    init = tg.init_script(t)
    assert "window.__tiraiT" in init and json.dumps(t) in init and "DOMContentLoaded" in init
    assert tg.with_tags({}, "1") == "1" and tg.with_tags(t, "1").endswith(";1")


def test_healed_and_failure_messages():
    spec = {"locators": ["#old", "text=Go"]}
    assert tg.healed("go", spec, {"ok": True, "via": 0, "counts": ["#old: 1"]}) is None
    msg = tg.healed("go", spec, {"ok": True, "via": 1, "counts": ["#old: 0", "text=Go: 1"]})
    assert msg == "target @go: #old: 0 -> used 'text=Go'; update the target"
    assert "text=Go: 2" in tg.describe_failure("go", {"ok": False, "via": -1, "counts": ["#old: 0", "text=Go: 2"]})


class TargetDriver(FakeDriver):
    def __init__(self, report):
        super().__init__()
        self.report = report
        self.tags = 0

    def evaluate(self, tab, expr):
        if expr.startswith(tg.script()):
            rest = expr[len(tg.script()) :]
            if rest.startswith(";window.__tiraiT.tag(") and rest.endswith(")") and ";(" not in rest[1:]:
                self.tags += 1
                return self.report
            if "__tiraiT.near(" in rest:
                return ['#email (textbox "Email")']
        return super().evaluate(tab, expr)


@pytest.fixture
def env(monkeypatch):
    monkeypatch.setenv("TIRAI_TIMING_SCALE", "0")
    monkeypatch.setenv("TIRAI_EXPECT_TIMEOUT", "0")


def run_with(monkeypatch, tmp_path, report, sc=None):
    d = TargetDriver(report)
    monkeypatch.setattr(runner, "make_driver", lambda *a, **k: d)
    sc = sc or tg.apply(base())[0]
    sc["steps"][0].pop("zoom")
    sc["steps"][0].pop("annotate")
    return d, runner.run(sc, tmp_path, record=False, hold=0)


OK = {"ok": True, "via": 0, "counts": []}


def test_runner_tags_targets_and_records_heal_warning(env, monkeypatch, tmp_path):
    report = {"email": {"ok": True, "via": 1, "counts": ["testid=email: 0", "#email: 1"]}, "submit": OK, "row": OK}
    d, tl = run_with(monkeypatch, tmp_path, report)
    step = tl["steps"][0]
    assert step["status"] == "passed", step
    assert step["warnings"] == ["target @email: testid=email: 0 -> used '#email'; update the target"]
    assert ("click", "t1", '[data-tirai-id~="submit"]') in d.calls
    assert d.tags >= 3
    assert any("__tiraiT" in s for s in d.init_scripts)


def test_runner_fails_closed_on_ambiguous_target(env, monkeypatch, tmp_path):
    report = {"email": OK, "submit": {"ok": False, "via": -1, "counts": ['role=button[name="Sign in"]: 2']}}
    d, tl = run_with(monkeypatch, tmp_path, report)
    step = tl["steps"][0]
    assert step["status"] == "error"
    assert 'target @submit: no locator matched exactly one element (role=button[name="Sign in"]: 2)' in step["error"]
    assert not any(c[0] == "click" for c in d.calls)


def test_driver_error_on_plain_css_suggests_nearby(env, monkeypatch, tmp_path):
    sc = {
        "name": "t",
        "tabs": {"app": {"url": "http://app.test/"}},
        "steps": [
            {"id": "S1", "tab": "app", "title": "x", "actions": [{"click": "#emial"}], "expect": [{"visible": "#a"}]}
        ],
    }
    d = TargetDriver({})
    d.fail_on = "click"
    monkeypatch.setattr(runner, "make_driver", lambda *a, **k: d)
    tl = runner.run(sc, tmp_path, record=False, hold=0)
    assert tl["steps"][0]["error"] == 'click boom; nearby: #email (textbox "Email")'


def test_inspect_writes_pages_and_targets(tmp_path):
    pages = [
        {
            "step": "S1",
            "title": "Login",
            "url": "http://app/",
            "elements": [
                {"id": "email_textbox", "role": "textbox", "name": "Email", "locators": ["#email"], "tagged": "email"},
                {"id": "save_button", "role": "button", "name": "Save", "locators": [], "tagged": None},
                {"id": "go_button", "role": "button", "name": 'Go "now"', "locators": ['role=button[name="Go"]']},
            ],
        },
        {
            "step": "S2",
            "title": "Home",
            "url": "http://app/home",
            "elements": [
                {"id": "email_textbox", "role": "textbox", "name": "Email", "locators": ["#email"], "tagged": None},
                {"id": "go_button", "role": "link", "name": "Go", "locators": ["#go-link"], "tagged": None},
            ],
        },
    ]
    res = inspect.write(pages, tmp_path, [{"id": "S1", "status": "passed"}])
    assert res["pages"] == 2 and res["targets"] == 3 and res["failed"] == []
    y = (tmp_path / "inspect" / "targets.yaml").read_text()
    assert y == (
        "targets:\n  email:\n    - '#email'\n  go_button:\n    - 'role=button[name=\"Go\"]'\n"
        "  go_button_2:\n    - '#go-link'\n"
    )
    md = (tmp_path / "inspect" / "S1.md").read_text()
    assert "| email | textbox | Email | `#email` |" in md and "no unique locator" in md


def test_inspect_cli_url_scenario_and_mcp():
    sc = inspect.url_scenario("http://x/")
    assert scenario.validate(sc) == []
    assert mcp.TOOLS["inspect"][2]({"scenario": "s.yaml", "out": "o"}) == ["inspect", "s.yaml", "--out", "o"]


def test_load_rejects_unknown_ref(tmp_path):
    p = tmp_path / "s.yaml"
    p.write_text(json.dumps(base(targets={})))
    with pytest.raises(ScenarioError):
        scenario.load(p)


def test_privacy_selectors_accept_targets():
    out, missing = tg.apply(base(privacy={"selectors": ["@email", ".api-key"], "mask": ["email"]}))
    assert out["privacy"]["selectors"] == ['[data-tirai-id~="email"]', ".api-key"]
    assert out["privacy"]["mask"] == ["email"] and not missing
