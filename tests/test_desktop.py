from tirai import desktop


def test_selectors_and_envelope_parsing():
    assert desktop.parse_selector("button:7") == {"role": "button", "name": "7", "exact": True}
    assert desktop.parse_selector("Save as") == {"name": "Save as", "exact": True}
    assert desktop.parse_selector({"role": "textfield"}) == {"role": "textfield"}
    found = {"match": {"name": "7", "ref_id": "@s1:e1", "role": "button"}, "snapshot_id": "s1"}
    assert desktop.first_ref(found) == "@s1:e1"
    got = {"property": "bounds", "value": {"height": 44.0, "width": 63.0, "x": 473.0, "y": 466.0}}
    assert desktop.bounds_of(got) == (473, 466, 63, 44)


def test_mixed_driver_routes_app_tabs(monkeypatch):
    calls = []

    class Browser:
        name, session = "agent-browser", None

        def click(self, tab, sel):
            calls.append(("browser", tab, sel))

    d = desktop.AgentDesktop()
    monkeypatch.setattr(d, "click", lambda tab, sel: calls.append(("desk", tab, sel)))
    m = desktop.MixedDriver(Browser, d)
    assert m.name == "agent-desktop"
    m.click("app:calc", "button:7")
    m.click("t1", "#go")
    assert calls == [("desk", "app:calc", "button:7"), ("browser", "t1", "#go")]
    assert m.name == "agent-browser+agent-desktop"
