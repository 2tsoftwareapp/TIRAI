"""Runner/compose/scenario wiring for annotations: lazy annotate.js injection, fail-closed masking, warnings."""

import types

from tirai import compose, runner, scenario
from tirai.resources import annotate_js, annotate_version


class Page:
    """`evaluate` stand-in: a page that has annotate.js once the full source was sent."""

    def __init__(self, loaded=False, answer="ok"):
        self.loaded, self.answer, self.exprs = loaded, answer, []

    def evaluate(self, tab, expr):
        self.exprs.append(expr)
        if "const VERSION" in expr:
            self.loaded = True
        elif runner.ANN_MISSING in expr and not self.loaded:
            return runner.ANN_MISSING
        return self.answer


def stub(page, **attrs):
    s = types.SimpleNamespace(b=page, tabs={"app": "t1"}, targets={}, warnings=[], **attrs)
    s.page = lambda tab, expr: page.evaluate(s.tabs[tab], expr)
    s.ann = lambda tab, body, tagged=False: runner.Runner.ann(s, tab, body, tagged)
    return s


def test_ann_sends_source_only_when_page_lacks_it():
    page = Page()
    s = stub(page)
    assert s.ann("app", "return 1") == "ok"
    assert s.ann("app", "return 2") == "ok"
    sent = [e for e in page.exprs if "const VERSION" in e]
    assert len(sent) == 1 and len(page.exprs) == 3  # probe, probe+source, probe only
    assert annotate_version() in page.exprs[0]


def test_privacy_init_script_fails_closed():
    s = types.SimpleNamespace(
        sc={"tabs": {"app": {"url": "http://app.test/"}}},
        privacy_config=lambda: {"mask": ["email"]},
    )
    script = runner.Runner.privacy_init_script(s)
    assert script.startswith(annotate_js())
    tail = script[len(annotate_js()) :]
    assert "catch(e){}" not in tail
    assert "mask-failsafe" in tail and "__tiraiMaskError" in tail


def test_expect_box_that_cannot_be_drawn_becomes_a_warning(monkeypatch):
    monkeypatch.setattr(runner.time, "sleep", lambda s: None)
    page = Page(loaded=True, answer="annotate: target not found: #gone")
    s = stub(
        page,
        record=True,
        theme={},
        expect_pos="top-right",
        _ann_theme_cfg=lambda: {},
        _format_expect_row=lambda tab, exp, res: {"ok": True, "label": "visible"},
    )
    s._expect_selector = lambda kind, arg: runner.Runner._expect_selector(s, kind, arg)
    runner.Runner._show_expect_result(s, "app", [], {"visible": "#gone"}, {"ok": True}, 0)
    assert s.warnings == ["expect box not drawn: annotate: target not found: #gone"]
    assert "catch(e){w=" in page.exprs[-1]


def test_badge_without_n_numbers_itself():
    page = Page(loaded=True, answer=["badge-1"])
    s = stub(page, theme={}, _ann_theme_cfg=lambda: {})
    runner.Runner.annotate(s, "app", [{"badge": {"target": "#a", "pos": "top-right"}}])
    assert '__ann.badge("#a","auto",{"pos": "top-right"})' in page.exprs[-1]


def test_fit_subtitle_size_shrinks_only_when_band_overflows():
    assert compose.fit_subtitle_size("short", 1280, 24, 84) == 24
    long_vi = "Kiểm tra màn hình đăng nhập với email sai định dạng và xác nhận thông báo lỗi " * 4
    fs = compose.fit_subtitle_size(long_vi, 1280, 24, 84)
    assert 14 <= fs < 24
    assert compose.fit_subtitle_size("日本語の字幕" * 80, 1280, 24, 84) == 14
    assert compose.fit_subtitle_size("one\ntwo\nthree", 1280, 24, 84) < 24  # three short lines


def test_header_shows_step_progress():
    tl = {
        "scenario": "s",
        "created": "now",
        "tabs": {"app": {"label": "App"}},
        "steps": [
            {"id": "S1", "tab": "app", "title": "a", "status": "passed", "final_start": 1, "final_end": 2},
            {"id": "S2", "tab": "app", "title": "b", "status": "passed", "final_start": 2, "final_end": 3},
        ],
    }
    ass = compose.build_ass(tl, (1280, 720), 1.0)
    assert "2/2   S2" in ass and "1/2   S1" in ass


def test_validate_annotation_style_and_badge_pos():
    def errs(item):
        sc = {
            "name": "x",
            "tabs": {"app": {"url": "http://a.test/"}},
            "steps": [{"id": "S1", "tab": "app", "title": "t", "actions": [], "expect": [], "annotate": [item]}],
        }
        return [e for e in scenario.validate(sc) if "annotate" in e]

    assert errs({"underline": {"target": "#a", "style": "success"}}) == []
    assert errs({"box": {"target": "#a", "style": "loud"}})
    assert errs({"badge": {"target": "#a", "pos": "middle"}})


