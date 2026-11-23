/*
 * annotate.js — Snagit-style on-screen annotations for evidence recordings.
 * Inject into any page (e.g. `bsk evaluate`). Idempotent: re-injecting keeps
 * the existing instance. Everything renders inside a closed-off shadow root,
 * position:fixed, pointer-events:none, so the app under test is not affected.
 *
 * API (window.__ann):
 *   box(target, opts)            rectangle around an element / rect
 *   circle(target, opts)         ellipse around an element / rect
 *   arrow(target, opts)          arrow pointing at the element (opts.from: 'left'|'right'|'top'|'bottom'|'top-left'|...)
 *   text(target, label, opts)    floating label next to target (or at {x,y})
 *   badge(target, n, opts)       numbered step marker
 *   highlight(target, opts)      translucent marker fill
 *   blur(target, opts)           pixelate/blur sensitive content
 *   clear(id?)                   remove one annotation or all
 * target: CSS selector | Element | {x, y, w?, h?} (viewport px) | {text, within?, exact?, nth?} | {selector, rel:{x,y,w,h}}
 *         | {grid:{column?, toColumn?, row, rows?, rowHeight?, header?, body?}} (canvas data grids)
 *   config({anim, duration})     global defaults; returns current config
 * common opts: id, color ('#e5252a'), width (3), padding (6), label, labelPos, anim, duration
 * anim: 'draw' (default: strokes draw on once, then label fades in) | 'fade' | 'none'.
 *   Intros run once (no loops/blinking); blur is always instant so masked data never shows.
 * Every call returns the annotation id. Missing targets throw.
 */
