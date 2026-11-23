from tirai import compose


def test_follow_pans_between_action_targets():
    z = {"follow": [{"t": 2.0, "rect": [0, 0, 100, 40], "viewport": [1280, 720]},
                    {"t": 4.0, "rect": [600, 300, 100, 40], "viewport": [1280, 720]}], "factor": 1.6}  # fmt: skip
    f = compose.follow_filter(z, (1280, 720), clip_start=1.0)
    assert f.startswith("scale=iw*2:ih*2,zoompan=") and "+(1200.0)*" in f and "1+0.600*" in f


def test_warp_shortens_waits_and_places_badges():
    expr, saved, shown = compose.warp([[3.0, 7.0, 4]], clip_start=1.0)
    assert "setpts=" in expr and abs(saved - 3.0) < 1e-9
    assert shown == [(2.0, 3.0, 4)]
    assert compose.warp(None, 0) == ("", 0.0, [])
