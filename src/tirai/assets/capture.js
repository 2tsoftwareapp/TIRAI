// TIRAI capture recorder: registered as a page init script, it logs what a person does (clicks, field changes,
// Enter) with a stable CSS selector into sessionStorage so `tirai capture` can drain it across navigations.
(() => {
  if (window.__tiraiRec) return;
  const KEY = '__tirai_rec';
  const esc = (s) => (window.CSS && CSS.escape ? CSS.escape(s) : s.replace(/[^\w-]/g, '\\$&'));
  const unique = (sel) => { try { return document.querySelectorAll(sel).length === 1; } catch (e) { return false; } };
  function selector(el) {
    if (el.id && unique(`#${esc(el.id)}`)) return `#${esc(el.id)}`;
    for (const a of ['data-testid', 'data-test', 'data-qa', 'name', 'aria-label']) {
      const v = el.getAttribute(a);
      const sel = v && `${el.localName}[${a}="${v.replace(/"/g, '\\"')}"]`;
      if (sel && unique(sel)) return sel;
    }
    const parts = [];
    for (let n = el; n && n.nodeType === 1 && n !== document.documentElement; n = n.parentElement) {
      if (n.id && unique(`#${esc(n.id)}`)) { parts.unshift(`#${esc(n.id)}`); break; }
      const same = n.parentElement ? [...n.parentElement.children].filter((c) => c.localName === n.localName) : [];
      parts.unshift(same.length > 1 ? `${n.localName}:nth-of-type(${same.indexOf(n) + 1})` : n.localName);
      if (unique(parts.join(' > '))) break;
    }
    return parts.join(' > ');
  }
  function label(el) {
    const byFor = el.id && document.querySelector(`label[for="${esc(el.id)}"]`);
    const text = el.getAttribute('aria-label') || (byFor && byFor.innerText) || (el.closest('label') || {}).innerText
      || el.getAttribute('placeholder') || el.getAttribute('name') || el.innerText || el.value || el.id || el.localName;
    return String(text).trim().replace(/\s+/g, ' ').slice(0, 60);
  }
  const textual = (el) => el.matches('textarea, input:not([type]), input[type=text], input[type=email], input[type=password],'
    + ' input[type=search], input[type=tel], input[type=url], input[type=number], input[type=date], [contenteditable=""], [contenteditable=true]');
  function push(ev) {
    const q = JSON.parse(sessionStorage.getItem(KEY) || '[]');
    q.push({ ...ev, url: location.href, t: Date.now() });
    sessionStorage.setItem(KEY, JSON.stringify(q));
  }
  const target = (e) => (e.target && e.target.nodeType === 1 ? e.target : null);
  addEventListener('click', (e) => {
    let el = target(e);
    if (!el || textual(el) || el.matches('select, option')) return;
    el = el.closest('a, button, [role=button], [role=link], [role=tab], [role=menuitem], input, label, summary') || el;
    push({ op: 'click', selector: selector(el), role: el.getAttribute('role') || el.localName, name: label(el) });
  }, true);
  addEventListener('input', (e) => {
    const el = target(e);
    if (!el || !textual(el)) return;
    const base = { selector: selector(el), role: el.localName, name: label(el) };
    push(el.type === 'password' ? { op: 'fill', redacted: true, ...base } : { op: 'fill', value: el.value, ...base });
  }, true);
  addEventListener('change', (e) => {
    const el = target(e);
    if (!el) return;
    const base = { selector: selector(el), role: el.localName, name: label(el) };
    if (el.matches('select')) push({ op: 'select', value: el.value, ...base });
    else if (el.matches('input[type=checkbox], input[type=radio]')) return;
    else if (textual(el)) push(el.type === 'password' ? { op: 'fill', redacted: true, ...base } : { op: 'fill', value: el.value, ...base });
  }, true);
  addEventListener('keydown', (e) => {
    const el = target(e);
    if (e.key !== 'Enter' || !el || el.matches('textarea')) return;
    if (textual(el)) {
      const base = { selector: selector(el), role: el.localName, name: label(el) };
      push(el.type === 'password' ? { op: 'fill', redacted: true, ...base } : { op: 'fill', value: el.value, ...base });
      push({ op: 'press', key: 'Enter', ...base });
    }
  }, true);
  window.__tiraiRec = {
    drain() {
      const q = JSON.parse(sessionStorage.getItem(KEY) || '[]');
      sessionStorage.removeItem(KEY);
      const texts = [...document.querySelectorAll('h1, h2, h3, [role=alert], [role=status], .alert, .toast, .flash, .error, .success')]
        .map((n) => n.innerText.trim().replace(/\s+/g, ' ')).filter((t) => t && t.length < 120).slice(0, 20);
      return { events: q, url: location.href, texts, t: Date.now() };
    },
  };
})();