(() => {
  if (window.__ann && window.__ann.version) return window.__ann.version;
  const VERSION = '0.2.0';
  const CFG = { anim: 'draw', duration: 420, ease: 'cubic-bezier(.22,.8,.24,1)' };
  const NS = 'http://www.w3.org/2000/svg';
  const host = document.createElement('div');
  host.id = '__ann_host';
  host.style.cssText = 'position:fixed;inset:0;z-index:2147483647;pointer-events:none;';
  const root = host.attachShadow({ mode: 'open' });
  root.innerHTML = `<style>
    :host{all:initial}
    svg{position:fixed;inset:0;width:100vw;height:100vh;overflow:visible}
    .lbl{position:fixed;font:600 15px/1.3 system-ui,'Segoe UI',sans-serif;color:#fff;padding:6px 10px;border-radius:6px;
         box-shadow:0 2px 8px #0005;white-space:pre-wrap;max-width:360px}
    .badge{position:fixed;width:30px;height:30px;border-radius:50%;color:#fff;font:700 16px/30px system-ui,sans-serif;
           text-align:center;box-shadow:0 2px 6px #0006;border:2px solid #fff}
    .blur{position:fixed;backdrop-filter:blur(8px);-webkit-backdrop-filter:blur(8px);background:#ffffff33;border-radius:4px}
    .sh{filter:drop-shadow(0 1px 1.5px rgba(0,0,0,.35))}
  </style><svg></svg>`;
  const svg = root.querySelector('svg');
  const mount = () => { if (!host.isConnected) (document.body || document.documentElement).appendChild(host); };
  mount();

  const items = new Map();
  let seq = 0;

  const visible = (e) => { const r = e.getBoundingClientRect(); return r.width > 0 && r.height > 0; };
  const pick = (sel) => [...document.querySelectorAll(sel)].find(visible) || null;
  const resolveTarget = (t) => {
    if (t instanceof Element) return () => t.getBoundingClientRect();
    if (typeof t === 'string') {
      const el = pick(t);
      if (!el) throw new Error(`annotate: target not found: ${t}`);
      return () => el.getBoundingClientRect();
    }
    if (typeof t === 'object' && t && typeof t.text === 'string') {
      const scope = t.within ? document.querySelector(t.within) : document.body;
      if (!scope) throw new Error(`annotate: scope not found: ${t.within}`);
      const want = t.text.trim(), nth = t.nth || 0, hits = [];
      const walker = document.createTreeWalker(scope, NodeFilter.SHOW_ELEMENT);
      for (let n = walker.currentNode; n; n = walker.nextNode()) {
        if (n.closest('#__ann_host')) continue;
        const txt = (n.innerText || n.textContent || '').trim();
        const ok = t.exact === false ? txt.includes(want) : txt === want;
        const r = n.getBoundingClientRect();
        if (!ok || !r.width || !r.height) continue;
        if ([...n.children].some((c) => ((c.innerText || c.textContent || '').trim() === txt))) continue;
        hits.push(n);
      }
      const found = hits[nth];
      if (!found) throw new Error(`annotate: text not found: ${want}`);
      return () => found.getBoundingClientRect();
    }
    if (t && t.grid) {
      // Cell of a canvas-rendered data grid whose header row is DOM (e.g. DBX):
      // x/width from the matching header cell, y from body top + (row-1)*rowHeight.
      const g = { header: '.data-grid-header-cell', body: 'canvas.canvas-grid-surface', rowHeight: 26, row: 1, ...t.grid };
      const body = pick(g.body);
      if (!body) throw new Error(`annotate: grid body not found: ${g.body}`);
      const heads = [...document.querySelectorAll(g.header)].filter(visible);
      const name = (h) => (h.innerText || '').trim().split('\n')[0].trim();
      const cols = g.column ? heads.filter((h) => name(h) === g.column) : heads;
      if (!cols.length) throw new Error(`annotate: grid column not found: ${g.column}`);
      const last = g.toColumn ? heads.find((h) => name(h) === g.toColumn) || cols[0] : cols[0];
      return () => {
        const a = cols[0].getBoundingClientRect(), z = last.getBoundingClientRect(), b = body.getBoundingClientRect();
        const left = g.column ? a.left : b.left, right = g.column ? z.right : b.right;
        const top = b.top + (g.row - 1) * g.rowHeight, height = g.rowHeight * (g.rows || 1);
        return { left, top, width: right - left, height, right, bottom: top + height };
      };
    }
    if (t && typeof t.selector === 'string') {
      // Region relative to an element, e.g. a cell inside a canvas data grid.
      const host = pick(t.selector);
      if (!host) throw new Error(`annotate: target not found: ${t.selector}`);
      const rel = t.rel || {};
      return () => {
        const b = host.getBoundingClientRect();
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
  const defaults = (o = {}) => ({ color: '#e5252a', width: 3, padding: 6, ...o });

  function makeLabel(text, color) {
    const d = document.createElement('div');
    d.className = 'lbl';
    d.style.background = color;
    d.textContent = text;
    root.appendChild(d);
    return d;
  }
  function placeLabel(d, b, pos) {
    const lw = d.offsetWidth, lh = d.offsetHeight, gap = 10;
    let x, y;
    switch (pos) {
      case 'top': x = b.x; y = b.y - lh - gap; break;
      case 'left': x = b.x - lw - gap; y = b.y + (b.h - lh) / 2; break;
      case 'bottom': x = b.x; y = b.y + b.h + gap; break;
      default: x = b.x + b.w + gap; y = b.y + (b.h - lh) / 2;
    }
    x = Math.max(4, Math.min(x, innerWidth - lw - 4));
    y = Math.max(4, Math.min(y, innerHeight - lh - 4));
    d.style.left = `${x}px`; d.style.top = `${y}px`;
  }

  function add(kind, target, o, build) {
    mount();
    const opts = defaults(o);
    const rectOf = resolveTarget(target);
    const id = opts.id || `${kind}-${++seq}`;
    clear(id);
    const g = el('g', {});
    if (kind !== 'highlight') g.setAttribute('class', 'sh');
    svg.appendChild(g);
    const label = opts.label ? makeLabel(opts.label, opts.color) : null;
    const item = { id, kind, g, label, nodes: [], update: null };
    item.update = () => {
      const b = pad(rectOf(), opts.padding);
      build(item, b, opts);
      if (label && opts.labelPos !== 'none') placeLabel(label, b, opts.labelPos);
    };
    item.update();
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
    return add('circle', target, { padding: 12, ...o }, (item, b, opts) => {
      const [e] = once(item, () => [el('ellipse', { fill: 'none' })]);
      Object.entries({ cx: b.x + b.w / 2, cy: b.y + b.h / 2, rx: b.w / 2, ry: b.h / 2, stroke: opts.color, 'stroke-width': opts.width }).forEach(([k, v]) => e.setAttribute(k, v));
    });
  }
  function highlight(target, o) {
    return add('highlight', target, { color: '#ffd400', padding: 2, ...o }, (item, b, opts) => {
      const [r] = once(item, () => [el('rect', { rx: 3 })]);
      Object.entries({ x: b.x, y: b.y, width: b.w, height: b.h, fill: opts.color, 'fill-opacity': 0.35 }).forEach(([k, v]) => r.setAttribute(k, v));
    });
  }
  const DIRS = { left: [-1, 0], right: [1, 0], top: [0, -1], bottom: [0, 1], 'top-left': [-0.7, -0.7], 'top-right': [0.7, -0.7], 'bottom-left': [-0.7, 0.7], 'bottom-right': [0.7, 0.7] };
  function arrow(target, o) {
    return add('arrow', target, { padding: 4, length: 110, from: 'right', labelPos: undefined, ...o }, (item, b, opts) => {
      const [dx, dy] = DIRS[opts.from] || DIRS.right;
      const cx = b.x + b.w / 2, cy = b.y + b.h / 2;
      const tipX = cx + dx * (b.w / 2), tipY = cy + dy * (b.h / 2);
      const tailX = tipX + dx * opts.length, tailY = tipY + dy * opts.length;
      const ang = Math.atan2(tipY - tailY, tipX - tailX), hl = 18;
      const [line, head] = once(item, () => [el('line', { 'stroke-linecap': 'round' }), el('polygon', {})]);
      Object.entries({ x1: tailX, y1: tailY, x2: tipX - Math.cos(ang) * hl * 0.6, y2: tipY - Math.sin(ang) * hl * 0.6, stroke: opts.color, 'stroke-width': opts.width + 2 }).forEach(([k, v]) => line.setAttribute(k, v));
      const p = (a) => `${tipX - hl * Math.cos(ang - a)},${tipY - hl * Math.sin(ang - a)}`;
      head.setAttribute('points', `${tipX},${tipY} ${p(0.45)} ${p(-0.45)}`);
      head.setAttribute('fill', opts.color);
      if (item.label) {
        const lw = item.label.offsetWidth, lh = item.label.offsetHeight;
        let lx = tailX + (dx < 0 ? -lw - 6 : dx > 0 ? 6 : -lw / 2), ly = tailY + (dy < 0 ? -lh - 6 : dy > 0 ? 6 : -lh / 2);
        item.label.style.left = `${Math.max(4, Math.min(lx, innerWidth - lw - 4))}px`;
        item.label.style.top = `${Math.max(4, Math.min(ly, innerHeight - lh - 4))}px`;
        opts.labelPos = 'none';
      }
    });
  }
  function text(target, label, o) {
    const opts = defaults({ padding: 0, ...o });
    return add('text', target, { ...opts, label }, () => {});
  }
  function badge(target, n, o) {
    return add('badge', target, { padding: 0, color: '#1f6feb', ...o }, (item, b, opts) => {
      if (!item.div) { item.div = document.createElement('div'); item.div.className = 'badge'; item.div.textContent = String(n); root.appendChild(item.div); }
      item.div.style.background = opts.color;
      item.div.style.left = `${b.x - 15}px`; item.div.style.top = `${b.y - 15}px`;
    });
  }
  function blur(target, o) {
    return add('blur', target, { padding: 2, ...o }, (item, b) => {
      if (!item.div) { item.div = document.createElement('div'); item.div.className = 'blur'; root.appendChild(item.div); }
      Object.assign(item.div.style, { left: `${b.x}px`, top: `${b.y}px`, width: `${b.w}px`, height: `${b.h}px` });
    });
  }
  function clear(id) {
    const drop = (it) => {
      items.delete(it.id);
      const nodes = [it.g, it.label, it.div].filter(Boolean);
      if (it.kind === 'blur' || reduced()) return nodes.forEach((n) => n.remove());
      nodes.forEach((n) => { n.animate([{ opacity: 1 }, { opacity: 0 }], { duration: 160, easing: 'ease-in', fill: 'forwards' }).onfinish = () => n.remove(); });
    };
    if (id) { const it = items.get(id); if (it) drop(it); return; }
    [...items.values()].forEach(drop);
  }
  function list() { return [...items.keys()]; }
  function config(o) { Object.assign(CFG, o || {}); return { ...CFG }; }

  let raf = 0;
  const tick = () => { raf = 0; items.forEach((it) => { try { it.update(); } catch (_) { /* target detached */ } }); };
  const schedule = () => { if (!raf) raf = requestAnimationFrame(tick); };
  addEventListener('scroll', schedule, true);
  addEventListener('resize', schedule);
  setInterval(schedule, 250);

  window.__ann = { version: VERSION, config, box, circle, arrow, text, badge, highlight, blur, clear, list };
  return VERSION;
})();
