/*
 * annotate.js — Snagit-style on-screen annotations for evidence recordings.
 * Inject into any page (e.g. `bsk evaluate`). Idempotent: re-injecting keeps
 * the existing instance. Everything renders inside its own (open) shadow root,
 * position:fixed, pointer-events:none, so the app's styles and events are not affected.
 *
 * API (window.__ann):
 *   box(target, opts)            rectangle around an element / rect
 *   circle(target, opts)         ellipse around an element / rect
 *   underline(target, opts)      line under the target; strike(target, opts) line through it
 *   arrow(target, opts)          arrow pointing at the element (opts.from: 'left'|'right'|'top'|'bottom'|'top-left'|...;
 *                                opts.curve: bend, e.g. 0.3 or -0.3)
 *   text(target, label, opts)    floating label next to target (or at {x,y})
 *   badge(target, n, opts)       numbered step marker (n omitted/'auto': next number; opts.pos: corner)
 *   highlight(target, opts)      translucent marker fill
 *   callout(target, opts)        speech bubble (opts.label) with a tail to the target (opts.from: auto|top|bottom|left|right)
 *   magnify(target, opts)        loupe beside the target with an enlarged snapshot (opts.factor 2, opts.from auto|right|left|bottom|top)
 *   blur(target, opts)           pixelate/blur sensitive content (opts.solid: opaque cover)
 *   clear(id?)                   remove one annotation or all (auto masks stay)
 *   mask({mask, patterns, selectors, keep, inputs})  auto-blur PII and keep it blurred as the DOM changes
 *                                mask: built-in rules (email, phone, card, token); patterns: extra regex sources;
 *                                selectors: always-blurred elements; keep: exact strings left visible
 * target: CSS selector | Element | {x, y, w?, h?} (viewport px) | {text, within?, exact?, nth?} | {selector, rel:{x,y,w,h}}
 *         | {grid:{column?, toColumn?, row, rows?, rowHeight?, header?, body?}} (canvas data grids)
 *   config({anim, duration})     global defaults; returns current config
 * common opts: id, color ('#2563eb'), style ('error'|'warning'|'info'|'success'; ignored when color is set),
 *   width (3), padding (6), label, labelPos, anim, duration
 * anim: 'draw' (default: strokes draw on once, then label fades in) | 'fade' | 'none'.
 *   Intros run once (no loops/blinking); blur is always instant so masked data never shows.
 * Every call returns the annotation id. Missing targets throw. A target that later leaves the DOM is
 * looked up again; while it cannot be found its shape is hidden instead of drawn at a stale position.
 */
