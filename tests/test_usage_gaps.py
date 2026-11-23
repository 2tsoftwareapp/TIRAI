"""Gaps found in real use: write guard, loops, inline checks, popups, resume, diagnostics, friendlier errors."""

import json

import pytest
from test_runner import FakeDriver, scenario

from tirai import cli, compose, mcp, report, runner
from tirai.install import destinations
from tirai.scenario import ScenarioError, expand, js_regex_problem, load, sql_writes, step_writes, validate


@pytest.fixture
def fake(monkeypatch):
    holder = {}

    def make(name=None, session=None, headed=None):
        holder["d"] = holder.get("proto") or FakeDriver()
        return holder["d"]

    monkeypatch.setattr(runner, "make_driver", make)
    monkeypatch.setenv("TIRAI_TIMING_SCALE", "0")
    monkeypatch.setenv("TIRAI_EXPECT_TIMEOUT", "0")
    return holder


def step(sid, **kw):
    return {"id": sid, "tab": "app", "title": sid, "expect": [{"visible": "#a"}], **kw}


def sc_with(*steps, **extra):
    return {"name": "x", "tabs": {"app": {"url": "http://a"}}, "steps": list(steps), **extra}


# ---------- scenario ----------
def test_for_each_expands_one_step_per_item():
    sc = expand(
        sc_with(
            step(
                "LINE",
                for_each="lines",
                title="line {{index}}",
                actions=[{"fill": {"selector": "#c", "value": "{{code}}"}}],
            ),
            vars={"lines": [{"code": "A1"}, {"code": "B2"}]},
        )
    )
    assert [s["id"] for s in sc["steps"]] == ["LINE-1", "LINE-2"]
    assert [s["title"] for s in sc["steps"]] == ["line 1", "line 2"]
    assert sc["steps"][1]["actions"][0]["fill"]["value"] == "B2"
    scalars = expand(sc_with(step("S", for_each=["x", "y"], **{"as": "v"}, title="{{v}}")))
    assert [s["title"] for s in scalars["steps"]] == ["x", "y"]
    with pytest.raises(ScenarioError, match="not a list"):
        expand(sc_with(step("S", for_each="nope")))


def test_once_last_runs_after_the_last_case():
    sc = expand(sc_with(step("ADD"), step("SAVE", once="last", title="N{{n}}"), cases=[{"n": 1}, {"n": 2}]))
    assert [s["id"] for s in sc["steps"]] == ["ADD-1", "ADD-2", "SAVE"]
    assert sc["steps"][-1]["title"] == "N2"


@pytest.mark.parametrize(
    "st, fragment",
    [
        (step("S", actions=[{"click": '.x:has-text("A")'}]), "Playwright-only selector syntax"),
        (step("S", expect=[{"visible": "a >> b"}]), "Playwright-only"),
        (step("S", sav={"name": "x"}), "unknown sav"),
        (step("S", once="sometimes"), "once must be"),
        (step("S", expect=[{"text_matches": {"pattern": "("}}]), "invalid pattern"),
        (step("S", actions=[{"expect": {"count": {"selector": "li"}}}]), "count is missing equals"),
        (step("S", save={"selector": "#x"}), "save is missing name"),
        (step("S", actions=[{"wait_for": {"timeout": 1}}]), "wait_for needs a selector or idle"),
    ],
)
def test_validation_catches_real_use_mistakes(st, fragment):
    assert any(fragment in p for p in validate(sc_with(st))), validate(sc_with(st))


def test_db_unknown_keys_and_settings_are_rejected():
    sc = sc_with(
        step("S", expect=[{"db": {"sql": "select 1", "rows": [], "bogus": 1}}]),
        databases={"default": {"dsn": "sqlite:///x"}},
        settings={"viewport": {"width": "wide"}},
    )
    problems = validate(sc)
    assert any("db has unknown bogus" in p for p in problems)
    assert any("settings.viewport" in p for p in problems)


def test_inline_expect_satisfies_expect_requirement_and_popup_tabs_need_no_url():
    st = {"id": "S", "tab": "child", "title": "t", "actions": [{"expect": {"visible": "#a"}}]}
    assert validate({"name": "x", "tabs": {"child": {"popup": True}}, "steps": [st]}) == []


def test_js_regex_forms_are_accepted():
    assert js_regex_problem("([^]*)") is None
    assert js_regex_problem("(?<n>a)\\k<n>") is None
    assert js_regex_problem("(") is not None