def test_mask_that_cannot_start_fails_the_step(monkeypatch, tmp_path):
    from test_runner import FakeDriver, scenario

    class MaskFails(FakeDriver):
        def evaluate(self, tab, expr):
            if "__ann.mask(" in expr:
                return {"maskError": "bad pattern"}
            return super().evaluate(tab, expr)

    monkeypatch.setattr(runner, "make_driver", lambda *a, **k: MaskFails())
    monkeypatch.setenv("TIRAI_TIMING_SCALE", "0")
    monkeypatch.setenv("TIRAI_EXPECT_TIMEOUT", "0")
    tl = runner.run(scenario(privacy={"mask": ["email"]}), tmp_path, record=False, hold=0)
    assert tl["steps"][0]["status"] == "error"
    assert "masking could not start: bad pattern" in tl["steps"][0]["error"]


def _tl(n=2, **extra):
    steps = [
        {"id": f"S{i}", "tab": "app", "title": f"t{i}", "status": "failed" if i == 2 else "passed",
         "final_start": i, "final_end": i + 1}
        for i in range(1, n + 1)
    ]  # fmt: skip
    return {"scenario": "s", "created": "now", "tabs": {"app": {"label": "App"}}, "steps": steps, **extra}


def test_scale_theme_grows_defaults_but_keeps_explicit_sizes():
    tl = _tl(theme={"subtitle_size": 30})
    compose.scale_theme(tl, (1920, 1080))
    th = compose.resolve_theme(tl)
    assert th["header_height"] == 60 and th["header_size"] == 30 and th["subtitle_height"] == 126
    assert th["subtitle_size"] == 30  # set by the scenario
    small = _tl()
    compose.scale_theme(small, (1280, 600))
    assert compose.resolve_theme(small)["header_height"] == compose.TOP  # never shrinks below the 720p design


def test_status_badge_scales_with_chrome():
    th = compose.resolve_theme({"theme": {"chrome_scale": 1.5}})
    badge = compose.status_badge(th, 60, "st.txt", ok=False)
    assert "w=120:h=42" in badge and "fontsize=27" in badge and "0xdc2626" in badge.lower()


def test_title_card_meta_and_summary_card():
    tl = _tl(meta={"ticket": "#12", "env": "staging"}, summary={"start": 3.0, "end": 7.0})
    ass = compose.build_ass(tl, (1280, 720), 1.0)
    assert "ticket: #12  ·  env: staging" in ass
    assert "1/2 steps passed" in ass and "FAIL" in ass
    assert "✓" in ass and "✗" in ass and "0:00:03.00" in ass


def test_summary_rows_put_failures_first_when_they_do_not_fit():
    steps = [{"id": f"S{i}", "status": "failed" if i == 9 else "passed"} for i in range(1, 10)]
    rows, more = compose.summary_rows(steps, 4)
    assert rows[0]["id"] == "S9" and len(rows) == 3 and more == 6
    assert compose.summary_rows(steps, 20) == (steps, 0)


def test_chapters_include_summary(tmp_path):
    tl = _tl(summary={"start": 3.0, "end": 7.0})
    for s in tl["steps"]:
        s["title"] = s["id"]
    name = compose.chapters_file(tmp_path, tl, 1.0)
    assert "title=Summary" in (tmp_path / name).read_text()


def test_validate_meta_and_new_shapes():
    def errs(annotate=(), **top):
        sc = {
            "name": "x",
            "tabs": {"app": {"url": "http://a.test/"}},
            "steps": [{"id": "S1", "tab": "app", "title": "t", "actions": [], "annotate": list(annotate)}],
            **top,
        }
        return [e for e in scenario.validate(sc) if e.startswith(("meta", "settings")) or "annotate" in e]

    assert errs(meta={"ticket": "#1", "build": 42}) == []
    assert errs(meta={"token": "${SECRET}"})
    assert errs(meta=["x"])
    assert errs(settings={"summary_card": "no"})
    assert errs([{"callout": {"target": "#a", "label": "x"}}, {"magnify": {"target": "#a", "factor": 2}}]) == []
    bad = [
        {"callout": {"target": "#a"}},
        {"magnify": {"target": "#a", "factor": 9}},
        {"arrow": {"target": "#a", "curve": 2}},
    ]
    assert len(errs(bad)) == 3


def test_summary_rows_truncate_cjk_titles_to_the_column():
    long_jp = "受注一覧画面で検索条件を入力して結果を確認する" * 3
    assert compose.text_em(compose.clip_em(long_jp, 20)) <= 20
    assert compose.clip_em("short", 20) == "short"
    steps = [{"id": f"S{i}", "tab": "app", "title": long_jp, "status": "passed", "final_start": i, "final_end": i + 1}
             for i in range(1, 41)]  # fmt: skip
    tl = {"scenario": "s", "created": "now", "tabs": {"app": {"label": "App"}}, "steps": steps,
          "summary": {"start": 41.0, "end": 45.0}}  # fmt: skip
    rows = [line for line in compose.build_ass(tl, (1280, 720), 1.0).splitlines() if ",Row," in line]
    assert rows and all("…" in r for r in rows if "受注" in r)
