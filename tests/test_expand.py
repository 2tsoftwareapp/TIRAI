import pytest

from tirai.scenario import ScenarioError, expand, load, render


def _sc(**extra):
    return {
        "name": "x",
        "tabs": {"app": {"url": "http://a"}},
        "steps": [
            {"id": "L", "tab": "app", "title": "login", "once": True, "expect": [{"visible": "#f"}]},
            {
                "id": "S1", "tab": "app", "title": "search {{q}}",
                "actions": [{"fill": {"selector": "#q", "value": "{{q}}"}}],
                "expect": [{"count": {"selector": "li", "equals": "{{n}}"}}],
            },
        ],
        **extra,
    }  # fmt: skip


def test_render_keeps_type_and_unknowns():
    assert render({"a": "{{n}}", "b": "x {{n}} {{later}}"}, {"n": 3}) == {"a": 3, "b": "x 3 {{later}}"}
    with pytest.raises(ScenarioError, match="undefined variable"):
        render("{{later}}", {}, strict=True)


def test_cases_repeat_steps_and_once_runs_first_only():
    sc = expand(_sc(cases=[{"name": "apple", "q": "apple", "n": 2}, {"q": "kiwi", "n": 0}]))
    assert [s["id"] for s in sc["steps"]] == ["L", "S1-1", "S1-2"]
    assert sc["steps"][1]["title"] == "[apple] search apple"
    assert sc["steps"][2]["title"] == "[q=kiwi, n=0] search kiwi"
    assert sc["steps"][2]["expect"][0]["count"]["equals"] == 0


def test_matrix_is_cartesian():
    sc = expand(_sc(matrix={"q": ["a", "b"], "n": [1, 2]}))
    assert len(sc["steps"]) == 1 + 4


def test_vars_apply_without_cases():
    sc = expand(_sc(vars={"q": "pear", "n": 1}))
    assert sc["steps"][1]["actions"][0]["fill"]["value"] == "pear"


def test_cases_and_matrix_conflict():
    with pytest.raises(ScenarioError, match="either cases or matrix"):
        expand(_sc(cases=[{"q": 1}], matrix={"q": [1]}))


def test_include_with_prefix_and_vars(tmp_path):
    (tmp_path / "common").mkdir()
    (tmp_path / "common" / "login.yaml").write_text(
        "steps:\n"
        "  - id: LOGIN\n    tab: app\n    title: login as {{user}}\n"
        "    actions: [{fill: {selector: '#email', value: '{{user}}'}}]\n"
        "    expect: [{visible: '#welcome'}]\n"
    )
    (tmp_path / "main.yaml").write_text(
        "name: inc\ntabs: {app: {url: 'http://a'}}\nsteps:\n"
        "  - include: common/login.yaml\n    with: {user: alice}\n    prefix: A-\n"
        "  - include: common/login.yaml\n    with: {user: bob}\n    prefix: B-\n"
    )
    sc = load(tmp_path / "main.yaml")
    assert [s["id"] for s in sc["steps"]] == ["A-LOGIN", "B-LOGIN"]
    assert sc["steps"][1]["actions"][0]["fill"]["value"] == "bob"


def test_include_cycle_and_missing(tmp_path):
    (tmp_path / "a.yaml").write_text("- include: b.yaml\n")
    (tmp_path / "b.yaml").write_text("- include: a.yaml\n")
    with pytest.raises(ScenarioError, match="include cycle"):
        expand({"steps": [{"include": "a.yaml"}]}, tmp_path)
    with pytest.raises(ScenarioError, match="include not found"):
        expand({"steps": [{"include": "nope.yaml"}]}, tmp_path)


def test_save_requires_name_and_selector(tmp_path):
    from tirai.scenario import validate

    sc = _sc()
    sc["steps"][1]["actions"].append({"save": {"name": "order"}})
    assert any("save is missing selector" in e for e in validate(sc))
