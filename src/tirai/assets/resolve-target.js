// Resolve a bsk trace target (accessibility role + name) to a unique CSS selector. Used by `tirai from-trace`.
((role, name, nth) => {
  const norm = (s) => (s || '').replace(/\s+/g, ' ').trim();
  const kinds = {
    textbox: 'input:not([type=button]):not([type=submit]):not([type=checkbox]):not([type=radio]):not([type=hidden]),textarea,[contenteditable=true],[role=textbox]',
    searchbox: 'input[type=search],[role=searchbox]',
    button: 'button,input[type=submit],input[type=button],input[type=reset],[role=button]',
    link: 'a[href],[role=link]',
    combobox: 'select,[role=combobox]',
    listbox: 'select,[role=listbox]',
    checkbox: 'input[type=checkbox],[role=checkbox]',
    radio: 'input[type=radio],[role=radio]',
  };
  const label = (e) => {
    if (e.getAttribute('aria-label')) return e.getAttribute('aria-label');
    const by = e.getAttribute('aria-labelledby');
    if (by) return by.split(/\s+/).map((id) => document.getElementById(id)?.innerText || '').join(' ');
    if (e.id) { const l = document.querySelector(`label[for="${CSS.escape(e.id)}"]`); if (l) return l.innerText; }
    const wrap = e.closest('label'); if (wrap) return wrap.innerText;
    return e.getAttribute('placeholder') || e.innerText || e.value || e.getAttribute('title') || e.getAttribute('alt') || '';
  };
  const want = norm(name);
  const found = [...document.querySelectorAll(kinds[role] || '*')].filter((e) => norm(label(e)) === want);
  const e = found[nth] || found[0];
  if (!e) return null;
  const unique = (sel) => { try { return document.querySelectorAll(sel).length === 1 && document.querySelector(sel) === e; } catch (_) { return false; } };
  const tag = e.tagName.toLowerCase();
  const tries = [];
  if (e.id) tries.push(`#${CSS.escape(e.id)}`);
  for (const a of ['data-testid', 'data-test', 'data-qa', 'name', 'aria-label']) {
    if (e.getAttribute(a)) tries.push(`${tag}[${a}="${e.getAttribute(a).replace(/"/g, '\\"')}"]`);
  }
  for (const s of tries) if (unique(s)) return s;
  const parts = [];
  for (let n = e; n && n !== document.body; n = n.parentElement) {
    if (n.id && unique(`#${CSS.escape(n.id)}`)) { parts.unshift(`#${CSS.escape(n.id)}`); break; }
    const same = [...(n.parentElement?.children || [])].filter((c) => c.tagName === n.tagName);
    parts.unshift(same.length > 1 ? `${n.tagName.toLowerCase()}:nth-of-type(${same.indexOf(n) + 1})` : n.tagName.toLowerCase());
    if (unique(parts.join(' > '))) break;
  }
  return parts.join(' > ');
})
