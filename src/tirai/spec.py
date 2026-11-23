"""Draft a scenario from a written test spec: Gherkin `.feature`, a Markdown table or CSV test cases.

The draft is a starting point for an agent: plain-language steps become actions/expectations by
pattern, element names become `TODO(name)` selectors unless `--url` lets TIRAI resolve them on the
live page (accessibility role + name -> unique CSS selector). Lines that match no pattern are kept
in the step's `subtitle` and listed so nothing from the spec is silently dropped.
"""

import csv
import io
import json
import re
from pathlib import Path

import yaml

Q = r"[\"'“”‘’]([^\"'“”‘’]+)[\"'“”‘’]"
GHERKIN_KW = r"^(Given|When|Then|And|But|\*|Cho|Khi|Thì|Và|Nhưng)\s+"
RULES = [
    (
        "navigate",
        rf"(?:opens?|goes to|go to|navigates? to|visits?|is on|mở|truy cập|vào trang)\s+(?:the\s+)?(?:page\s+)?{Q}",
    ),
    ("navigate", r"(?:opens?|go to|navigates? to|visits?|mở|truy cập)\s+(?:the\s+)?(\S+://\S+|\$\{\w+\})"),
    (
        "fill",
        rf"(?:enters?|types?|fills?(?: in)?|inputs?|nhập|điền)\s+{Q}\s+(?:in|into|as|for|vào|cho)\s+(?:the\s+)?{Q}",
    ),
    ("fill_with", rf"(?:fills?(?: in)?|enters?|nhập|điền)\s+(?:the\s+)?{Q}\s+(?:with|bằng|là)\s+{Q}"),
    ("select", rf"(?:selects?|chooses?|chọn)\s+{Q}\s+(?:in|from|trong)\s+(?:the\s+)?{Q}"),
    ("click", rf"(?:clicks?|press(?:es)?|taps?|submits?|bấm|nhấn|click)\s+(?:on\s+)?(?:the\s+)?(?:nút\s+)?{Q}"),
    ("key", r"(?:press(?:es)?|nhấn phím)\s+(Enter|Tab|Escape|Esc)\b"),
    ("sql", r"(?:runs?|executes?|chạy)?\s*(?:sql|query|truy vấn)\s*:?\s*`([^`]+)`"),
    ("not_text", rf"(?:should not see|does not see|không (?:còn )?thấy|không hiển thị)\s+{Q}"),
    (
        "text",
        rf"(?:should see|sees?|shows?|displays?|is shown|thấy|hiển thị|báo)\s+(?:the\s+)?(?:message\s+|text\s+)?{Q}",
    ),
    ("url", rf"(?:url|redirected to|lands on|chuyển (?:sang|tới)|đến trang)\s+.*?{Q}"),
    ("visible", rf"{Q}\s+(?:is visible|appears|xuất hiện)"),
]


def todo(name):
    return f"TODO({name})"


def parse_line(text):
    """Return (actions, expects) found in one plain-language line; both empty when nothing matched."""
    actions, expects = [], []
    for kind, pat in RULES:
        m = re.search(pat, text, re.I)
        if not m:
            continue
        g = m.groups()
        if kind == "navigate":
            actions.append(
                {"navigate": g[0] if re.match(r"\S+://|\$\{|/", g[0]) else f"${{APP_URL}}/{g[0].lstrip('/')}"}
            )
        elif kind == "fill":
            actions.append({"fill": {"selector": todo(g[1]), "value": g[0]}})
        elif kind == "fill_with":
            actions.append({"fill": {"selector": todo(g[0]), "value": g[1]}})
        elif kind == "select":
            actions.append({"select": {"selector": todo(g[1]), "value": g[0]}})
        elif kind == "click":
            actions.append({"click": todo(g[0])})
        elif kind == "key":
            actions.append({"press": g[0].replace("Esc", "Escape").replace("Escapeape", "Escape")})
        elif kind == "sql":
            actions.append({"sql": g[0]})
        elif kind == "not_text":
            expects.append({"text_matches": {"pattern": f"^(?![\\s\\S]*{re.escape(g[0])})"}})
        elif kind == "text":
            expects.append({"text_contains": {"text": g[0]}})
        elif kind == "url":
            expects.append({"url_contains": g[0]})
        elif kind == "visible":
            expects.append({"visible": todo(g[0])})
        break
    return actions, expects