def test_yaml_error_points_at_unquoted_env_var(tmp_path):
    f = tmp_path / "s.yaml"
    f.write_text("name: x\nsteps:\n  - fill: { selector: '#u', value: ${APP_USER} }\n")
    with pytest.raises(ScenarioError) as e:
        load(f)
    assert "s.yaml:3:" in str(e.value) and 'value: "${APP_USER}"' in str(e.value)


def test_writes_detection():
    assert sql_writes("-- note\nUPDATE users SET x=1") and not sql_writes("SELECT * FROM t -- update later")
    assert step_writes({"writes": "creates an order"}) == "creates an order"
    assert step_writes({"writes": True}) == "writes data"
    assert step_writes({"actions": [{"sql": "delete from t"}]}).startswith("sql: delete")
    assert step_writes({"actions": [{"sql": "select 1"}]}) is None


# ---------- runner ----------
def test_dry_run_stops_before_writes_unless_allowed(fake, tmp_path):
    sc = scenario()
    sc["steps"][1]["writes"] = "creates an order"
    sc["cleanup"] = [{"tab": "app", "actions": [{"click": "#undo"}]}]
    tl = runner.run(sc, tmp_path, record=False, hold=0)
    assert [s["id"] for s in tl["steps"]] == ["S1"]
    assert tl["stopped"] == {"before": "S2", "reason": "writes data (creates an order)"}
    assert ("click", "t1", "#undo") not in fake["d"].calls  # nothing written, nothing to clean up
    assert cli._summary(tl) == 0
    tl = runner.run(sc, tmp_path, record=False, hold=0, allow_writes=True)
    assert len(tl["steps"]) == 3 and tl["steps"][1]["writes"] == "creates an order"
    assert tl["cleanup"][0]["status"] == "passed" and ("click", "t1", "#undo") in fake["d"].calls
    rec = runner.run(sc, tmp_path, record=True, hold=0)
    assert len(rec["steps"]) == 3  # a recording always runs the write


def test_until_stops_after_the_step_family(fake, tmp_path):
    sc = scenario()
    sc["steps"][0]["id"] = "S1-1"
    tl = runner.run(sc, tmp_path, record=False, hold=0, until="S1")
    assert [s["id"] for s in tl["steps"]] == ["S1-1"] and tl["stopped"]["after"] == "S1-1"
    assert cli._summary(tl) == 0


def test_failed_inline_expect_halts_the_step(fake, tmp_path):
    fake["proto"] = FakeDriver(ok=False)
    sc = scenario()
    sc["steps"][0]["actions"] = [{"expect": {"visible": "#x"}}, {"click": "#never"}]
    tl = runner.run(sc, tmp_path, record=False, hold=0)
    assert tl["steps"][0]["status"] == "failed" and len(tl["steps"][0]["checks"]) == 1
    assert ("click", "t1", "#never") not in fake["d"].calls


def test_step_level_save(fake, tmp_path):
    sc = scenario()
    sc["steps"][0]["save"] = {"name": "order", "selector": "#order"}
    sc["steps"][2]["actions"] = [{"fill": {"selector": "#q", "value": "{{order}}"}}]
    tl = runner.run(sc, tmp_path, record=False, hold=0)
    assert tl["steps"][0]["saved"] == {"order": "ORD-42"}


class TabsDriver(FakeDriver):
    def __init__(self):
        super().__init__()
        self.tabs = [{"id": "t1", "url": "http://app.test/"}]
        self.viewports = []

    def tab_list(self):
        return list(self.tabs)

    def set_viewport(self, tab, w, h):
        self.viewports.append((tab, w, h))

    def click(self, tab, selector):
        super().click(tab, selector)
        if selector == "#open":
            self.tabs.append({"id": "t9", "url": "http://app.test/child"})


def test_popup_tab_binds_to_the_window_the_page_opened(fake, tmp_path):
    fake["proto"] = TabsDriver()
    sc = {
        "name": "p",
        "settings": {"viewport": {"width": 1400, "height": 800}},
        "tabs": {"app": {"url": "http://app.test/"}, "child": {"popup": True, "match": "/child"}},
        "steps": [
            {"id": "S1", "tab": "app", "title": "open", "actions": [{"click": "#open"}], "expect": [{"visible": "a"}]},
            {"id": "S2", "tab": "child", "title": "child", "actions": [{"click": "#in"}], "expect": [{"visible": "a"}]},
        ],
    }
    tl = runner.run(sc, tmp_path, record=False, hold=0)
    assert [s["status"] for s in tl["steps"]] == ["passed", "passed"]
    assert ("click", "t9", "#in") in fake["d"].calls
    assert fake["d"].viewports == [("t1", 1400, 800), ("t9", 1400, 800)]