(() => {
  const VERSION = '0.7.0';
  if (window.__ann && window.__ann.version === VERSION) return VERSION;
  try {
    window.__ann?.destroy?.();
  } catch (_) {
    /* an older instance without destroy(): its timers die with the page */
  }
  document.getElementById('__ann_host')?.remove();
  const CFG = {
    anim: 'draw',
    duration: 420,
    ease: 'cubic-bezier(.22,.8,.24,1)',
    color: '#2563eb',
    labelFont: "system-ui,'Segoe UI',sans-serif",
    cursorColor: '#111827',
    rippleColor: '#2563eb',
    spotlightOpacity: 0.30,
    passColor: '#16a34a',
    failColor: '#dc2626',
  };
  const NS = 'http://www.w3.org/2000/svg';
  const host = document.createElement('div');
  host.id = '__ann_host';
  host.style.cssText = 'position:fixed;inset:0;z-index:2147483647;pointer-events:none;';
  const root = host.attachShadow({ mode: 'open' });
  root.innerHTML = `<style>
    :host{all:initial}
    svg.ann-canvas{position:fixed;inset:0;width:100vw;height:100vh;overflow:visible}
    .lbl{position:fixed;font:600 15px/1.3 var(--ann-font,system-ui,'Segoe UI',sans-serif);color:#fff;padding:6px 10px;border-radius:6px;
         box-shadow:0 2px 8px #0005;white-space:pre-wrap;max-width:360px}
    .act-box{position:fixed;border:3px solid #2563eb;border-radius:8px;box-shadow:0 0 0 3px rgba(37,99,235,.18),0 4px 14px rgba(15,23,42,.18);
             background:rgba(37,99,235,.04);pointer-events:none;z-index:10;opacity:0;
             transition:left 280ms cubic-bezier(.22,.8,.24,1),top 280ms cubic-bezier(.22,.8,.24,1),
                        width 280ms cubic-bezier(.22,.8,.24,1),height 280ms cubic-bezier(.22,.8,.24,1),
                        opacity 220ms ease,border-color 220ms ease}
    .act-pill{position:fixed;display:inline-flex;align-items:center;gap:6px;font:700 13.5px/1.25 var(--ann-font,system-ui,'Segoe UI',sans-serif);
              color:#fff;padding:6px 12px;border-radius:999px;box-shadow:0 4px 14px rgba(15,23,42,.34);border:1.5px solid rgba(255,255,255,.35);
              white-space:nowrap;max-width:380px;overflow:hidden;text-overflow:ellipsis;z-index:11;opacity:0;
              transition:left 280ms cubic-bezier(.22,.8,.24,1),top 280ms cubic-bezier(.22,.8,.24,1),
                         opacity 220ms ease,background-color 220ms ease}
    .exp-hud{position:fixed;width:370px;max-width:calc(100vw - 28px);max-height:calc(100vh - 36px);overflow:hidden;
             background:rgba(15,23,42,.92);backdrop-filter:blur(8px);-webkit-backdrop-filter:blur(8px);
             color:#f8fafc;border:1px solid rgba(255,255,255,.15);border-radius:10px;box-shadow:0 8px 24px rgba(0,0,0,.42);
             font-family:var(--ann-font,system-ui,'Segoe UI',sans-serif);z-index:12}
    .exp-hdr{display:flex;align-items:center;justify-content:space-between;padding:8px 12px;
             border-bottom:1px solid rgba(255,255,255,.12);font-size:12px;font-weight:700;letter-spacing:.04em;color:#cbd5e1}
    .exp-sum{padding:2px 8px;border-radius:999px;font-size:11px;font-weight:700;color:#fff}
    .exp-list{display:flex;flex-direction:column;gap:5px;padding:8px 10px}
    .exp-row{display:flex;align-items:flex-start;gap:8px;padding:5px 7px;border-radius:6px;background:rgba(255,255,255,.04)}
    .exp-row.fail{background:rgba(220,38,38,.16);border:1px solid rgba(248,113,113,.35)}
    .exp-ico{flex:0 0 18px;width:18px;height:18px;border-radius:50%;display:flex;align-items:center;justify-content:center;
             font-size:11px;font-weight:800;color:#fff;margin-top:1px}
    .exp-txt{min-width:0;flex:1}
    .exp-lbl{font-size:12.5px;font-weight:600;line-height:1.3;color:#f8fafc;word-break:break-word}
    .exp-det{font-size:11px;line-height:1.25;color:#cbd5e1;margin-top:2px;word-break:break-word}
    .exp-row.fail .exp-det{color:#fca5a5}
    .badge{position:fixed;width:30px;height:30px;border-radius:50%;color:#fff;font:700 16px/30px system-ui,sans-serif;
           text-align:center;box-shadow:0 2px 6px #0006;border:2px solid #fff}
    .blur{position:fixed;backdrop-filter:blur(12px);-webkit-backdrop-filter:blur(12px);background:#cbd5e1b3;border-radius:4px}
    .blur.solid{background:#cbd5e1}
    .mag{position:fixed;overflow:hidden;border:3px solid;border-radius:8px;background:#fff;box-shadow:0 6px 20px rgba(15,23,42,.35)}
    .mag-in{position:absolute;left:0;top:0;transform-origin:0 0}
    .mag-cover{position:absolute;background:#cbd5e1}
    .sh{filter:drop-shadow(0 1px 1.5px rgba(0,0,0,.35))}
    .cur{position:fixed;left:0;top:0;width:28px;height:28px;pointer-events:none;z-index:10;
         filter:drop-shadow(0 2px 4px rgba(0,0,0,.45));transform-origin:4px 3px;will-change:transform;display:none}
    .cur svg{position:static;inset:auto;width:28px;height:28px;display:block;overflow:visible}
    .rpl{position:fixed;border-radius:50%;pointer-events:none;z-index:9;border:3px solid var(--rpl-c,#2563eb);
         background:color-mix(in srgb,var(--rpl-c,#2563eb) 22%,transparent);transform:translate(-50%,-50%)}
  </style><svg class="ann-canvas"></svg>`;
  const svg = root.querySelector('svg');
  const mount = () => { if (!host.isConnected) (document.body || document.documentElement).appendChild(host); };
  mount();

  const items = new Map();
  let seq = 0;

  const visible = (e) => { const r = e.getBoundingClientRect(); return r.width > 0 && r.height > 0; };
  // Open shadow roots under `scope` (web components); our own overlay host is skipped.
  const shadowRoots = (scope) => {
    const out = [];
    const visit = (r) => r.querySelectorAll('*').forEach((e) => {
      if (e.shadowRoot && e !== host) { out.push(e.shadowRoot); visit(e.shadowRoot); }
    });
    visit(scope);
    return out;
  };
  // Light DOM first; shadow roots are only searched when nothing visible matched there.
  const pick = (sel) => [...document.querySelectorAll(sel)].find(visible)
    || shadowRoots(document).map((r) => [...r.querySelectorAll(sel)].find(visible)).find(Boolean) || null;
  // Re-resolve a lookup once its element left the DOM (SPA re-render); throw while it cannot be found again.
  const live = (find, what) => {
    let node = find();
    if (!node) throw new Error(`annotate: ${what}`);
    return () => {
      if (!node.isConnected) {
        // Keep the last good node until a replacement exists, so a later tick can still find it again.
        const again = find();
        if (!again) throw new Error(`annotate: ${what} (removed)`);
        node = again;
      }
      // A hidden node is not swapped for another match: that could box a different element.
      if (!visible(node)) throw new Error(`annotate: ${what} (hidden)`);
      return node;
    };
  };
  const findText = (t) => {
    const scope = t.within ? document.querySelector(t.within) || pick(t.within) : document.body;
    if (!scope) throw new Error(`annotate: scope not found: ${t.within}`);
    const want = t.text.trim(), hits = [];
    for (const root of [scope, ...shadowRoots(scope)]) {
      const walker = document.createTreeWalker(root, NodeFilter.SHOW_ELEMENT);
      const first = root instanceof Element ? root : walker.nextNode();
      for (let n = first; n; n = walker.nextNode()) {
        if (n.closest('#__ann_host')) continue;
        const txt = (n.innerText || n.textContent || '').trim();
        const ok = t.exact === false ? txt.includes(want) : txt === want;
        if (!ok || !visible(n)) continue;
        if ([...n.children].some((c) => ((c.innerText || c.textContent || '').trim() === txt))) continue;
        hits.push(n);
      }
    }
    return hits[t.nth || 0] || null;
  };
  const resolveTarget = (t) => {
    if (typeof t === 'function') return t;
    if (t instanceof Element) {
      const get = () => {
        if (!t.isConnected) throw new Error('annotate: target element detached');
        return t;
      };
      return Object.assign(() => get().getBoundingClientRect(), { source: get });
    }
    // `.source()` hands the element itself to shapes that need it (magnify), not only its rect.
    const ofNode = (get) => Object.assign(() => get().getBoundingClientRect(), { source: get });
    if (typeof t === 'string') return ofNode(live(() => pick(t), `target not found: ${t}`));
    if (typeof t === 'object' && t && typeof t.text === 'string') {
      return ofNode(live(() => findText(t), `text not found: ${t.text.trim()}`));
    }
    if (t && t.grid) {
      // Cell of a canvas-rendered data grid whose header row is DOM (e.g. DBX):
      // x/width from the matching header cell, y from body top + (row-1)*rowHeight.
      const g = { header: '.data-grid-header-cell', body: 'canvas.canvas-grid-surface', rowHeight: 26, row: 1, ...t.grid };
      const name = (h) => (h.innerText || '').trim().split('\n')[0].trim();
      const lookup = () => {
        const body = pick(g.body);
        if (!body) throw new Error(`annotate: grid body not found: ${g.body}`);
        const heads = [...document.querySelectorAll(g.header)].filter(visible);
        const cols = g.column ? heads.filter((h) => name(h) === g.column) : heads;
        if (!cols.length) throw new Error(`annotate: grid column not found: ${g.column}`);
        const last = g.toColumn ? heads.find((h) => name(h) === g.toColumn) || cols[0] : cols[0];
        return { body, first: cols[0], last };
      };
      let parts = lookup();
      return () => {
        if (![parts.body, parts.first, parts.last].every((n) => n.isConnected)) parts = lookup();
        const a = parts.first.getBoundingClientRect(), z = parts.last.getBoundingClientRect();
        const b = parts.body.getBoundingClientRect();
        const left = g.column ? a.left : b.left, right = g.column ? z.right : b.right;
        const top = b.top + (g.row - 1) * g.rowHeight, height = g.rowHeight * (g.rows || 1);
        return { left, top, width: right - left, height, right, bottom: top + height };
      };
    }
    if (t && typeof t.selector === 'string') {
      // Region relative to an element, e.g. a cell inside a canvas data grid.
      const get = live(() => pick(t.selector), `target not found: ${t.selector}`);
      const rel = t.rel || {};
      return () => {
        const b = get().getBoundingClientRect();
        const left = b.left + (rel.x || 0), top = b.top + (rel.y || 0);
        const width = rel.w ?? b.width, height = rel.h ?? b.height;
        return { left, top, width, height, right: left + width, bottom: top + height };
      };
    }
    if (t && typeof t.x === 'number') {
      const r = { left: t.x, top: t.y, width: t.w || 0, height: t.h || 0 };
      return () => ({ ...r, right: r.left + r.width, bottom: r.top + r.height });
    }
    throw new Error('annotate: invalid target');
  };
  const pad = (r, p) => ({ x: r.left - p, y: r.top - p, w: r.width + 2 * p, h: r.height + 2 * p });
  const el = (tag, attrs) => { const n = document.createElementNS(NS, tag); for (const k in attrs) n.setAttribute(k, attrs[k]); return n; };
  const STYLES = { error: '#dc2626', warning: '#d97706', info: '#2563eb', success: '#16a34a' };
  const defaults = (o = {}) => ({ color: CFG.color || '#2563eb', width: 3, padding: 6, ...o });
  // Shape defaults (`base`) < user opts; a user `style` picks the colour unless the user also set `color`.
  const shapeOpts = (base, o = {}) => {
    const opts = defaults({ ...base, ...o });
    if (o.style !== undefined && o.color === undefined) {
      if (!STYLES[o.style]) throw new Error(`annotate: unknown style ${o.style} (use ${Object.keys(STYLES).join(', ')})`);
      opts.color = STYLES[o.style];
    }
    return opts;
  };
  const overlaps = (a, b) => a.left < b.right && b.left < a.right && a.top < b.bottom && b.top < a.bottom;
  // Labels of annotations drawn before `item`; later labels move out of their way, so placement is stable.
  const earlierLabels = (item, d) => {
    const out = [];
    for (const it of items.values()) {
      if (it === item) break;
      if (it.label && it.label !== d && !it.hidden) out.push(it.label.getBoundingClientRect());
    }
    return out;
  };
  // Clamp a label into the viewport, then step it down (or up near the bottom) until it clears earlier labels.
  function setLabelPos(d, x, y, item) {
    const lw = d.offsetWidth, lh = d.offsetHeight, step = lh + 6;
    const clampX = Math.max(4, Math.min(x, innerWidth - lw - 4));
    let cy = Math.max(4, Math.min(y, innerHeight - lh - 4));
    const others = earlierLabels(item, d);
    const box = (yy) => ({ left: clampX, top: yy, right: clampX + lw, bottom: yy + lh });
    for (let i = 0, dir = 1; i < 8 && others.some((o) => overlaps(box(cy), o)); i++) {
      if (cy + step * dir > innerHeight - lh - 4 || cy + step * dir < 4) dir = -dir;
      cy += step * dir;
    }
    d.style.left = `${clampX}px`; d.style.top = `${cy}px`;
  }

  function makeLabel(text, color) {
    const d = document.createElement('div');
    d.className = 'lbl';
    d.style.background = color;
    d.textContent = text;
    root.appendChild(d);
    return d;
  }
  function placeLabel(d, b, pos, item) {
    const lw = d.offsetWidth, lh = d.offsetHeight, gap = 10;
    let x, y;
    switch (pos) {
      case 'top': x = b.x; y = b.y - lh - gap; break;
      case 'left': x = b.x - lw - gap; y = b.y + (b.h - lh) / 2; break;
      case 'bottom': x = b.x; y = b.y + b.h + gap; break;
      default: x = b.x + b.w + gap; y = b.y + (b.h - lh) / 2;
    }
    setLabelPos(d, x, y, item);
  }

  function add(kind, target, o, build, base = {}) {
    mount();
    const opts = shapeOpts(base, o);
    const rectOf = resolveTarget(target);
    const id = opts.id || `${kind}-${++seq}`;
    clear(id);
    const g = el('g', {});
    if (kind !== 'highlight') g.setAttribute('class', 'sh');
    svg.appendChild(g);
    const label = opts.label ? makeLabel(opts.label, opts.color) : null;
    const item = { id, kind, g, label, nodes: [], update: null, hidden: false, rectOf, opts };
    item.update = () => {
      const b = pad(rectOf(), opts.padding);
      item._lastBox = b;
      build(item, b, opts);
      if (label && opts.labelPos !== 'none') placeLabel(label, b, opts.labelPos, item);
    };
    try {
      item.update();
    } catch (e) {
      [g, label, item.div].forEach((n) => n && n.remove());
      throw e;
    }
    items.set(id, item);
    intro(item, kind === 'blur' ? 'none' : opts.anim ?? CFG.anim, opts.duration ?? CFG.duration);
    return id;
  }

  const reduced = () => matchMedia('(prefers-reduced-motion: reduce)').matches;
  const play = (n, frames, timing) => n && n.animate(frames, { easing: CFG.ease, fill: 'backwards', ...timing });
  function intro(item, mode, d) {
    if (mode === 'none' || reduced()) return;
    const strokes = item.nodes.filter((n) => n.tagName === 'line' || n.getAttribute('fill') === 'none');
    const fills = item.nodes.filter((n) => !strokes.includes(n));
    let shapeEnd = 0;
    if (mode === 'draw' && strokes.length) {
      strokes.forEach((n) => {
        n.setAttribute('pathLength', '1');
        play(n, [{ strokeDasharray: '1 1', strokeDashoffset: '1' }, { strokeDasharray: '1 1', strokeDashoffset: '0' }], { duration: d });
      });
      fills.forEach((n) => play(n, [{ opacity: 0 }, { opacity: 1 }], { duration: 120, delay: d * 0.75 }));
      shapeEnd = d;
    } else if (item.kind === 'highlight' && mode === 'draw') {
      fills.forEach((n) => {
        n.style.transformBox = 'fill-box'; n.style.transformOrigin = 'left center';
        play(n, [{ transform: 'scaleX(0)' }, { transform: 'scaleX(1)' }], { duration: d * 0.8 });
      });
      shapeEnd = d * 0.8;
    } else if (item.nodes.length) {
      play(item.g, [{ opacity: 0 }, { opacity: 1 }], { duration: 220 });
      shapeEnd = 220;
    }
    play(item.div, [{ opacity: 0, transform: 'scale(.85)' }, { opacity: 1, transform: 'none' }], { duration: 200 });
    play(item.label, [{ opacity: 0, transform: 'translateY(4px)' }, { opacity: 1, transform: 'none' }], { duration: 200, delay: shapeEnd * 0.7 });
  }

  const once = (item, make) => { if (!item.nodes.length) { item.nodes = make(); item.nodes.forEach((n) => item.g.appendChild(n)); } return item.nodes; };

  function box(target, o) {
    return add('box', target, o, (item, b, opts) => {
      const [r] = once(item, () => [el('rect', { fill: 'none', rx: 6 })]);
      Object.entries({ x: b.x, y: b.y, width: b.w, height: b.h, stroke: opts.color, 'stroke-width': opts.width }).forEach(([k, v]) => r.setAttribute(k, v));
    });
  }
  function circle(target, o) {
    return add('circle', target, o, (item, b, opts) => {
      const [e] = once(item, () => [el('ellipse', { fill: 'none' })]);
      Object.entries({ cx: b.x + b.w / 2, cy: b.y + b.h / 2, rx: b.w / 2, ry: b.h / 2, stroke: opts.color, 'stroke-width': opts.width }).forEach(([k, v]) => e.setAttribute(k, v));
    }, { padding: 12 });
  }
  // underline: just below the target; strike: through its vertical centre.
  const rule = (kind, yOf) => (target, o) => add(kind, target, o, (item, b, opts) => {
    const [l] = once(item, () => [el('line', { 'stroke-linecap': 'round' })]);
    const y = yOf(b);
    Object.entries({ x1: b.x, y1: y, x2: b.x + b.w, y2: y, stroke: opts.color, 'stroke-width': opts.width }).forEach(([k, v]) => l.setAttribute(k, v));
  }, { padding: 2 });
  const underline = rule('underline', (b) => b.y + b.h);
  const strike = rule('strike', (b) => b.y + b.h / 2);
  function highlight(target, o) {
    return add('highlight', target, o, (item, b, opts) => {
      const [r] = once(item, () => [el('rect', { rx: 3 })]);
      Object.entries({ x: b.x, y: b.y, width: b.w, height: b.h, fill: opts.color, 'fill-opacity': 0.35 }).forEach(([k, v]) => r.setAttribute(k, v));
    }, { color: '#ffd400', padding: 2 });
  }
  const DIRS = { left: [-1, 0], right: [1, 0], top: [0, -1], bottom: [0, 1], 'top-left': [-0.7, -0.7], 'top-right': [0.7, -0.7], 'bottom-left': [-0.7, 0.7], 'bottom-right': [0.7, 0.7] };
  // Longest tail (px) from the tip along (dx, dy) that stays 8 px inside the viewport.
  const room = (x, y, dx, dy) => Math.min(
    dx > 0 ? (innerWidth - 8 - x) / dx : dx < 0 ? (x - 8) / -dx : Infinity,
    dy > 0 ? (innerHeight - 8 - y) / dy : dy < 0 ? (y - 8) / -dy : Infinity,
  );
  function arrow(target, o) {
    return add('arrow', target, o, (item, b, opts) => {
      let [dx, dy] = DIRS[opts.from] || DIRS.right;
      const cx = b.x + b.w / 2, cy = b.y + b.h / 2;
      const tipOf = (ddx, ddy) => [cx + ddx * (b.w / 2), cy + ddy * (b.h / 2)];
      let [tipX, tipY] = tipOf(dx, dy);
      let len = Math.min(opts.length, room(tipX, tipY, dx, dy));
      // Target against the edge the arrow comes from: come from the opposite side instead of leaving the frame.
      if (len < Math.min(40, opts.length)) {
        const [fx, fy] = tipOf(-dx, -dy);
        const flipped = Math.min(opts.length, room(fx, fy, -dx, -dy));
        if (flipped > len) { dx = -dx; dy = -dy; tipX = fx; tipY = fy; len = flipped; }
      }
      len = Math.max(0, len);
      const tailX = tipX + dx * len, tailY = tipY + dy * len;
      const hl = 18;
      // curve: control point pushed sideways by curve x length (sign picks the side); the head follows the curve.
      const bend = Number(opts.curve) || 0;
      const cx2 = (tailX + tipX) / 2 - dy * bend * len, cy2 = (tailY + tipY) / 2 + dx * bend * len;
      const ang = bend ? Math.atan2(tipY - cy2, tipX - cx2) : Math.atan2(tipY - tailY, tipX - tailX);
      const endX = tipX - Math.cos(ang) * hl * 0.6, endY = tipY - Math.sin(ang) * hl * 0.6;
      const [line, head] = once(item, () => [
        bend ? el('path', { fill: 'none', 'stroke-linecap': 'round' }) : el('line', { 'stroke-linecap': 'round' }),
        el('polygon', {}),
      ]);
      const shaft = bend
        ? { d: `M${tailX},${tailY} Q${cx2},${cy2} ${endX},${endY}` }
        : { x1: tailX, y1: tailY, x2: endX, y2: endY };
      Object.entries({ ...shaft, stroke: opts.color, 'stroke-width': opts.width + 2 }).forEach(([k, v]) => line.setAttribute(k, v));
      const p = (a) => `${tipX - hl * Math.cos(ang - a)},${tipY - hl * Math.sin(ang - a)}`;
      head.setAttribute('points', `${tipX},${tipY} ${p(0.45)} ${p(-0.45)}`);
      head.setAttribute('fill', opts.color);
      if (item.label) {
        const lw = item.label.offsetWidth, lh = item.label.offsetHeight;
        const lx = tailX + (dx < 0 ? -lw - 6 : dx > 0 ? 6 : -lw / 2), ly = tailY + (dy < 0 ? -lh - 6 : dy > 0 ? 6 : -lh / 2);
        setLabelPos(item.label, lx, ly, item);
        opts.labelPos = 'none';
      }
    }, { padding: 4, length: 110, from: 'right', labelPos: undefined });
  }
  function text(target, label, o) {
    return add('text', target, { ...o, label }, () => {}, { padding: 0 });
  }
  let badgeSeq = 0;
  // Badge centre per `pos`, relative to the padded target box.
  const BADGE_POS = {
    'top-left': (b) => [b.x, b.y], 'top-right': (b) => [b.x + b.w, b.y],
    'bottom-left': (b) => [b.x, b.y + b.h], 'bottom-right': (b) => [b.x + b.w, b.y + b.h],
    left: (b) => [b.x - 18, b.y + b.h / 2], right: (b) => [b.x + b.w + 18, b.y + b.h / 2],
  };
  function badge(target, n, o = {}) {
    const at = BADGE_POS[o.pos || 'top-left'];
    if (!at) throw new Error(`annotate: unknown badge pos ${o.pos} (use ${Object.keys(BADGE_POS).join(', ')})`);
    const num = n === undefined || n === null || n === 'auto' ? ++badgeSeq : n;
    if (typeof num === 'number') badgeSeq = Math.max(badgeSeq, num);
    return add('badge', target, o, (item, b, opts) => {
      if (!item.div) { item.div = document.createElement('div'); item.div.className = 'badge'; item.div.textContent = String(num); root.appendChild(item.div); }
      item.div.style.background = opts.color;
      const [x, y] = at(b);
      item.div.style.left = `${x - 15}px`; item.div.style.top = `${y - 15}px`;
    }, { padding: 0, color: '#1f6feb' });
  }
  function blur(target, o = {}) {
    const id = add('blur', target, o, (item, b, opts) => {
      if (!item.div) { item.div = document.createElement('div'); item.div.className = o.solid ? 'blur solid' : 'blur'; root.appendChild(item.div); }
      Object.assign(item.div.style, { left: `${b.x}px`, top: `${b.y}px`, width: `${b.w}px`, height: `${b.h}px` });
      // Text that is not laid out (display:none) has an empty rect: keep its cover, but not as a dot at 0,0.
      item.div.style.visibility = b.w > 2 * opts.padding && b.h > 2 * opts.padding ? '' : 'hidden';
    }, { padding: 2 });
    followCovers();
    return id;
  }
  // Speech bubble: the label sits beside the target with a tail pointing at it.
  function callout(target, o = {}) {
    if (!o.label) throw new Error('annotate: callout needs a label');
    return add('callout', target, o, (item, b, opts) => {
      const [tail] = once(item, () => [el('polygon', {})]);
      const d = item.label, lw = d.offsetWidth, lh = d.offsetHeight, gap = opts.gap;
      let side = opts.from;
      if (side === 'auto') side = b.y - lh - gap >= 4 ? 'top' : 'bottom';
      const cx = b.x + b.w / 2, cy = b.y + b.h / 2;
      const at = {
        top: [cx - lw / 2, b.y - lh - gap], bottom: [cx - lw / 2, b.y + b.h + gap],
        left: [b.x - lw - gap, cy - lh / 2], right: [b.x + b.w + gap, cy - lh / 2],
      }[side];
      if (!at) throw new Error(`annotate: unknown callout side ${side} (use auto, top, bottom, left, right)`);
      // No room on the requested side: flip to the opposite one rather than covering the target.
      const flip = { top: at[1] < 4, bottom: at[1] + lh > innerHeight - 4, left: at[0] < 4, right: at[0] + lw > innerWidth - 4 };
      if (flip[side]) {
        side = { top: 'bottom', bottom: 'top', left: 'right', right: 'left' }[side];
        const o2 = { top: [at[0], b.y - lh - gap], bottom: [at[0], b.y + b.h + gap], left: [b.x - lw - gap, at[1]], right: [b.x + b.w + gap, at[1]] };
        at[0] = o2[side][0]; at[1] = o2[side][1];
      }
      setLabelPos(d, at[0], at[1], item);
      const lx = parseFloat(d.style.left), ly = parseFloat(d.style.top);
      const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));
      const vertical = side === 'top' || side === 'bottom';
      // Tail base on the bubble edge facing the target, apex on the target edge.
      const bx = vertical ? clamp(cx, lx + 14, lx + lw - 14) : side === 'left' ? lx + lw - 1 : lx + 1;
      const by = vertical ? (ly + lh / 2 < cy ? ly + lh - 1 : ly + 1) : clamp(cy, ly + 12, ly + lh - 12);
      const ax = vertical ? clamp(cx, b.x, b.x + b.w) : side === 'left' ? b.x : b.x + b.w;
      const ay = vertical ? (ly + lh / 2 < cy ? b.y : b.y + b.h) : cy;
      const base = vertical ? [[bx - 9, by], [bx + 9, by]] : [[bx, by - 8], [bx, by + 8]];
      tail.setAttribute('points', `${base[0]} ${base[1]} ${ax},${ay}`);
      tail.setAttribute('fill', opts.color);
    }, { padding: 4, from: 'auto', gap: 22, labelPos: 'none' });
  }

  // Magnify: a loupe panel next to the target with an enlarged snapshot (taken when drawn) of that region.
  const MAG_MAX_NODES = 1500;
  const copyStyle = (src, dst) => {
    const cs = getComputedStyle(src);
    for (let i = 0; i < cs.length; i++) dst.style.setProperty(cs[i], cs.getPropertyValue(cs[i]), cs.getPropertyPriority(cs[i]));
  };
  // Page CSS does not reach into our shadow root, so every cloned element carries its computed style inline.
  function cloneStyled(src, budget) {
    if (src.nodeType === 3) return src.cloneNode(false);
    if (src.nodeType !== 1 || /^(SCRIPT|STYLE|LINK|META|NOSCRIPT|TEMPLATE|IFRAME|OBJECT|EMBED|AUDIO)$/.test(src.tagName)) return null;
    if (--budget.left < 0) throw new Error('annotate: magnify target is too complex; point it at a smaller element');
    // Media become still pictures, so the copy never plays, loads or fires anything.
    const still = src instanceof HTMLCanvasElement || src instanceof HTMLVideoElement;
    const dst = still ? document.createElement('canvas') : src.cloneNode(false);
    // The copy must not run page code or change page state: drop handlers, ids and self-starting attributes.
    [...dst.attributes].forEach((a) => {
      if (/^on/i.test(a.name) || /^(id|autoplay|autofocus|loading|contenteditable|tabindex)$/i.test(a.name)) dst.removeAttribute(a.name);
    });
    copyStyle(src, dst);
    if (still) {
      dst.width = src.width || src.videoWidth || src.clientWidth;
      dst.height = src.height || src.videoHeight || src.clientHeight;
      dst.getContext('2d').drawImage(src, 0, 0, dst.width, dst.height);
      return dst;
    }
    src.childNodes.forEach((c) => { const k = cloneStyled(c, budget); if (k) dst.appendChild(k); });
    // After the children: a <select> can only take a value its cloned options offer.
    if (/^(INPUT|TEXTAREA|SELECT)$/.test(src.tagName)) dst.value = src.value;
    return dst;
  }
  // Masked text must not reappear enlarged: redact it in the copy, and cover every blur/mask box in the region.
  function redact(node, region, f, panel) {
    if (MASK.re) {
      const walker = document.createTreeWalker(node, NodeFilter.SHOW_TEXT);
      for (let n = walker.nextNode(); n; n = walker.nextNode()) {
        n.data = n.data.replace(MASK.re, (m) => (m.trim() && !MASK.keep.has(m) ? '█'.repeat(m.length) : m));
      }
      node.querySelectorAll('input,textarea').forEach((e) => { if (hits(e.value || '').length) e.value = '█'.repeat(e.value.length); });
    }
    items.forEach((it) => {
      const c = it.kind === 'blur' && it._lastBox;
      if (!c || c.x > region.x + region.w || c.x + c.w < region.x || c.y > region.y + region.h || c.y + c.h < region.y) return;
      const cover = document.createElement('div');
      cover.className = 'mag-cover';
      Object.assign(cover.style, { left: `${(c.x - region.x) * f}px`, top: `${(c.y - region.y) * f}px`, width: `${c.w * f}px`, height: `${c.h * f}px` });
      panel.appendChild(cover);
    });
  }
  function magnifySource(item, region) {
    if (item.rectOf.source) return item.rectOf.source();
    // Rect/grid targets: the smallest element that holds the target itself (not the padded box around it).
    const p = item.opts.padding, inner = { x: region.x + p, y: region.y + p, w: region.w - 2 * p, h: region.h - 2 * p };
    const fits = (e) => {
      const r = e.getBoundingClientRect();
      return r.left <= inner.x + 1 && r.top <= inner.y + 1 && r.right >= inner.x + inner.w - 1 && r.bottom >= inner.y + inner.h - 1;
    };
    const under = document.elementsFromPoint(inner.x + inner.w / 2, inner.y + inner.h / 2).filter((e) => e !== host);
    const src = under.find(fits) || under[0];
    if (!src) throw new Error('annotate: magnify found nothing under the target');
    return src;
  }
  function snapshot(src, region, f, color) {
    const sr = src.getBoundingClientRect();
    const copy = cloneStyled(src, { left: MAG_MAX_NODES });
    Object.assign(copy.style, {
      position: 'absolute', left: `${sr.left - region.x}px`, top: `${sr.top - region.y}px`, margin: '0',
      width: `${sr.width}px`, height: `${sr.height}px`, boxSizing: 'border-box', transform: 'none',
    });
    const panel = document.createElement('div');
    panel.className = 'mag';
    Object.assign(panel.style, { width: `${region.w * f}px`, height: `${region.h * f}px`, borderColor: color });
    const inner = document.createElement('div');
    inner.className = 'mag-in';
    Object.assign(inner.style, { width: `${region.w}px`, height: `${region.h}px`, transform: `scale(${f})` });
    inner.appendChild(copy);
    panel.appendChild(inner);
    redact(copy, region, f, panel);
    return panel;
  }
  function magnify(target, o = {}) {
    return add('magnify', target, o, (item, b, opts) => {
      const [frame, l1, l2] = once(item, () => [el('rect', { fill: 'none', rx: 4 }), el('line', {}), el('line', {})]);
      if (!item.div) {
        const f = Math.min(opts.factor, opts.maxWidth / b.w, opts.maxHeight / b.h);
        if (!(f >= 1.2)) throw new Error('annotate: magnify target is too large to enlarge; use a smaller target');
        item.div = snapshot(magnifySource(item, b), b, f, opts.color);
        root.appendChild(item.div);
      }
      const p = item.div, pw = p.offsetWidth, ph = p.offsetHeight, gap = opts.gap;
      let side = opts.from;
      if (side === 'auto') {
        side = b.x + b.w + gap + pw <= innerWidth - 4 ? 'right' : b.x - gap - pw >= 4 ? 'left'
          : b.y + b.h + gap + ph <= innerHeight - 4 ? 'bottom' : 'top';
      }
      const pos = {
        right: [b.x + b.w + gap, b.y + b.h / 2 - ph / 2], left: [b.x - gap - pw, b.y + b.h / 2 - ph / 2],
        bottom: [b.x + b.w / 2 - pw / 2, b.y + b.h + gap], top: [b.x + b.w / 2 - pw / 2, b.y - gap - ph],
      }[side];
      if (!pos) throw new Error(`annotate: unknown magnify side ${side} (use auto, right, left, bottom, top)`);
      const px = Math.max(4, Math.min(pos[0], innerWidth - pw - 4)), py = Math.max(4, Math.min(pos[1], innerHeight - ph - 4));
      Object.assign(p.style, { left: `${px}px`, top: `${py}px` });
      Object.entries({ x: b.x, y: b.y, width: b.w, height: b.h, stroke: opts.color, 'stroke-width': opts.width }).forEach(([k, v]) => frame.setAttribute(k, v));
      // Connectors from the target box to the loupe's facing corners.
      const ends = {
        right: [[b.x + b.w, b.y, px, py], [b.x + b.w, b.y + b.h, px, py + ph]],
        left: [[b.x, b.y, px + pw, py], [b.x, b.y + b.h, px + pw, py + ph]],
        bottom: [[b.x, b.y + b.h, px, py], [b.x + b.w, b.y + b.h, px + pw, py]],
        top: [[b.x, b.y, px, py + ph], [b.x + b.w, b.y, px + pw, py + ph]],
      }[side];
      [l1, l2].forEach((ln, i) => {
        const [x1, y1, x2, y2] = ends[i];
        Object.entries({ x1, y1, x2, y2, stroke: opts.color, 'stroke-width': Math.max(1, opts.width - 1) }).forEach(([k, v]) => ln.setAttribute(k, v));
      });
      if (item.label) setLabelPos(item.label, px, py - item.label.offsetHeight - 8, item);
    }, { padding: 2, factor: 2, from: 'auto', gap: 36, maxWidth: 560, maxHeight: 360, labelPos: 'none' });
  }

  const activeItems = () => [...items.values()].filter((it) => !it.id.startsWith('mask-') && it.kind !== 'blur' && !it.hidden);
  // Dimmed overlay with holes; `boxes()` is re-read on every tick so the holes follow scroll/resize/re-render.
  let spot = null;
  function clearSpotlight() {
    if (!spot) return;
    const old = spot.g;
    spot = null;
    if (reduced()) return old.remove();
    old.animate([{ opacity: 1 }, { opacity: 0 }], { duration: 180, fill: 'forwards' }).onfinish = () => old.remove();
  }
  function layoutSpot() {
    if (!spot) return;
    const W = innerWidth, H = innerHeight;
    spot.dim.setAttribute('width', W);
    spot.dim.setAttribute('height', H);
    const holes = spot.boxes().filter((r) => r && r.w > 0 && r.h > 0)
      .map((r) => el('rect', { x: r.x - 10, y: r.y - 10, width: r.w + 20, height: r.h + 20, rx: 10, fill: '#000' }));
    spot.m.replaceChildren(el('rect', { x: 0, y: 0, width: W, height: H, fill: '#fff' }), ...holes);
  }
  function makeSpot(boxes, opacity, kind) {
    mount();
    clearSpotlight();
    const op = typeof opacity === 'number' ? opacity : CFG.spotlightOpacity;
    if (!(op > 0) || !boxes().some((r) => r && r.w > 0 && r.h > 0)) return false;
    const maskId = `ann-spot-${++seq}`;
    const g = el('g', { 'data-spot': kind });
    const defs = el('defs', {});
    const m = el('mask', { id: maskId });
    defs.appendChild(m);
    g.appendChild(defs);
    const dim = el('rect', { x: 0, y: 0, fill: `rgba(15,23,42,${op})`, mask: `url(#${maskId})` });
    g.appendChild(dim);
    svg.insertBefore(g, svg.firstChild);
    spot = { g, m, dim, boxes, kind };
    layoutSpot();
    if (!reduced()) g.animate([{ opacity: 0 }, { opacity: 1 }], { duration: 320, easing: CFG.ease, fill: 'backwards' });
    return true;
  }
  function spotlight(opacity) {
    return makeSpot(() => activeItems().map((it) => it._lastBox), opacity, 'ann');
  }
  function bounds() {
    const active = activeItems();
    if (!active.length) return null;
    let x1 = Infinity, y1 = Infinity, x2 = -Infinity, y2 = -Infinity;
    const grow = (x, y, w, h) => {
      if (!(w > 0 && h > 0)) return;
      x1 = Math.min(x1, x); y1 = Math.min(y1, y);
      x2 = Math.max(x2, x + w); y2 = Math.max(y2, y + h);
    };
    active.forEach((it) => {
      const b = it._lastBox;
      if (b) grow(b.x, b.y, b.w, b.h);
      if (it.label) { const lr = it.label.getBoundingClientRect(); grow(lr.left, lr.top, lr.width, lr.height); }
      if (it.div) { const dr = it.div.getBoundingClientRect(); grow(dr.left, dr.top, dr.width, dr.height); }
    });
    if (!Number.isFinite(x1)) return null;
    const padPx = 28;
    const bx = Math.max(0, x1 - padPx), by = Math.max(0, y1 - padPx);
    const bw = Math.min(innerWidth - bx, (x2 - x1) + padPx * 2);
    const bh = Math.min(innerHeight - by, (y2 - y1) + padPx * 2);
    return [bx, by, bw, bh, innerWidth, innerHeight];
  }

  let curEl = null, curX = null, curY = null, curAnim = 0;
  function ensureCursor(color) {
    mount();
    if (!curEl) {
      curEl = document.createElement('div');
      curEl.className = 'cur';
      curEl.innerHTML = `<svg viewBox="0 0 28 28" width="28" height="28"><path d="M4 2 L4 22 L9.5 16.8 L13.2 24.5 L16.2 23.1 L12.5 15.5 L20 15.5 Z" fill="${color || CFG.cursorColor}" stroke="#fff" stroke-width="2" stroke-linejoin="round"/></svg>`;
      root.appendChild(curEl);
    } else if (color) {
      const p = curEl.querySelector('path');
      if (p) p.setAttribute('fill', color);
    }
    curEl.style.display = 'block';
    return curEl;
  }
  function cursorMove(x, y, ms = 360, color) {
    const c = ensureCursor(color);
    const tx = Math.max(2, Math.min(innerWidth - 2, x));
    const ty = Math.max(2, Math.min(innerHeight - 2, y));
    if (curAnim) { cancelAnimationFrame(curAnim); curAnim = 0; }
    if (curX === null || ms <= 0 || reduced()) {
      curX = tx; curY = ty;
      c.style.transform = `translate3d(${tx - 4}px,${ty - 3}px,0)`;
      return true;
    }
    const sx = curX, sy = curY;
    const dx = tx - sx, dy = ty - sy;
    const dist = Math.hypot(dx, dy);
    const dur = Math.max(180, Math.min(ms, 180 + dist * 0.45));
    const arc = Math.min(42, dist * 0.12) * (dx >= 0 ? -1 : 1);
    const mx = (sx + tx) / 2, my = (sy + ty) / 2 + arc;
    const t0 = performance.now();
    const step = (now) => {
      const u = Math.min(1, (now - t0) / dur);
      const e = 1 - Math.pow(1 - u, 3);
      const inv = 1 - e;
      curX = inv * inv * sx + 2 * inv * e * mx + e * e * tx;
      curY = inv * inv * sy + 2 * inv * e * my + e * e * ty;
      c.style.transform = `translate3d(${curX - 4}px,${curY - 3}px,0)`;
      if (u < 1) curAnim = requestAnimationFrame(step); else curAnim = 0;
    };
    curAnim = requestAnimationFrame(step);
    return dur;
  }
  function cursorClick(x, y, rippleColor) {
    const c = ensureCursor();
    const tx = typeof x === 'number' ? x : (curX ?? innerWidth / 2);
    const ty = typeof y === 'number' ? y : (curY ?? innerHeight / 2);
    curX = tx; curY = ty;
    c.style.transform = `translate3d(${tx - 4}px,${ty - 3}px,0)`;
    if (!reduced()) {
      c.animate(
        [
          { transform: `translate3d(${tx - 4}px,${ty - 3}px,0) scale(1)` },
          { transform: `translate3d(${tx - 4}px,${ty - 3}px,0) scale(0.82)` },
          { transform: `translate3d(${tx - 4}px,${ty - 3}px,0) scale(1)` },
        ],
        { duration: 160, easing: 'ease-out' }
      );
      const r = document.createElement('div');
      r.className = 'rpl';
      r.style.setProperty('--rpl-c', rippleColor || CFG.rippleColor);
      r.style.left = `${tx}px`;
      r.style.top = `${ty}px`;
      r.style.width = '14px';
      r.style.height = '14px';
      root.appendChild(r);
      r.animate(
        [
          { width: '12px', height: '12px', opacity: 0.78 },
          { width: '48px', height: '48px', opacity: 0 },
        ],
        { duration: 340, easing: 'cubic-bezier(.22,.8,.24,1)', fill: 'forwards' }
      ).onfinish = () => r.remove();
    }
    return true;
  }
  function cursorHide() { if (curEl) curEl.style.display = 'none'; return true; }

  function targetLabel(sel) {
    try {
      const e = typeof sel === 'string' ? pick(sel) : null;
      if (!e) return '';
      const aria = (e.getAttribute('aria-label') || '').trim();
      if (aria) return aria.slice(0, 32);
      const lbBy = e.getAttribute('aria-labelledby');
      if (lbBy) {
        const ref = document.getElementById(lbBy.split(/\s+/)[0]);
        const t = ref && (ref.innerText || ref.textContent || '').trim();
        if (t) return t.slice(0, 32);
      }
      if (e.id) {
        const lbl = document.querySelector(`label[for="${CSS.escape(e.id)}"]`);
        const t = lbl && (lbl.innerText || lbl.textContent || '').trim();
        if (t) return t.slice(0, 32);
      }
      const wrap = e.closest && e.closest('label');
      if (wrap) {
        const t = (wrap.innerText || wrap.textContent || '').trim();
        if (t) return t.slice(0, 32);
      }
      const ph = (e.getAttribute('placeholder') || e.getAttribute('title') || '').trim();
      if (ph) return ph.slice(0, 32);
      const txt = (e.innerText || e.textContent || '').trim().replace(/\s+/g, ' ');
      if (txt && txt.length <= 36) return txt;
      return '';
    } catch (_) {
      return '';
    }
  }

  let actBoxEl = null;
  let actPillEl = null;
  function clearAction() {
    if (actBoxEl) {
      const oldBox = actBoxEl;
      actBoxEl = null;
      if (reduced()) oldBox.remove();
      else {
        oldBox.style.opacity = '0';
        setTimeout(() => oldBox.remove(), 240);
      }
    }
    if (actPillEl) {
      const oldPill = actPillEl;
      actPillEl = null;
      if (reduced()) oldPill.remove();
      else {
        oldPill.style.opacity = '0';
        setTimeout(() => oldPill.remove(), 240);
      }
    }
    actRectOf = null;
    actBox = null;
    if (spot && spot.kind === 'act') clearSpotlight();
    return true;
  }
  let actRectOf = null, actBox = null;
  // Keep the callout box on its control while the page scrolls or re-lays out (called from tick).
  function followAction() {
    if (!actRectOf || !actBoxEl) return;
    try {
      const b = pad(actRectOf(), 6);
      actBox = b;
      Object.assign(actBoxEl.style, { left: `${b.x}px`, top: `${b.y}px`, width: `${b.w}px`, height: `${b.h}px` });
    } catch (_) {
      actBox = null;
      actBoxEl.style.opacity = '0';
    }
  }
  function actionCallout(target, label, o = {}) {
    mount();
    const color = o.color || CFG.rippleColor || '#2563eb';
    let b = null;
    actRectOf = null;
    if (target) {
      // A missing control is reported by the action itself; the callout just stays off.
      try {
        actRectOf = resolveTarget(target);
        b = pad(actRectOf(), 6);
      } catch (_) {
        actRectOf = null;
      }
    }
    actBox = b;
    if (b && b.w > 0 && b.h > 0) {
      const isNew = !actBoxEl || !actBoxEl.isConnected;
      if (isNew) {
        actBoxEl = document.createElement('div');
        actBoxEl.className = 'act-box';
        if (reduced()) actBoxEl.style.transition = 'none';
        root.appendChild(actBoxEl);
      }
      actBoxEl.style.borderColor = color;
      actBoxEl.style.left = `${b.x}px`;
      actBoxEl.style.top = `${b.y}px`;
      actBoxEl.style.width = `${b.w}px`;
      actBoxEl.style.height = `${b.h}px`;
      if (isNew) {
        actBoxEl.getBoundingClientRect();
      }
      actBoxEl.style.opacity = '1';
    } else if (actBoxEl) {
      actBoxEl.style.opacity = '0';
    }
    if (label) {
      const isNew = !actPillEl || !actPillEl.isConnected;
      if (isNew) {
        actPillEl = document.createElement('div');
        actPillEl.className = 'act-pill';
        if (reduced()) actPillEl.style.transition = 'none';
        root.appendChild(actPillEl);
      }
      actPillEl.style.background = color;
      actPillEl.textContent = String(label);
      const pw = actPillEl.offsetWidth, ph = actPillEl.offsetHeight;
      let px, py;
      if (b && b.w > 0 && b.h > 0) {
        px = b.x + b.w / 2 - pw / 2;
        py = b.y - ph - 10;
        if (py < 8) py = b.y + b.h + 10;
      } else {
        px = (innerWidth - pw) / 2;
        py = 18;
      }
      px = Math.max(8, Math.min(px, innerWidth - pw - 8));
      py = Math.max(8, Math.min(py, innerHeight - ph - 8));
      actPillEl.style.left = `${px}px`;
      actPillEl.style.top = `${py}px`;
      if (isNew) {
        actPillEl.getBoundingClientRect();
      }
      actPillEl.style.opacity = '1';
    } else if (actPillEl) {
      actPillEl.style.opacity = '0';
    }
    if (o.spotlight && b && b.w > 0 && b.h > 0) makeSpot(() => [actBox], o.spotlightOpacity, 'act');
    else if (spot && spot.kind === 'act') clearSpotlight();
    return b ? [b.x, b.y, b.w, b.h, innerWidth, innerHeight] : null;
  }

  let hudEl = null;
  let hudCount = 0;
  function clearExpectHud() {
    if (hudEl) {
      const old = hudEl;
      hudEl = null;
      hudCount = 0;
      if (reduced()) old.remove();
      else old.animate([{ opacity: 1 }, { opacity: 0 }], { duration: 160, fill: 'forwards' }).onfinish = () => old.remove();
    }
    return true;
  }
  function expectHud(rows, o = {}) {
    mount();
    if (!Array.isArray(rows) || !rows.length) return clearExpectHud();
    const passC = o.passColor || CFG.passColor || '#16a34a';
    const failC = o.failColor || CFG.failColor || '#dc2626';
    const passed = rows.filter((r) => r.ok).length;
    const allOk = passed === rows.length;
    if (!hudEl) {
      hudEl = document.createElement('div');
      hudEl.className = 'exp-hud';
      root.appendChild(hudEl);
      if (!reduced()) hudEl.animate([{ opacity: 0, transform: 'translateY(-6px)' }, { opacity: 1, transform: 'none' }], { duration: 200, easing: CFG.ease, fill: 'backwards' });
    }
    const pos = o.pos || 'top-right';
    hudEl.style.top = pos.startsWith('top') ? '14px' : 'auto';
    hudEl.style.bottom = pos.startsWith('bottom') ? '14px' : 'auto';
    hudEl.style.right = pos.endsWith('right') ? '14px' : 'auto';
    hudEl.style.left = pos.endsWith('left') ? '14px' : 'auto';

    const title = o.title || 'EXPECTATIONS';
    const prevCount = hudCount;
    hudCount = rows.length;
    hudEl.innerHTML = '';
    const hdr = document.createElement('div');
    hdr.className = 'exp-hdr';
    const tspan = document.createElement('span');
    tspan.textContent = title;
    const sum = document.createElement('span');
    sum.className = 'exp-sum';
    sum.style.background = allOk ? passC : failC;
    sum.textContent = `${passed}/${rows.length} ${allOk ? 'PASS' : 'FAIL'}`;
    hdr.appendChild(tspan);
    hdr.appendChild(sum);
    hudEl.appendChild(hdr);

    const listEl = document.createElement('div');
    listEl.className = 'exp-list';
    rows.forEach((r, idx) => {
      const row = document.createElement('div');
      row.className = r.ok ? 'exp-row pass' : 'exp-row fail';
      const ico = document.createElement('div');
      ico.className = 'exp-ico';
      ico.style.background = r.ok ? passC : failC;
      ico.textContent = r.ok ? '✓' : '✗';
      const txt = document.createElement('div');
      txt.className = 'exp-txt';
      const lbl = document.createElement('div');
      lbl.className = 'exp-lbl';
      lbl.textContent = String(r.label || '');
      txt.appendChild(lbl);
      if (r.detail) {
        const det = document.createElement('div');
        det.className = 'exp-det';
        det.textContent = String(r.detail);
        txt.appendChild(det);
      }
      row.appendChild(ico);
      row.appendChild(txt);
      listEl.appendChild(row);
      if (!reduced() && idx >= prevCount) {
        row.animate([{ opacity: 0, transform: 'translateX(8px)' }, { opacity: 1, transform: 'none' }], { duration: 180, easing: CFG.ease, fill: 'backwards' });
      }
    });
    hudEl.appendChild(listEl);
    return true;
  }

  function clear(id, opts = {}) {
    const drop = (it) => {
      items.delete(it.id);
      const nodes = [it.g, it.label, it.div].filter(Boolean);
      if (it.kind === 'blur' || reduced()) return nodes.forEach((n) => n.remove());
      nodes.forEach((n) => { n.animate([{ opacity: 1 }, { opacity: 0 }], { duration: 160, easing: 'ease-in', fill: 'forwards' }).onfinish = () => n.remove(); });
    };
    if (id) { const it = items.get(id); if (it) drop(it); return; }
    clearSpotlight();
    clearAction();
    if (!opts.keepHud) clearExpectHud();
    badgeSeq = 0;
    [...items.values()].filter((it) => !it.id.startsWith('mask-')).forEach(drop);
  }
  function list() { return [...items.keys()]; }
  function config(o) {
    Object.assign(CFG, o || {});
    if (CFG.labelFont) host.style.setProperty('--ann-font', CFG.labelFont);
    return { ...CFG };
  }

  const setShown = (it, on) => [it.g, it.label, it.div].forEach((n) => { if (n) n.style.display = on ? '' : 'none'; });
  // A target that cannot be resolved any more is hidden (not frozen at a stale spot) until it comes back.
  const refresh = (it) => {
    try {
      it.update();
      if (it.hidden) { it.hidden = false; setShown(it, true); }
    } catch (_) {
      if (!it.hidden) { it.hidden = true; setShown(it, false); }
    }
  };
  let raf = 0;
  const tick = () => { raf = 0; items.forEach(refresh); followAction(); layoutSpot(); };
  const schedule = () => { if (!raf) raf = requestAnimationFrame(tick); };
  addEventListener('scroll', schedule, true);
  addEventListener('resize', schedule);
  const timer = setInterval(schedule, 250);

  const PII = {
    email: '[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\\.[A-Za-z]{2,}',
    phone: '(?<![\\d+])(?!\\d{4}-\\d\\d?-\\d\\d?(?!\\d))\\+?\\d[\\d ().-]{7,}\\d(?!\\d)',
    card: '\\b(?:\\d[ -]?){12,18}\\d\\b',
    token: '\\b(?:eyJ[\\w-]{8,}\\.[\\w-]{8,}\\.[\\w-]+|(?:sk|pk|ghp|gho|ghs|xox[abp])[-_][A-Za-z0-9_-]{10,})\\b',
  };
  const MASK = {
    re: null, selectors: [], keep: new Set(), inputs: true, done: new Map(), obs: null, raf: 0, seq: 0, loop: 0,
    watched: new WeakSet(), frames: new WeakSet(),
  };
  const nodeIds = new WeakMap();
  let nodeSeq = 0;
  const nid = (n) => { if (!nodeIds.has(n)) nodeIds.set(n, ++nodeSeq); return nodeIds.get(n); };
  const hits = (text) => (MASK.re ? [...text.matchAll(MASK.re)].filter((m) => m[0].trim() && !MASK.keep.has(m[0])) : []);
  const ZERO = () => [0, 0];
  const shifted = (rectOf, off) => (off === ZERO ? rectOf : () => {
    const r = rectOf(), [dx, dy] = off();
    return { left: r.left + dx, top: r.top + dy, width: r.width, height: r.height, right: r.right + dx, bottom: r.bottom + dy };
  });
  // Ignore only mutations caused by our own overlay host; text edits, removals and attribute flips all rescan.
  const ownMutation = (m) => m.target === host || host.contains(m.target)
    || (m.type === 'childList' && !m.removedNodes.length && [...m.addedNodes].every((x) => x === host));
  const watch = (node) => {
    if (!MASK.obs || MASK.watched.has(node)) return;
    MASK.watched.add(node);
    MASK.obs.observe(node, {
      subtree: true, childList: true, characterData: true,
      // Hidden text already has a mask (kept in place by maskFrame); only a changed value attribute adds text.
      attributes: true, attributeFilter: ['value'],
    });
  };
  // Everything to scan: the page, open shadow roots, and same-origin iframes (offset by the frame's position).
  // Cross-origin iframes cannot be read from here; the OCR pass is the safety net for those.
  function maskRoots() {
    const out = [];
    const walkDoc = (doc, off) => {
      if (!doc || !doc.body) return;
      watch(doc.documentElement);
      out.push({ q: doc, t: doc.body, off });
      shadowRoots(doc).forEach((r) => { watch(r); out.push({ q: r, t: r, off }); });
      doc.querySelectorAll('iframe,frame').forEach((f) => {
        let inner = null;
        try { inner = f.contentDocument; } catch (_) { /* cross-origin */ }
        if (!inner) return;
        if (!MASK.frames.has(f)) { MASK.frames.add(f); f.addEventListener('load', scheduleMask); }
        walkDoc(inner, () => {
          const [ox, oy] = off(), b = f.getBoundingClientRect();
          return [ox + b.left + f.clientLeft, oy + b.top + f.clientTop];
        });
      });
    };
    walkDoc(document, ZERO);
    return out;
  }
  // Blurs and masks follow their content every frame: layout shifts without scroll (accordions, transitions)
  // must not uncover hidden data for the 250 ms the regular tick would leave.
  const maskFrame = () => {
    MASK.loop = 0;
    const covers = [...items.values()].filter((it) => it.kind === 'blur');
    if (!covers.length) return;
    covers.forEach(refresh);
    MASK.loop = requestAnimationFrame(maskFrame);
  };
  const followCovers = () => { if (!MASK.loop) MASK.loop = requestAnimationFrame(maskFrame); };
  function scanMask() {
    MASK.raf = 0;
    if (!document.body) return 0;
    mount();
    const want = new Map();
    for (const { q, t, off } of maskRoots()) {
      MASK.selectors.forEach((sel) => q.querySelectorAll(sel).forEach((e) => want.set(`s${nid(e)}`, shifted(() => e.getBoundingClientRect(), off))));
      if (!MASK.re) continue;
      const walker = (t.ownerDocument || document).createTreeWalker(t, NodeFilter.SHOW_TEXT);
      for (let n = walker.nextNode(); n; n = walker.nextNode()) {
        const p = n.parentElement;
        if (!p || /^(SCRIPT|STYLE|NOSCRIPT|TEXTAREA)$/.test(p.tagName) || p.closest('#__ann_host')) continue;
        for (const m of hits(n.data)) {
          const r = (n.ownerDocument || document).createRange();
          r.setStart(n, m.index); r.setEnd(n, m.index + m[0].length);
          want.set(`t${nid(n)}:${m.index}:${m[0].length}`, shifted(() => r.getBoundingClientRect(), off));
        }
      }
      if (MASK.inputs) {
        q.querySelectorAll('input:not([type=password]):not([type=hidden]),textarea').forEach((e) => {
          if (hits(e.value || '').length) want.set(`i${nid(e)}`, shifted(() => e.getBoundingClientRect(), off));
        });
      }
    }
    want.forEach((rect, key) => { if (!MASK.done.has(key)) MASK.done.set(key, blur(rect, { id: `mask-${++MASK.seq}`, padding: 3, solid: true })); });
    MASK.done.forEach((id, key) => { if (!want.has(key)) { clear(id); MASK.done.delete(key); } });
    if (MASK.done.size) followCovers();
    return MASK.done.size;
  }
  const scheduleMask = () => { if (!MASK.raf) MASK.raf = requestAnimationFrame(scanMask); };
  function mask(o = {}) {
    const rules = (o.mask || []).map((k) => { if (!PII[k]) throw new Error(`mask: unknown rule ${k}`); return PII[k]; });
    const src = [...rules, ...(o.patterns || [])];
    MASK.re = src.length ? new RegExp(src.map((x) => `(?:${x})`).join('|'), 'g') : null;
    MASK.selectors = o.selectors || [];
    MASK.keep = new Set(o.keep || []);
    MASK.inputs = o.inputs !== false;
    if (!MASK.obs) {
      MASK.obs = new MutationObserver((ms) => { if (ms.some((m) => !ownMutation(m))) scheduleMask(); });
      addEventListener('input', scheduleMask, true);
    }
    MASK.done.forEach((id) => clear(id));
    MASK.done.clear();
    clear('mask-failsafe');
    return scanMask();
  }
  // Stop timers, listeners and observers so a newer annotate.js can take over cleanly.
  function destroy() {
    clearInterval(timer);
    removeEventListener('scroll', schedule, true);
    removeEventListener('resize', schedule);
    removeEventListener('input', scheduleMask, true);
    if (MASK.obs) MASK.obs.disconnect();
    [raf, MASK.raf, MASK.loop, curAnim].forEach((h) => h && cancelAnimationFrame(h));
    host.remove();
  }

  window.__ann = {
    version: VERSION, config, box, circle, underline, strike, arrow, callout, magnify, text, badge, highlight, blur,
    clear, list, mask,
    spotlight, bounds, cursorMove, cursorClick, cursorHide,
    targetLabel, actionCallout, clearAction, expectHud, clearExpectHud, destroy,
  };
  return VERSION;
})();
