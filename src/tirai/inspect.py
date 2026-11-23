"""`tirai inspect`: dry-run a scenario (or open one URL) and dump each step's page elements with
ready-to-use locators, plus a suggested `targets:` block covering every page in the flow."""

import json
from pathlib import Path


def url_scenario(url):
    return {
        "name": f"inspect {url}",
        "tabs": {"page": {"url": url}},
        "steps": [{"id": "page", "tab": "page", "title": url, "expect": [{"url_contains": ""}]}],
    }


def run(sc, out, session=None, driver=None):
    from tirai.runner import Runner

    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    r = Runner(sc, out, session, record=False, hold=0.3, driver=driver)
    r.inspect = True
    steps = r.run()
    return write(r.inspected, out, steps)


def _yaml_str(s):
    return f"'{s}'" if "'" not in s else json.dumps(s, ensure_ascii=False)


def suggest(pages):
    """{name: [locators]} for every element that has a unique locator, deduplicated across pages."""
    targets, seen = {}, {}
    for page in pages:
        for el in page["elements"] or []:
            if not el["locators"]:
                continue
            key = el["locators"][0]
            if key in seen:
                continue
            name = el.get("tagged") or el["id"] or el["role"]
            base, n = name, 2
            while name in targets:
                name, n = f"{base}_{n}", n + 1
            seen[key] = name
            targets[name] = el["locators"]
    return targets


def targets_yaml(targets):
    lines = ["targets:"]
    for name, locs in targets.items():
        lines.append(f"  {name}:")
        lines += [f"    - {_yaml_str(loc)}" for loc in locs]
    return "\n".join(lines) + "\n"


def page_md(page):
    lines = [
        f"# {page['step']} — {page['title']}",
        "",
        f"URL: {page['url']}",
        "",
        "| suggested id | role | name | locators (first = preferred) |",
        "|---|---|---|---|",
    ]
    for el in page["elements"] or []:
        locs = ", ".join(f"`{x}`" for x in el["locators"]) or "_no unique locator — add `within:`/`nth:`_"
        name = (el["name"] or "").replace("|", "\\|")
        lines.append(f"| {el.get('tagged') or el['id']} | {el['role']} | {name} | {locs.replace('|', chr(92) + '|')} |")
    return "\n".join(lines) + "\n"


def write(pages, out, steps=()):
    d = Path(out) / "inspect"
    d.mkdir(parents=True, exist_ok=True)
    for page in pages:
        (d / f"{page['step']}.md").write_text(page_md(page), encoding="utf-8")
    targets = suggest(pages)
    (d / "targets.yaml").write_text(targets_yaml(targets), encoding="utf-8")
    failed = [s for s in steps if s.get("status") != "passed"]
    return {"dir": d, "pages": len(pages), "targets": len(targets), "failed": failed}
