"""Behaviour tests for annotate.js in headless Chrome (skipped when no Chrome/Chromium is installed)."""

import json
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

from tirai.resources import annotate_js

CHROME = next(
    (
        p
        for p in (
            shutil.which(n) for n in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "chrome")
        )
        if p
    ),
    None,
)
pytestmark = pytest.mark.skipif(CHROME is None, reason="needs Chrome/Chromium for headless page tests")

PAGE = """<!doctype html><html><head><meta charset="utf-8">
<style>body{margin:0;font:16px sans-serif} .abs{position:absolute}</style></head><body>
<div id="a" class="abs" style="left:100px;top:100px;width:80px;height:30px">A</div>
<div id="edge" class="abs" style="left:1250px;top:300px;width:20px;height:20px">E</div>
<p id="mail" style="display:inline-block">contact: nobody</p>
<div id="host"></div>
<iframe id="fr" srcdoc="<p>frame mail: frame@example.com</p>" style="position:absolute;left:400px;top:400px"></iframe>
<style>.big{font-size:20px}</style>
<div id="price" class="abs big" style="left:100px;top:500px;color:rgb(255,0,0)">12,345</div>
<canvas id="cv" class="abs" width="60" height="30" style="left:300px;top:500px"></canvas>
<div id="flow" style="position:absolute;left:700px;top:40px;width:300px;height:200px;overflow:auto">
<table id="big"></table></div>
<span id="imgwrap" class="abs" style="left:900px;top:500px;width:60px;height:30px">
<img src="missing-image.png" onerror="window.__imgErr=(window.__imgErr||0)+1" width="20" height="20">x</span>
<pre id="out">pending</pre>
<script>
// --dump-dom with virtual time stops firing animation frames after the first; timers keep running.
window.requestAnimationFrame = (cb) => setTimeout(() => cb(performance.now()), 16);
window.cancelAnimationFrame = (h) => clearTimeout(h);
</script>
<script>__ANN__</script>
<script>
const frame = () => new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)));
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const R = {};
const shadow = () => document.getElementById('__ann_host').shadowRoot;
(async () => {
  try {
    await new Promise((r) => (document.getElementById('fr').contentDocument?.readyState === 'complete'
      ? r() : document.getElementById('fr').addEventListener('load', r)));
    const tick = async () => { window.dispatchEvent(new Event('resize')); await frame(); await frame(); };

    // Re-render: the box follows the replacement element; removal hides it.
    __ann.box('#a', { id: 'b1', padding: 0, anim: 'none' });
    const a2 = document.createElement('div');
    a2.id = 'a'; a2.className = 'abs'; a2.style.cssText = 'left:300px;top:200px;width:80px;height:30px';
    document.getElementById('a').replaceWith(a2);
    await tick();
    const rect = () => shadow().querySelector('svg g:not([data-spot]) rect');
    R.rerenderX = +rect().getAttribute('x');
    a2.remove();
    await tick();
    R.hiddenAfterRemove = rect().parentNode.style.display;
    const a3 = a2.cloneNode(true);
    a3.style.left = '600px';
    document.body.appendChild(a3);
    await tick();
    R.shownAgain = [rect().parentNode.style.display, +rect().getAttribute('x')];
    __ann.clear();

    // Spotlight hole follows its target when the layout moves.
    const s = document.createElement('div');
    s.id = 's'; s.className = 'abs'; s.style.cssText = 'left:50px;top:50px;width:40px;height:20px';
    document.body.appendChild(s);
    __ann.box('#s', { padding: 0, anim: 'none' });
    R.spot = __ann.spotlight();
    s.style.left = '500px';
    await tick();
    const holes = [...shadow().querySelectorAll('[data-spot] mask rect')];
    R.spotHoleX = +holes[holes.length - 1].getAttribute('x');
    __ann.clear();

    // Action callout honours spotlight.
    __ann.actionCallout('#s', 'Click', { spotlight: true });
    R.actSpot = !!shadow().querySelector('[data-spot=act]');
    __ann.clearAction();
    await sleep(300);

    // Badges number themselves; pos moves them; style picks the colour.
    __ann.badge('#s', 'auto', { anim: 'none' });
    __ann.badge('#s', undefined, { pos: 'bottom-right', anim: 'none' });
    R.badges = [...shadow().querySelectorAll('.badge')].map((b) => b.textContent);
    __ann.box('#s', { id: 'ok', style: 'success', anim: 'none' });
    R.styleStroke = [...shadow().querySelectorAll('svg g:not([data-spot]) rect')].pop().getAttribute('stroke');
    try { __ann.box('#s', { style: 'nope' }); R.badStyle = 'no error'; } catch (e) { R.badStyle = e.message; }
    __ann.underline('#s', { anim: 'none' });
    R.underline = !!shadow().querySelector('svg line');
    __ann.clear();

    // Arrow from the right of a target at the right edge stays inside the viewport.
    __ann.arrow('#edge', { from: 'right', anim: 'none' });
    const line = shadow().querySelector('svg line');
    R.arrowTail = [+line.getAttribute('x1'), innerWidth];
    __ann.clear();

    // Two labels on the same target do not overlap.
    __ann.text('#s', 'first', { anim: 'none' });
    __ann.text('#s', 'second', { anim: 'none' });
    await tick();
    const lbls = [...shadow().querySelectorAll('.lbl')].map((l) => l.getBoundingClientRect());
    R.labelsOverlap = lbls[0].top < lbls[1].bottom && lbls[1].top < lbls[0].bottom;
    __ann.clear();

    // Masks: text edits (characterData), open shadow roots and same-origin iframes.
    document.getElementById('host').attachShadow({ mode: 'open' }).innerHTML = '<span>sh@example.com</span>';
    R.maskStart = __ann.mask({ mask: ['email'] });
    document.getElementById('mail').firstChild.data = 'contact: late@example.com';
    await tick();
    R.maskAfterEdit = __ann.list().filter((id) => id.startsWith('mask-')).length;
    R.failsafeCleared = !__ann.list().includes('mask-failsafe');

    // Magnify on a cell of a big normal-flow table copies the cell, not the whole table.
    const big = document.getElementById('big');
    const row = (i) => `<tr><td>r${i}</td><td>a</td><td${i === 1 ? ' id="cell"' : ''}>v${i}</td></tr>`;
    big.innerHTML = Array.from({ length: 450 }, (_, i) => row(i)).join('');
    __ann.magnify('#cell', { anim: 'none' });
    R.magCell = [...shadow().querySelectorAll('.mag')].pop().querySelector('.mag-in > *').tagName;
    // The copy never runs page handlers.
    const errsBefore = window.__imgErr || 0;
    __ann.magnify('#imgwrap', { anim: 'none' });
    await sleep(300);
    R.imgHandler = [errsBefore, window.__imgErr || 0,
      [...shadow().querySelectorAll('.mag img')].some((i) => i.hasAttribute('onerror'))];
    __ann.clear();

    // Magnify: styled copy, canvas pixels, and masked text stays redacted in the enlargement.
    const cv = document.getElementById('cv').getContext('2d');
    cv.fillStyle = 'rgb(0,0,255)'; cv.fillRect(0, 0, 60, 30);
    __ann.magnify('#price', { id: 'm1', anim: 'none' });
    const mag = () => [...shadow().querySelectorAll('.mag')].pop();
    const priceCopy = mag().querySelector('.mag-in > *');
    R.magPrice = [priceCopy.textContent, priceCopy.style.color, priceCopy.style.fontSize, mag().style.transform || ''];
    __ann.magnify('#cv', { id: 'm2', anim: 'none', factor: 3 });
    const px = mag().querySelector('canvas').getContext('2d').getImageData(5, 5, 1, 1).data;
    R.magCanvas = [px[0], px[1], px[2], mag().offsetWidth];
    __ann.magnify('#mail', { id: 'm3', anim: 'none' });
    R.magMailText = mag().textContent;
    try { __ann.magnify('body'); R.magHuge = 'no error'; } catch (e) { R.magHuge = e.message; }
    __ann.clear();

    // Callout tail points at the target; curved arrows draw a path.
    __ann.callout('#s', { label: 'Note', anim: 'none' });
    const pts = [...shadow().querySelectorAll('svg polygon')].pop().getAttribute('points').trim().split(' ');
    const tail = pts.pop().split(',').map(Number);
    R.calloutApex = tail;
    try { __ann.callout('#s', {}); R.calloutNoLabel = 'no error'; } catch (e) { R.calloutNoLabel = e.message; }
    __ann.arrow('#a', { curve: 0.3, anim: 'none' });
    R.curved = (shadow().querySelector('svg path') || { getAttribute: () => '' }).getAttribute('d');
    __ann.clear();

    __ann.destroy();
    R.destroyed = !document.getElementById('__ann_host');
  } catch (e) {
    R.error = String(e && e.stack || e);
  }
  document.getElementById('out').textContent = 'RESULT' + JSON.stringify(R) + 'END';
})();
</script></body></html>"""