def _params(text):
    return re.sub(r"<(\w+)>", r"{{\1}}", text)


def from_gherkin(text):
    """Feature -> name; each Scenario -> steps (Given/When lines = actions, Then lines = expect)."""
    name, steps, cases, unmatched = "Spec scenario", [], None, []
    current, phase, scenario_title, table = None, None, "", None

    def flush():
        nonlocal current
        if current and (current["actions"] or current["expect"]):
            steps.append(current)
        current = None

    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if m := re.match(r"^(Feature|Tính năng):\s*(.+)", line):
            name = m.group(2)
        elif m := re.match(r"^(Scenario Outline|Scenario|Example|Kịch bản|Khung kịch bản):\s*(.+)", line):
            flush()
            scenario_title, phase = m.group(2), None
        elif re.match(r"^(Examples|Ví dụ):", line):
            flush()
            table = []
        elif line.startswith("|") and table is not None:
            table.append([c.strip() for c in line.strip("|").split("|")])
        elif m := re.match(GHERKIN_KW, line):
            kw, body = m.group(1), _params(line[m.end() :])
            if kw in ("Then", "Thì"):
                phase = "then"
            elif kw in ("Given", "When", "Cho", "Khi"):
                if phase == "then":
                    flush()
                phase = "do"
            actions, expects = parse_line(body)
            if not actions and not expects:
                unmatched.append(line)
            if current is None:
                current = {"title": scenario_title or body, "lines": [], "actions": [], "expect": []}
            current["lines"].append(body)
            current["actions"] += actions
            current["expect"] += expects
    flush()
    if table and len(table) > 1:
        cases = [dict(zip(table[0], row, strict=False)) for row in table[1:]]
    return name, steps, cases, unmatched


HEADERS = {
    "title": ("title", "test case", "case", "name", "tiêu đề", "tên"),
    "action": ("action", "actions", "step", "steps", "thao tác", "bước", "các bước"),
    "expected": ("expected", "expected result", "kết quả mong đợi", "mong đợi", "kết quả"),
}


def _column(header, key):
    for i, h in enumerate(header):
        if h.strip().lower() in HEADERS[key]:
            return i
    return None


def from_rows(rows):
    header, body = rows[0], rows[1:]
    ia, ie, it = _column(header, "action"), _column(header, "expected"), _column(header, "title")
    if ia is None:
        raise ValueError(f"no action/step column in {header}")
    steps, unmatched = [], []
    for row in body:
        cell = lambda i, row=row: row[i].strip() if i is not None and i < len(row) else ""  # noqa: E731
        act, exp = cell(ia), cell(ie)
        actions, expects = [], []
        for part in re.split(r"<br\s*/?>|\n|;\s*", act):
            a, e = parse_line(part)
            if part.strip() and not (a or e):
                unmatched.append(part.strip())
            actions += a
            expects += e
        for part in re.split(r"<br\s*/?>|\n|;\s*", exp):
            a, e = parse_line(part)
            if part.strip() and not e:
                e = [{"text_contains": {"text": part.strip()}}] if not re.search(r"\s", part.strip()) else []
                if not e:
                    unmatched.append(part.strip())
            expects += e
        steps.append({"title": cell(it) or act[:60], "lines": [act, exp], "actions": actions, "expect": expects})
    return steps, unmatched


