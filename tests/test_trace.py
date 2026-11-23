from tirai.scenario import validate
from tirai.trace import env_name, plan

TRACE = {
    "purpose": "Log in as Alice",
    "entry": {"start_url": "http://app.local/"},
    "states": [
        {"id": "s1", "url": "http://app.local/"},
        {"id": "s2", "url": "http://app.local/"},
        {"id": "s3", "url": "http://app.local/login"},
    ],
    "steps": [
        {"op": "fill", "id": 1, "state": "s1", "target": {"role": "textbox", "name": "Email"}, "value": "a@x.io"},
        {
            "op": "fill",
            "id": 2,
            "state": "s2",
            "target": {"role": "textbox", "name": "Password"},
            "value": "***",
            "redacted": True,
        },
        {
            "op": "click",
            "id": 3,
            "state": "s2",
            "result": {"state": "s3"},
            "target": {"role": "button", "name": "Sign in"},
        },
        {"op": "scroll", "id": 4, "state": "s3"},
    ],
}


def states(tmp_path):
    (tmp_path / "s2.txt").write_text('  heading "Sign in"\n')
    (tmp_path / "s3.txt").write_text('  heading "Sign in"\n  StaticText "Email or password is incorrect."\n')
    return tmp_path


def test_plan_groups_steps_and_derives_expectations(tmp_path):
    sc, env, skipped = plan(TRACE, states(tmp_path), {1: "#email", 2: "#password", 3: "#submit"})
    assert validate(sc) == []
    assert sc["name"] == "Log in as Alice" and sc["tabs"]["app"]["url"] == "http://app.local/"
    s1, s2 = sc["steps"]
    assert s1["actions"] == [{"navigate": "http://app.local/"}] and s1["expect"] == [{"visible": "#email"}]
    assert s2["actions"] == [
        {"fill": {"selector": "#email", "value": "a@x.io"}},
        {"fill": {"selector": "#password", "value": "${PASSWORD}"}},
        {"click": "#submit"},
    ]
    assert s2["expect"] == [{"url_contains": "/login"}, {"text_contains": {"text": "Email or password is incorrect."}}]
    assert env == ["PASSWORD"] and skipped == ["step 4: unsupported op 'scroll'"]


def test_plan_without_resolve_keeps_readable_placeholders():
    sc, _, _ = plan(TRACE)
    assert sc["steps"][1]["actions"][2] == {"click": "TODO role=button name='Sign in'"}


def test_env_name():
    assert env_name({"name": "API key / token"}) == "API_KEY_TOKEN"
    assert env_name({}) == "SECRET"
