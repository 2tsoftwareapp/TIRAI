from tirai import ocr


def words(*items):
    return [(("1", "1", str(line)), text, box) for line, text, box in items]


def test_hit_box_spans_the_matched_words_only():
    w = words((1, "user", (10, 10, 30, 10)), (1, "bob@demo.local", (50, 10, 90, 10)), (1, "ok", (150, 10, 15, 10)))
    hits = ocr.find_hits(w, ocr.rules_regex(["email"]))
    assert hits == [("bob@demo.local", (50, 10, 90, 10))]


def test_phone_split_across_words_and_keep_list():
    w = words(
        (1, "+84", (0, 0, 20, 10)),
        (1, "912", (25, 0, 20, 10)),
        (1, "345", (50, 0, 20, 10)),
        (1, "678", (75, 0, 20, 10)),
    )
    assert ocr.find_hits(w, ocr.rules_regex(["phone"]))[0][1] == (0, 0, 95, 10)
    assert ocr.find_hits(w, ocr.rules_regex(["phone"]), keep={"+84 912 345 678"}) == []


def test_regions_merge_consecutive_frames_and_hide_text():
    hits = [
        {"t": 1.0, "box": [100, 50, 80, 12]},
        {"t": 2.0, "box": [102, 50, 80, 12]},
        {"t": 9.0, "box": [500, 50, 80, 12]},
    ]
    regs = ocr.regions(hits)
    assert len(regs) == 2 and regs[0][4:] == (0.0, 3.0)
    assert ocr.hide("bob@demo.local").startswith("bo") and "demo" not in ocr.hide("bob@demo.local")