@pytest.fixture(scope="module")
def result():
    with tempfile.TemporaryDirectory(prefix="tirai-annjs-") as tmp:  # removed on teardown, also on failure
        page = Path(tmp) / "page.html"
        page.write_text(PAGE.replace("__ANN__", annotate_js()), encoding="utf-8")
        out = _chrome(page, Path(tmp) / "profile")
    m = re.search(r'<pre id="out">RESULT(.*?)END</pre>', out, re.S)
    assert m, f"page did not finish: {out[-500:]}"
    data = json.loads(m.group(1).replace("&quot;", '"').replace("&amp;", "&"))
    assert "error" not in data, data.get("error")
    return data


def _chrome(page, profile):
    return subprocess.run(
        [
            CHROME,
            "--headless=new",
            "--no-sandbox",
            "--disable-gpu",
            f"--user-data-dir={profile}",
            "--window-size=1280,720",
            "--virtual-time-budget=8000",
            "--dump-dom",
            page.as_uri(),
        ],
        capture_output=True,
        text=True,
        timeout=90,
    ).stdout


def test_box_follows_rerendered_element_and_hides_when_gone(result):
    assert result["rerenderX"] == 300
    assert result["hiddenAfterRemove"] == "none"
    assert result["shownAgain"] == ["", 600]


