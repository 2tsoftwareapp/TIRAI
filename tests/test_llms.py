import importlib.util
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _builder():
    spec = importlib.util.spec_from_file_location("build_llms_full", ROOT / "scripts" / "build_llms_full.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _without_cli_help(text):
    # argparse layout differs between Python versions; the docs sections must match exactly.
    return re.sub(r"## Source: `tirai --help`.*?\n---\n", "", text, flags=re.S)


def test_llms_full_is_up_to_date():
    current = (ROOT / "llms-full.txt").read_text(encoding="utf-8")
    expected = _builder().build()
    assert _without_cli_help(current) == _without_cli_help(expected), "run `python scripts/build_llms_full.py`"


def test_llms_txt_links_point_to_existing_files():
    prefix = "https://raw.githubusercontent.com/2tsoftwareapp/TIRAI/main/"
    text = (ROOT / "llms.txt").read_text(encoding="utf-8")
    links = [part.split(")")[0] for part in text.split("](")[1:]]
    assert links
    for link in links:
        assert link.startswith(prefix), link
        assert (ROOT / link[len(prefix) :]).exists(), link
