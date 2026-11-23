// Scenario `targets:` -> data-tirai-id. Each target lists locators tried in order; the first that matches
// exactly one element (visible ones preferred) tags it. Also builds the element map for `tirai inspect`.
(() => {
  if (window.__tiraiT) return;
  const ATTR = 'data-tirai-id';
  const norm = (s) => (s || '').replace(/\s+/g, ' ').trim();
  const ROLES = {
    textbox: 'input:not([type=button]):not([type=submit]):not([type=reset]):not([type=checkbox]):not([type=radio]):not([type=hidden]):not([type=file]):not([type=search]),textarea,[contenteditable=true],[role=textbox]',
    searchbox: 'input[type=search],[role=searchbox]',
    button: 'button,input[type=submit],input[type=button],input[type=reset],[role=button]',
    link: 'a[href],[role=link]',
    combobox: 'select,[role=combobox]',
    checkbox: 'input[type=checkbox],[role=checkbox]',
    radio: 'input[type=radio],[role=radio]',
    heading: 'h1,h2,h3,h4,h5,h6,[role=heading]',
    tab: '[role=tab]',
    menuitem: '[role=menuitem]',
    option: 'option,[role=option]',
    cell: 'td,[role=cell],[role=gridcell]',
    row: 'tr,[role=row]',
    dialog: 'dialog,[role=dialog]',
    img: 'img[alt],[role=img]',
  };
  const labelOf = (e) => {
    if (e.getAttribute('aria-label')) return e.getAttribute('aria-label');
    const by = e.getAttribute('aria-labelledby');
    if (by) return by.split(/\s+/).map((id) => document.getElementById(id)?.innerText || '').join(' ');
    if (e.id) { const l = document.querySelector(`label[for="${CSS.escape(e.id)}"]`); if (l) return l.innerText; }
    const wrap = e.closest('label'); if (wrap) return wrap.innerText;
    return '';
  };
  const nameOf = (e) => norm(labelOf(e) || (e.matches('input,textarea,select') ? e.getAttribute('placeholder') || (e.type === 'submit' || e.type === 'button' ? e.value : '') : e.innerText) || e.getAttribute('title') || e.getAttribute('alt') || '');
  const roleOf = (e) => {
    const r = e.getAttribute('role'); if (r) return r;
    for (const [role, sel] of Object.entries(ROLES)) if (e.matches(sel)) return role;
    return e.tagName.toLowerCase();
  };
  const visible = (e) => { const r = e.getBoundingClientRect(); const s = getComputedStyle(e); return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none'; };
  const unquote = (s) => s.replace(/^["']|["']$/g, '');
  // Locator forms: testid=, role=x[name="…"], label=, placeholder=, text=, text*=, css=, or plain CSS.
  const locate = (loc, root = document) => {
    let m;
    if ((m = /^testid=(.+)$/s.exec(loc))) { const v = CSS.escape(unquote(m[1])); return [...root.querySelectorAll(`[data-testid="${v}"],[data-test-id="${v}"],[data-test="${v}"],[data-qa="${v}"],[data-cy="${v}"]`)]; }
    if ((m = /^role=([\w-]+)(?:\[name=(.+)\])?$/s.exec(loc))) {
      const els = [...root.querySelectorAll(ROLES[m[1]] || `[role=${m[1]}]`)];
      return m[2] === undefined ? els : els.filter((e) => nameOf(e) === norm(unquote(m[2])));
    }
    if ((m = /^label=(.+)$/s.exec(loc))) { const v = norm(unquote(m[1])); return [...root.querySelectorAll('input,textarea,select,[role=textbox],[role=combobox],[role=checkbox]')].filter((e) => norm(labelOf(e)) === v); }
    if ((m = /^placeholder=(.+)$/s.exec(loc))) { const v = unquote(m[1]); return [...root.querySelectorAll('[placeholder]')].filter((e) => e.getAttribute('placeholder') === v); }
    if ((m = /^text(\*?)=(.+)$/s.exec(loc))) {
      const v = norm(unquote(m[2])), part = m[1] === '*';
      const hit = (e) => { const t = norm(e.innerText); return part ? t.includes(v) : t === v; };
      const all = [...root.querySelectorAll('body *')].filter((e) => !/^(SCRIPT|STYLE|NOSCRIPT)$/.test(e.tagName) && hit(e));
      return all.filter((e) => !all.some((o) => o !== e && e.contains(o)));
    }
    return [...root.querySelectorAll(loc.replace(/^css=/, ''))];
  };
  const short = (e) => e.tagName.toLowerCase() + (e.id ? `#${e.id}` : '') + (typeof e.className === 'string' && e.className.trim() ? `.${e.className.trim().split(/\s+/)[0]}` : '');
  const brief = (e) => { const p = e.parentElement?.closest('[id],form,section,article,li,tr,dialog,nav,header,footer,main'); return short(e) + (p ? ` in ${short(p)}` : ''); };
  const pick = (els) => { if (els.length <= 1) return els; const v = els.filter(visible); return v.length ? v : els; };
  const find = (t) => {
    const counts = [];
    let root = document;
    if (t.within) { root = document.querySelector(t.within); if (!root) return { el: null, via: -1, counts: [`within ${t.within}: not found`] }; }
    for (let i = 0; i < t.locators.length; i++) {
      let els;
      try { els = pick(locate(t.locators[i], root)); } catch (e) { counts.push(`${t.locators[i]}: invalid`); continue; }
      if (t.nth !== undefined && t.nth !== null) els = els[t.nth] ? [els[t.nth]] : [];
      counts.push(`${t.locators[i]}: ${els.length}` + (els.length > 1 ? ` [${els.slice(0, 3).map(brief).join(', ')}${els.length > 3 ? ', …' : ''}]` : ''));
      if (els.length === 1) return { el: els[0], via: i, counts };
    }
    return { el: null, via: -1, counts };
  };
  // One element can be several targets: the attribute holds space-separated ids, matched with ~=.
  const ids = (e) => (e.getAttribute(ATTR) || '').split(/\s+/).filter(Boolean);
  const setIds = (e, list) => (list.length ? e.setAttribute(ATTR, list.join(' ')) : e.removeAttribute(ATTR));
  let targets = {};
  const report = {};
  const tag = (t) => {
    if (t) targets = t;
    for (const [id, spec] of Object.entries(targets)) {
      const sel = `[${ATTR}~="${CSS.escape(id)}"]`;
      const cur = document.querySelector(sel);
      if (cur && report[id] && report[id].ok) continue;
      const r = find(spec);
      document.querySelectorAll(sel).forEach((e) => e !== r.el && setIds(e, ids(e).filter((x) => x !== id)));
      if (r.el && !ids(r.el).includes(id)) setIds(r.el, [...ids(r.el), id]);
      report[id] = { ok: !!r.el, via: r.via, counts: r.counts };
    }
    if (!window.__tiraiObs && document.documentElement) {
      let pending = 0;
      window.__tiraiObs = new MutationObserver(() => { clearTimeout(pending); pending = setTimeout(() => tag(), 25); });
      window.__tiraiObs.observe(document.documentElement, { childList: true, subtree: true, attributes: true, attributeFilter: ['id', 'class', 'aria-label', 'data-testid', 'hidden', 'style'] });
    }
    return report;
  };
  const unique = (loc, e) => { try { const els = pick(locate(loc)); return els.length === 1 && els[0] === e; } catch (_) { return false; } };
  const q = (v) => JSON.stringify(v);
  const generated = (v) => /\d{4,}|(?=[a-f]*\d)[a-f0-9]{8,}|^[a-z]{1,3}-?(?=[a-z]*\d)[0-9a-z]{5,}$|^:r|^(ember|react|mui|radix|headlessui)/i.test(v);
  const locatorsFor = (e) => {
    const out = [], tag = e.tagName.toLowerCase(), role = roleOf(e), name = nameOf(e);
    for (const a of ['data-testid', 'data-test-id', 'data-test', 'data-qa', 'data-cy']) if (e.getAttribute(a)) out.push(`testid=${e.getAttribute(a)}`);
    if (e.id && !generated(e.id)) out.push(`#${CSS.escape(e.id)}`);
    if (e.getAttribute('name') && !generated(e.getAttribute('name'))) out.push(`${tag}[name=${q(e.getAttribute('name'))}]`);
    if (name && name.length <= 60) out.push(`role=${role}[name=${q(name)}]`);
    const lab = norm(labelOf(e)); if (lab && lab !== name) out.push(`label=${q(lab)}`);
    if (e.getAttribute('placeholder')) out.push(`placeholder=${q(e.getAttribute('placeholder'))}`);
    const txt = norm(e.innerText); if (txt && txt.length <= 40 && !e.matches('input,textarea,select')) out.push(`text=${q(txt)}`);
    return [...new Set(out)].filter((l) => unique(l, e));
  };
  const INTERACTIVE = 'a[href],button,input:not([type=hidden]),select,textarea,[role=button],[role=link],[role=tab],[role=menuitem],[role=checkbox],[role=radio],[role=combobox],[role=textbox],[contenteditable=true],h1,h2,h3,[data-testid],[data-test],[data-qa],[data-cy],[role=alert],[role=status],[aria-live],[id]';
  const slug = (s) => norm(s).toLowerCase().normalize('NFD').replace(/[\u0300-\u036f]/g, '').replace(/[^a-z0-9]+/g, '_').replace(/^_|_$/g, '').slice(0, 30);
  const listed = (e) => !e.matches('html,body') && !e.closest('[id^="__"]') && (!e.matches('[id]') || e.matches(INTERACTIVE.replace(',[id]', '')) || (!generated(e.id) && norm(e.innerText).length <= 80 && e.children.length <= 3));
  const elements = (limit = 300) => [...document.querySelectorAll(INTERACTIVE)].filter((e) => visible(e) && listed(e)).slice(0, limit).map((e) => {
    const role = roleOf(e), name = nameOf(e).slice(0, 80);
    return { id: slug(`${name || e.id || e.getAttribute('name') || ''} ${role}`) || role, role, name, locators: locatorsFor(e), tagged: ids(e).find((x) => !x.startsWith('_t')) || null };
  });
  // "Did you mean": elements whose locators/name share a word with (or are a near-typo of) what matched nothing.
  const LOC_WORDS = /^(role|name|text|label|placeholder|testid|css|data|tirai|input|button|div|span)$/;
  const wordsOf = (s) => (s.toLowerCase().match(/[a-z0-9]{3,}/g) || []).filter((w) => !LOC_WORDS.test(w));
  const dist = (a, b) => {
    const d = Array.from({ length: a.length + 1 }, (_, i) => [i, ...Array(b.length).fill(0)]);
    for (let j = 1; j <= b.length; j++) d[0][j] = j;
    for (let i = 1; i <= a.length; i++) for (let j = 1; j <= b.length; j++)
    {
      d[i][j] = Math.min(d[i - 1][j] + 1, d[i][j - 1] + 1, d[i - 1][j - 1] + (a[i - 1] === b[j - 1] ? 0 : 1));
      if (i > 1 && j > 1 && a[i - 1] === b[j - 2] && a[i - 2] === b[j - 1]) d[i][j] = Math.min(d[i][j], d[i - 2][j - 2] + 1);
    }
    return d[a.length][b.length];
  };
  const near = (sel, limit = 5) => {
    const want = wordsOf(sel);
    const roleWanted = (/role=([\w-]+)/.exec(sel) || [])[1];
    const score = (x) => {
      const have = wordsOf([x.name, ...x.locators].join(' '));
      let n = 0;
      for (const w of want) {
        let best = 0;
        for (const h of have) best = Math.max(best, h === w ? 2 : (h.includes(w) || w.includes(h)) ? 1.5 : dist(h, w) <= Math.max(1, Math.floor(w.length / 4)) ? 1 : 0);
        n += best;
      }
      return n && roleWanted === x.role ? n + 0.5 : n;
    };
    return elements().map((x) => ({ x, s: score(x) })).filter((r) => r.s > 0 && r.x.locators.length)
      .sort((a, b) => b.s - a.s).slice(0, limit).map((r) => `${r.x.locators[0]} (${r.x.role} ${q(r.x.name)})`);
  };
  window.__tiraiT = { tag, find, locate, elements, near, report };
})();