def test_spotlight_hole_follows_layout(result):
    assert result["spot"] is True
    assert result["spotHoleX"] == 490  # left 500 - 10 px hole margin


def test_action_callout_spotlight(result):
    assert result["actSpot"] is True


def test_badges_styles_and_underline(result):
    assert result["badges"] == ["1", "2"]
    assert result["styleStroke"] == "#16a34a"
    assert "unknown style" in result["badStyle"]
    assert result["underline"] is True


def test_arrow_tail_stays_in_viewport(result):
    tail, width = result["arrowTail"]
    assert 0 <= tail <= width - 8


def test_labels_do_not_overlap(result):
    assert result["labelsOverlap"] is False


def test_mask_covers_shadow_dom_iframe_and_text_edits(result):
    assert result["maskStart"] == 2  # shadow root + same-origin iframe
    assert result["maskAfterEdit"] == 3  # + the edited text node
    assert result["failsafeCleared"] is True


def test_destroy_removes_overlay(result):
    assert result["destroyed"] is True


def test_magnify_copies_styles_canvas_and_keeps_masks(result):
    text, color, size, _ = result["magPrice"]
    assert (text, color, size) == ("12,345", "rgb(255, 0, 0)", "20px")
    r, g, b, width = result["magCanvas"]
    assert (r, g, b) == (0, 0, 255)
    assert width >= 60 * 3  # 3x enlarged (+ border)
    assert "late@example.com" not in result["magMailText"] and "█" in result["magMailText"]
    assert "too large" in result["magHuge"] or "too complex" in result["magHuge"]


def test_callout_tail_and_curved_arrow(result):
    # #s ends at left 500, top 50, 40x20; padding 4 -> box 496..544 x 46..74; no room above, so the bubble is below.
    assert result["calloutApex"] == [520, 74]
    assert "needs a label" in result["calloutNoLabel"]
    assert " Q" in result["curved"]


def test_magnify_copies_the_target_not_its_container_and_runs_no_handlers(result):
    assert result["magCell"] == "TD"
    before, after, has_handler = result["imgHandler"]
    assert before == 1 and after == 1 and has_handler is False
