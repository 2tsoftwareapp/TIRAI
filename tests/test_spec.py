from tirai import scenario, spec

FEATURE = """Feature: Lock
  Scenario Outline: wrong password
    Given the user opens "${APP_URL}"
    When the user enters "<email>" into "Email"
    And the user clicks "Sign in"
    Then the user should see "Invalid"
    And a human checks the colour
    Examples:
      | email |
      | a@b.c |
"""


def test_gherkin_to_scenario_with_cases(tmp_path):
    f = tmp_path / "x.feature"
    f.write_text(FEATURE)
    sc, unmatched, unresolved = spec.build(f)
    st = sc["steps"][0]
    assert st["actions"][0] == {"navigate": "${APP_URL}"}
    assert st["actions"][1] == {"fill": {"selector": "TODO(Email)", "value": "{{email}}"}}
    assert st["expect"] == [{"text_contains": {"text": "Invalid"}}]
    assert sc["cases"] == [{"email": "a@b.c"}]
    assert unresolved == ["Email", "Sign in"] and unmatched == ["And a human checks the colour"]
    assert scenario.validate(sc) == []


def test_markdown_table_and_sql_goes_to_db_tab(tmp_path):
    f = tmp_path / "c.md"
    f.write_text(
        "# Login\n| Test case | Steps | Expected result |\n|---|---|---|\n"
        '| Bad | Enter "x" into "Email"; Click "Go" | Should see "Invalid" |\n'
        "| DB | Run query `select 1` | `1` |\n"
    )
    sc, _, _ = spec.build(f)
    assert sc["name"] == "Login" and len(sc["steps"]) == 2
    assert sc["steps"][1]["tab"] == "db" and "db" in sc["tabs"]


def test_resolve_replaces_todo_with_live_selectors(tmp_path, monkeypatch):
    f = tmp_path / "x.feature"
    f.write_text(FEATURE)
    monkeypatch.setattr(spec, "resolve", lambda url, names: {"Email": "#email"})
    sc, _, unresolved = spec.build(f, url="http://app")
    assert sc["steps"][0]["actions"][1]["fill"]["selector"] == "#email" and unresolved == ["Sign in"]