def test_from_step_reuses_open_tab_and_saved_values(fake, tmp_path):
    d = TabsDriver()
    d.session = "kept"
    fake["proto"] = d
    (tmp_path / "timeline.json").write_text(json.dumps({"steps": [{"saved": {"order": "ORD-7"}}]}))
    sc = scenario()
    sc["steps"][2]["actions"] = [{"fill": {"selector": "#q", "value": "{{order}}"}}]
    sc["tabs"] = {"app": {"url": "http://app.test/", "setup": [{"click": "#login"}]}}
    for st in sc["steps"]:
        st["tab"] = "app"
    tl = runner.run(sc, tmp_path, record=False, hold=0, session="kept", from_step="S3")
    assert [s["id"] for s in tl["steps"]] == ["S3"] and tl["total_steps"] == 1
    assert ("fill", "t1", "#q", "ORD-7") in d.calls
    assert not any(c[0] in ("tab_create", "open_session") for c in d.calls)
    assert ("click", "t1", "#login") not in d.calls  # setup already happened in the kept session
    assert runner.previous_vars(tmp_path) == {"order": "ORD-7"}


def test_db_save_unknown_column_is_an_error(fake, tmp_path, monkeypatch):
    monkeypatch.setattr(runner.dbq, "query", lambda dsn, sql: [(8,)])
    sc = scenario(databases={"default": {"dsn": "sqlite:///x"}})
    sc["steps"][0]["expect"] = [{"db": {"sql": "select count(*)", "rows": [{"cnt": 8}], "save": {"rows": "count"}}}]
    tl = runner.run(sc, tmp_path, record=False, hold=0)
    assert tl["steps"][0]["status"] == "error" and "no column 'count'" in tl["steps"][0]["error"]


# ---------- compose / report ----------
def test_still_spans_keep_step_start_and_hold():
    st = {"start": 1.0, "end": 20.0, "idle": [[2.0, 4.0, 4]]}
    compose.add_still_spans(st, [(3.0, 6.0), (6.0, 15.0), (16.0, 20.0)], hold=2.5)
    assert st["idle"] == [[2.0, 4.0, 4], [6.3, 14.7, compose.STILL_SPEED]]


def test_report_lists_writes_requests_and_cleanup():
    tl = {
        "steps": [
            {"id": "S", "writes": "creates an order", "saved": {"orderNo": "18"}, "failed_requests": ["401 /api/me"]},
        ],
        "cleanup": [{"id": "C1", "status": "passed"}],
    }
    md = "\n".join(report.extra_md(tl))
    assert "| S | creates an order | orderNo=18 |" in md and "`401 /api/me`" in md and "C1: PASSED" in md
    assert "Data written" in report._extra_html(tl)


# ---------- cli / install / mcp ----------
def test_init_adds_gitignore_once(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".gitignore").write_text("node_modules/\n")
    gi, added = cli.ensure_gitignore(tmp_path / "s" / "x.yaml")
    assert added == ["**/.env", "evidence/"] and "node_modules/" in gi.read_text()
    assert cli.ensure_gitignore(tmp_path / "s" / "x.yaml") is None


def test_agents_skill_dir_and_mcp_flags():
    assert destinations(["agents"])[0].parts[-2:] == (".agents", "skills")
    argv = mcp.TOOLS["dry_run"][2]({"scenario": "s.yaml", "allow_writes": True, "until": "S3", "session": "k"})
    assert argv[-5:] == ["--allow-writes", "--until", "S3", "--session", "k"]


def test_main_prints_one_line_instead_of_a_traceback(capsys, monkeypatch):
    monkeypatch.delenv("TIRAI_DEBUG", raising=False)
    with pytest.raises(SystemExit) as e:
        cli.main(["compose", "/nonexistent/timeline.json"])
    assert e.value.code == 1 and "TIRAI_DEBUG=1" in capsys.readouterr().err