def from_markdown(text):
    rows = [
        [c.strip() for c in ln.strip().strip("|").split("|")]
        for ln in text.splitlines()
        if ln.strip().startswith("|") and not re.match(r"^\|?\s*:?-{2,}", ln.strip())
    ]
    if len(rows) < 2:
        raise ValueError("no Markdown table found")
    name = next((ln.lstrip("# ").strip() for ln in text.splitlines() if ln.startswith("#")), "Spec scenario")
    return (name, *from_rows(rows))


def build(path, url=None):
    """Return (scenario dict, unmatched lines, unresolved names)."""
    path = Path(path)
    text = path.read_text(encoding="utf-8-sig")
    cases = None
    if path.suffix == ".feature":
        name, steps, cases, unmatched = from_gherkin(text)
    elif path.suffix == ".csv":
        name, (steps, unmatched) = path.stem, from_rows(list(csv.reader(io.StringIO(text))))
    else:
        name, steps, unmatched = from_markdown(text)
    uses_sql = any("sql" in a for s in steps for a in s["actions"])
    tabs = {"app": {"url": "${APP_URL}", "label": "WEB APP"}}
    if uses_sql:
        tabs["db"] = {"url": "${DBX_URL}", "label": "DATABASE (DBX)", "kind": "dbx",
                      "setup": [{"dbx_login": "${DBX_PASSWORD}"}]}  # fmt: skip
    out_steps = []
    for i, s in enumerate(steps, 1):
        sql = [a for a in s["actions"] if "sql" in a]
        if sql and len(sql) == len(s["actions"]):
            tab = "db"
        else:
            tab = "app"
            s["actions"] = [a for a in s["actions"] if "sql" not in a] or s["actions"]
        expect = s["expect"] or [{"visible": "body"}]
        step = {"id": f"S{i}", "tab": tab, "title": s["title"], "subtitle": " · ".join(x for x in s["lines"] if x)}
        if s["actions"]:
            step["actions"] = s["actions"]
        step["expect"] = expect
        out_steps.append(step)
    sc = {"name": name, "tabs": tabs}
    if cases:
        sc["cases"] = cases
    sc["steps"] = out_steps
    unresolved = sorted({m for m in re.findall(r"TODO\(([^)]+)\)", json.dumps(sc, ensure_ascii=False))})
    if url and unresolved:
        resolved = resolve(url, unresolved)
        dumped = json.dumps(sc, ensure_ascii=False)
        for label, sel in resolved.items():
            dumped = dumped.replace(json.dumps(todo(label))[1:-1], json.dumps(sel)[1:-1])
        sc = json.loads(dumped)
        unresolved = [u for u in unresolved if u not in resolved]
    return sc, unmatched, unresolved


def resolve(url, names, driver=None):
    """Find a unique selector for each element name on the live page (textbox, button, link, ...)."""
    from tirai.agentbrowser import AgentBrowser
    from tirai.resources import asset_text

    b = driver or AgentBrowser(headed=False, cursor=False)
    found = {}
    try:
        tab = b.open_session(url, "tirai-spec")
        b.sync(tab)
        js = asset_text("resolve-target.js")
        for name in names:
            for role in ("textbox", "button", "link", "combobox", "checkbox", "heading"):
                sel = b.evaluate(tab, f"{js}({json.dumps(role)},{json.dumps(name)},0)")
                if sel:
                    found[name] = sel
                    break
    finally:
        b.close_session()
    return found


def write(path, out, url=None):
    sc, unmatched, unresolved = build(path, url)
    head = [f"# Draft generated by `tirai from-spec {Path(path).name}`. Review before recording."]
    if unresolved:
        head.append("# Replace TODO(...) selectors: " + ", ".join(unresolved))
    for line in unmatched:
        head.append(f"# Not converted (add actions/expect by hand): {line}")
    body = yaml.safe_dump(sc, sort_keys=False, allow_unicode=True, width=120)
    Path(out).write_text("\n".join(head) + "\n" + body, encoding="utf-8")
    return sc, unmatched, unresolved
