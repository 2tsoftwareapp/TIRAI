"""Round-2 features: decimal db compare, save timeout/pattern, clear, request debug, single_tab,
download/pdf/xlsx checks, dbx auth, header fonts, install.sh explicit reinstall."""

from decimal import Decimal
from pathlib import Path

import pytest

from tirai import db as dbq
from tirai import runner
from tirai import scenario as sc_mod
from tirai.scenario import ScenarioError

# ---------- db numeric compare ----------


def test_db_rows_eq_decimal():
    assert dbq.db_rows_eq([{"amount": "204000.00000"}], [{"amount": 204000}])
    assert dbq.db_rows_eq([["1.50", 2]], [[Decimal("1.5"), 2]])
    assert not dbq.db_rows_eq([{"a": "1"}], [{"a": "2"}])
    assert not dbq.db_rows_eq([{"a": "x"}], [{"a": 1}])
    assert dbq.db_rows_eq({"rows": [{"n": "3.0"}]}, {"rows": [{"n": 3}]})


# ---------- save timeout / pattern / allow_empty ----------


class SaveDriver:
    def __init__(self, values):
        self.values = list(values)
        self.calls = 0

    def evaluate(self, tab, expr):
        self.calls += 1
        v = self.values.pop(0) if self.values else {"s": "missing"}
        if isinstance(v, str):
            return {"s": "ok", "v": v}
        return v

    def __getattr__(self, name):
        return lambda *a, **k: None


def make_runner(driver, timeout=5):
    r = runner.Runner.__new__(runner.Runner)
    r.b = driver
    r.tabs = {"app": "t1"}
    r.vars = {}
    r.saved = {}
    r.targets = None
    r.expect_timeout = timeout
    r.sc = {}
    r.pause = lambda s: None
    r.page = lambda tab, expr: driver.evaluate(r.tabs[tab], expr)
    return r


def test_save_waits_for_non_empty():
    d = SaveDriver(["", {"s": "ok", "v": "ORD-9"}])
    r = make_runner(d)
    r.save("app", {"name": "order", "selector": "#o"})
    assert r.vars["order"] == "ORD-9"


def test_save_times_out_on_empty():
    d = SaveDriver(["", {"s": "ok", "v": ""}])
    r = make_runner(d, timeout=0)
    with pytest.raises(ScenarioError, match="still empty"):
        r.save("app", {"name": "order", "selector": "#o"})


def test_save_allow_empty_and_pattern():
    d = SaveDriver(["no digits"])
    r = make_runner(d)
    # the fake does not evaluate the regex: simulate the page reporting a miss, then a capture
    d.values = [{"s": "miss", "v": "no digits"}, {"s": "ok", "v": "123"}]
    r.save("app", {"name": "x", "selector": "#o", "pattern": "(\\d+)"})
    assert r.vars["x"] == "123"


# ---------- clear action ----------


def test_clear_presses_select_all_and_backspace(monkeypatch, tmp_path):
    from test_runner import FakeDriver

    d = FakeDriver()
    monkeypatch.setattr(runner, "make_driver", lambda *a, **k: d)
    monkeypatch.setenv("TIRAI_TIMING_SCALE", "0")
    monkeypatch.setenv("TIRAI_EXPECT_TIMEOUT", "0")
    sc = {
        "name": "x",
        "tabs": {"app": {"url": "http://a"}},
        "steps": [{"id": "S1", "tab": "app", "title": "t", "actions": [{"clear": "#date"}]}],
    }
    tl = runner.run(sc, tmp_path, record=False, hold=0)
    presses = [c for c in d.calls if c[0] == "press"]
    assert ("press", "t1", "Ctrl+A", "#date") in presses
    assert ("press", "t1", "Backspace", "#date") in presses
    assert tl["steps"][0]["status"] == "passed"


# ---------- single_tab setting ----------


def write_scenario(tmp_path, body):
    p = tmp_path / "s.yaml"
    p.write_text(body)
    return sc_mod.load(p)


def test_single_tab_setting_validated(tmp_path):
    sc = write_scenario(
        tmp_path,
        "name: x\nsettings:\n  single_tab: yes\ntabs:\n  app: {url: http://a}\n"
        "steps:\n  - id: S1\n    tab: app\n    title: t\n    expect: [{visible: body}]\n",
    )
    assert sc["settings"]["single_tab"] is True
    bad = (
        "name: x\nsettings:\n  single_tab: maybe\ntabs:\n  app: {url: http://a}\n"
        "steps:\n  - id: S1\n    tab: app\n    title: t\n    expect: [{visible: body}]\n"
    )
    p = tmp_path / "bad.yaml"
    p.write_text(bad)
    with pytest.raises(ScenarioError):
        sc_mod.load(p)


def test_apply_single_tab_only_when_enabled():
    r = make_runner(SaveDriver([]))
    r.settings = {}
    r.apply_single_tab("app")  # no-op without the setting
    r.settings = {"single_tab": True}
    seen = []
    r.page = lambda tab, expr: seen.append(expr)
    r.apply_single_tab("app")
    assert seen and "window.open" in seen[0]


# ---------- download action ----------


class MinimalDriver:
    """No `download` method: bsk-like."""

    def evaluate(self, tab, expr):
        return None


