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
 *   blur(target, opts)           pixelate/blur sensitive content (opts.solid: opaque cover)
 *   clear(id?)                   remove one annotation or all (auto masks stay)
 *   mask({mask, patterns, selectors, keep, inputs})  auto-blur PII and keep it blurred as the DOM changes
 *                                mask: built-in rules (email, phone, card, token); patterns: extra regex sources;
 *                                selectors: always-blurred elements; keep: exact strings left visible
 * target: CSS selector | Element | {x, y, w?, h?} (viewport px) | {text, within?, exact?, nth?} | {selector, rel:{x,y,w,h}}
 *         | {grid:{column?, toColumn?, row, rows?, rowHeight?, header?, body?}} (canvas data grids)
 *   config({anim, duration})     global defaults; returns current config
 * common opts: id, color ('#e5252a'), width (3), padding (6), label, labelPos, anim, duration
 * anim: 'draw' (default: strokes draw on once, then label fades in) | 'fade' | 'none'.
 *   Intros run once (no loops/blinking); blur is always instant so masked data never shows.
 * Every call returns the annotation id. Missing targets throw.
 */
(() => {
  const VERSION = '0.4.0';
  if (window.__ann && window.__ann.version === VERSION) return VERSION;
  document.getElementById('__ann_host')?.remove();
  const CFG = {
    anim: 'draw',
    duration: 420,
    ease: 'cubic-bezier(.22,.8,.24,1)',
    color: '#e5252a',
    labelFont: "system-ui,'Segoe UI',sans-serif",
    cursorColor: '#111827',
    rippleColor: '#2563eb',
    spotlightOpacity: 0.30,
  };
  const NS = 'http://www.w3.org/2000/svg';
  const host = document.createElement('div');
  host.id = '__ann_host';
  host.style.cssText = 'position:fixed;inset:0;z-index:2147483647;pointer-events:none;';
  const root = host.attachShadow({ mode: 'open' });
  root.innerHTML = `<style>
    :host{all:initial}
    svg{position:fixed;inset:0;width:100vw;height:100vh;overflow:visible}
    .lbl{position:fixed;font:600 15px/1.3 var(--ann-font,system-ui,'Segoe UI',sans-serif);color:#fff;padding:6px 10px;border-radius:6px;
         box-shadow:0 2px 8px #0005;white-space:pre-wrap;max-width:360px}
    .badge{position:fixed;width:30px;height:30px;border-radius:50%;color:#fff;font:700 16px/30px system-ui,sans-serif;
           text-align:center;box-shadow:0 2px 6px #0006;border:2px solid #fff}
    .blur{position:fixed;backdrop-filter:blur(12px);-webkit-backdrop-filter:blur(12px);background:#cbd5e1b3;border-radius:4px}
    .blur.solid{background:#cbd5e1}
    .sh{filter:drop-shadow(0 1px 1.5px rgba(0,0,0,.35))}
    .cur{position:fixed;left:0;top:0;width:28px;height:28px;pointer-events:none;z-index:10;
         filter:drop-shadow(0 2px 4px rgba(0,0,0,.45));transform-origin:4px 3px;will-change:transform;display:none}
    .rpl{position:fixed;border-radius:50%;pointer-events:none;z-index:9;border:3px solid var(--rpl-c,#2563eb);
         background:color-mix(in srgb,var(--rpl-c,#2563eb) 22%,transparent);transform:translate(-50%,-50%)}
  </style><svg></svg>`;
  const svg = root.querySelector('svg');
  const mount = () => { if (!host.isConnected) (document.body || document.documentElement).appendChild(host); };
  mount();

  const items = new Map();
  let seq = 0;

  const visible = (e) => { const r = e.getBoundingClientRect(); return r.width > 0 && r.height > 0; };
  const pick = (sel) => [...document.querySelectorAll(sel)].find(visible) || null;
  const resolveTarget = (t) => {
    if (typeof t === 'function') return t;
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
  const defaults = (o = {}) => ({ color: CFG.color || '#e5252a', width: 3, padding: 6, ...o });

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
      item._lastBox = b;
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
      if (!item.div) { item.div = document.createElement('div'); item.div.className = o.solid ? 'blur solid' : 'blur'; root.appendChild(item.div); }
      Object.assign(item.div.style, { left: `${b.x}px`, top: `${b.y}px`, width: `${b.w}px`, height: `${b.h}px` });
    });
  }
  let spotEl = null;
  function clearSpotlight() {
    if (!spotEl) return;
    const old = spotEl;
    spotEl = null;
    if (reduced()) return old.remove();
    old.animate([{ opacity: 1 }, { opacity: 0 }], { duration: 180, fill: 'forwards' }).onfinish = () => old.remove();
  }
  function spotlight(opacity) {
    mount();
    clearSpotlight();
    const active = [...items.values()].filter((it) => !it.id.startsWith('mask-') && it.kind !== 'blur');
    if (!active.length) return false;
    const op = typeof opacity === 'number' ? opacity : CFG.spotlightOpacity;
    if (!(op > 0)) return false;
    const maskId = `ann-spot-${++seq}`;
    const g = el('g', { 'data-spot': '1' });
    const defs = el('defs', {});
    const m = el('mask', { id: maskId });
    m.appendChild(el('rect', { x: 0, y: 0, width: innerWidth, height: innerHeight, fill: '#fff' }));
    active.forEach((it) => {
      try {
        const r = it._lastBox;
        if (r && r.w > 0 && r.h > 0) {
          m.appendChild(el('rect', { x: r.x - 10, y: r.y - 10, width: r.w + 20, height: r.h + 20, rx: 10, fill: '#000' }));
        }
      } catch (_) {}
    });
    defs.appendChild(m);
    g.appendChild(defs);
    g.appendChild(el('rect', { x: 0, y: 0, width: innerWidth, height: innerHeight, fill: `rgba(15,23,42,${op})`, mask: `url(#${maskId})` }));
    svg.insertBefore(g, svg.firstChild);
    spotEl = g;
    if (!reduced()) g.animate([{ opacity: 0 }, { opacity: 1 }], { duration: 320, easing: CFG.ease, fill: 'backwards' });
    return true;
  }
  function bounds() {
    const active = [...items.values()].filter((it) => !it.id.startsWith('mask-') && it.kind !== 'blur');
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

  function clear(id) {
    const drop = (it) => {
      items.delete(it.id);
      const nodes = [it.g, it.label, it.div].filter(Boolean);
      if (it.kind === 'blur' || reduced()) return nodes.forEach((n) => n.remove());
      nodes.forEach((n) => { n.animate([{ opacity: 1 }, { opacity: 0 }], { duration: 160, easing: 'ease-in', fill: 'forwards' }).onfinish = () => n.remove(); });
    };
    if (id) { const it = items.get(id); if (it) drop(it); return; }
    clearSpotlight();
    [...items.values()].filter((it) => !it.id.startsWith('mask-')).forEach(drop);
  }
  function list() { return [...items.keys()]; }
  function config(o) {
    Object.assign(CFG, o || {});
    if (CFG.labelFont) host.style.setProperty('--ann-font', CFG.labelFont);
    return { ...CFG };
  }

  let raf = 0;
  const tick = () => { raf = 0; items.forEach((it) => { try { it.update(); } catch (_) { /* target detached */ } }); };
  const schedule = () => { if (!raf) raf = requestAnimationFrame(tick); };
  addEventListener('scroll', schedule, true);
  addEventListener('resize', schedule);
  setInterval(schedule, 250);

  const PII = {
    email: '[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\\.[A-Za-z]{2,}',
    phone: '(?<![\\d+])(?!\\d{4}-\\d\\d?-\\d\\d?(?!\\d))\\+?\\d[\\d ().-]{7,}\\d(?!\\d)',
    card: '\\b(?:\\d[ -]?){12,18}\\d\\b',
    token: '\\b(?:eyJ[\\w-]{8,}\\.[\\w-]{8,}\\.[\\w-]+|(?:sk|pk|ghp|gho|ghs|xox[abp])[-_][A-Za-z0-9_-]{10,})\\b',
  };
  const MASK = { re: null, selectors: [], keep: new Set(), inputs: true, done: new Map(), obs: null, raf: 0, seq: 0 };
  const nodeIds = new WeakMap();
  let nodeSeq = 0;
  const nid = (n) => { if (!nodeIds.has(n)) nodeIds.set(n, ++nodeSeq); return nodeIds.get(n); };
  const hits = (text) => (MASK.re ? [...text.matchAll(MASK.re)].filter((m) => m[0].trim() && !MASK.keep.has(m[0])) : []);
  function scanMask() {
    MASK.raf = 0;
    if (!document.body) return 0;
    mount();
    const want = new Map();
    MASK.selectors.forEach((sel) => document.querySelectorAll(sel).forEach((e) => want.set(`s${nid(e)}`, () => e.getBoundingClientRect())));
    if (MASK.re) {
      const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
      for (let n = walker.nextNode(); n; n = walker.nextNode()) {
        const p = n.parentElement;
        if (!p || /^(SCRIPT|STYLE|NOSCRIPT|TEXTAREA)$/.test(p.tagName) || p.closest('#__ann_host')) continue;
        for (const m of hits(n.data)) {
          const r = document.createRange();
          r.setStart(n, m.index); r.setEnd(n, m.index + m[0].length);
          want.set(`t${nid(n)}:${m.index}:${m[0].length}`, () => r.getBoundingClientRect());
        }
      }
      if (MASK.inputs) {
        document.querySelectorAll('input:not([type=password]):not([type=hidden]),textarea').forEach((e) => {
          if (hits(e.value || '').length) want.set(`i${nid(e)}`, () => e.getBoundingClientRect());
        });
      }
    }
    want.forEach((rect, key) => { if (!MASK.done.has(key)) MASK.done.set(key, blur(rect, { id: `mask-${++MASK.seq}`, padding: 3, solid: true })); });
    MASK.done.forEach((id, key) => { if (!want.has(key)) { clear(id); MASK.done.delete(key); } });
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
      MASK.obs = new MutationObserver((ms) => { if (ms.some((m) => m.target !== host && !host.contains(m.target) && ![...m.addedNodes].every((x) => x === host))) scheduleMask(); });
      MASK.obs.observe(document.documentElement, { subtree: true, childList: true, characterData: true });
      addEventListener('input', scheduleMask, true);
    }
    MASK.done.forEach((id) => clear(id));
    MASK.done.clear();
    return scanMask();
  }

  window.__ann = {
    version: VERSION, config, box, circle, arrow, text, badge, highlight, blur, clear, list, mask,
    spotlight, bounds, cursorMove, cursorClick, cursorHide,
  };
  return VERSION;
})();