def test_download_requires_agent_browser():
    r = make_runner(MinimalDriver())
    with pytest.raises(ScenarioError, match="agent-browser"):
        r.download("app", {"selector": "#dl", "path": "r.pdf"})


def test_download_saves_into_downloads_dir(tmp_path):
    class DL(MinimalDriver):
        def download(self, tab, sel, path):
            Path(path).write_bytes(b"PDF")

    r = make_runner(DL())
    r.out = tmp_path
    r._step_id = "S1"
    r.downloads = []
    r.download("app", {"selector": "#dl", "path": "report.pdf"})
    assert (tmp_path / "downloads" / "report.pdf").read_bytes() == b"PDF"
    assert r.downloads[0]["file"] == "report.pdf"
    assert r.downloads[0]["step"] == "S1"


# ---------- pdf / xlsx checks ----------


def make_pdf(path, pages=2):
    from pypdf import PdfWriter

    w = PdfWriter()
    for _ in range(pages):
        w.add_blank_page(width=200, height=200)
    with open(path, "wb") as f:
        w.write(f)


def test_check_pdf_pages(tmp_path):
    pytest.importorskip("pypdf", reason="needs tirai[pdf]")
    from tirai.filescheck import check_pdf, pdf_page_count

    p = tmp_path / "r.pdf"
    make_pdf(p, 2)
    assert pdf_page_count(p) == 2
    assert check_pdf(p, {"pages": 2})["ok"]
    assert not check_pdf(p, {"pages": 3})["ok"]
    assert check_pdf(p, {"pages": [1, 3]})["ok"]
    assert not check_pdf(p, {"pages": [3, 5]})["ok"]
    assert not check_pdf(p, {"contains": "hello"})["ok"]


def test_check_xlsx(tmp_path):
    openpyxl = pytest.importorskip("openpyxl", reason="needs tirai[excel]")
    from tirai.filescheck import check_xlsx

    p = tmp_path / "r.xlsx"
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Orders"
    ws.append(["order", "amount"])
    ws.append(["A-1", 204000])
    wb.save(p)
    assert check_xlsx(p, {"sheets": ["Orders"], "contains": "A-1"})["ok"]
    assert not check_xlsx(p, {"sheets": ["Nope"]})["ok"]
    assert not check_xlsx(p, {"contains": "ZZZ"})["ok"]


# ---------- scenario validation for new vocabulary ----------


def test_pdf_xlsx_args_validated(tmp_path):
    ok = (
        "name: x\ntabs:\n  app: {url: http://a}\n"
        "steps:\n  - id: S1\n    tab: app\n    title: t\n"
        "    expect:\n      - pdf: {path: r.pdf, pages: [1, 3]}\n"
    )
    write_scenario(tmp_path, ok)
    bad = ok.replace("pages: [1, 3]", "pages: 1.5")
    p = tmp_path / "bad.yaml"
    p.write_text(bad)
    with pytest.raises(ScenarioError):
        sc_mod.load(p)
    bad2 = ok.replace("path: r.pdf", "path: r.pdf\n        bogus: 1")
    p.write_text(bad2)
    with pytest.raises(ScenarioError):
        sc_mod.load(p)


def test_clear_and_download_in_actions():
    assert "clear" in sc_mod.ACTIONS and "download" in sc_mod.ACTIONS
    assert "pdf" in sc_mod.EXPECTS and "xlsx" in sc_mod.EXPECTS


# ---------- dbx auth ----------


def test_dbx_auth_parses_endpoint(monkeypatch):
    from tirai import system

    class R:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return b'{"authenticated": false, "required": true}'

    monkeypatch.setattr(system.urllib.request, "urlopen", lambda *a, **k: R()) if hasattr(system, "urllib") else None
    import urllib.request

    monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **k: R())
    assert system.dbx_auth("http://x:4224") == (True, False, True)

    def boom(*a, **k):
        raise OSError("down")

    monkeypatch.setattr(urllib.request, "urlopen", boom)
    assert system.dbx_auth("http://x:4224") == (False, False, False)


# ---------- header fonts ----------


def test_header_fonts_warn_on_cjk_without_cjk_font(monkeypatch):
    from tirai import system

    dejavu = system.find_font(False)
    assert dejavu, "test needs a Latin font"
    monkeypatch.setenv("TIRAI_FONT_HEADER", dejavu)  # env override is authoritative
    monkeypatch.delenv("TIRAI_FONT_HEADER_BOLD", raising=False)
    path, missing = system.header_fonts(["受注番号を確認"], False)
    assert path == dejavu
    if system.font_covers(dejavu, "受注番号を確認") is False:
        assert missing, "CJK text with a Latin-only font must report missing glyphs"
    else:
        assert missing == ""


def test_header_fonts_env_override(monkeypatch):
    from tirai import system

    f = system.find_font(False)
    monkeypatch.setenv("TIRAI_FONT_HEADER", f)
    path, _ = system.header_fonts(["plain ascii"], False)
    assert path == f


# ---------- install.sh explicit --source reinstalls ----------


def test_install_sh_source_flag_bypasses_skip():
    sh = (Path(__file__).parent.parent / "install.sh").read_text()
    assert "EXPLICIT=1" in sh
    assert '[ "$EXPLICIT" = 0 ]' in sh
