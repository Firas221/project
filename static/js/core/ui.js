// Shared UI toolkit: escaping, formatting, toasts, modals, form fields, badges, tables.
export const $ = (sel, el = document) => el.querySelector(sel);
export const $$ = (sel, el = document) => Array.from(el.querySelectorAll(sel));
const ESC = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' };
/** Escape ANY untrusted value before putting it into HTML. */
export const esc = (v) => String(v ?? '').replace(/[&<>"']/g, (c) => ESC[c]);

// ------------------------------------------------------------------ formatting
let LOCALE;   // undefined = the browser's own language
try { if (localStorage.getItem('lang') === 'ar') LOCALE = 'ar-EG-u-nu-latn'; } catch (e) { /* storage unavailable */ }
export const settings = { currency: 'EGP' };
export function configure(s) { Object.assign(settings, s || {}); }

export function isoDate(d) {
  const z = (n) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${z(d.getMonth() + 1)}-${z(d.getDate())}`;
}
export const todayISO = () => isoDate(new Date());
export function addDays(iso, n) { const d = new Date(iso + 'T00:00:00'); d.setDate(d.getDate() + n); return isoDate(d); }
export function nightsBetween(a, b) { return Math.round((new Date(b + 'T00:00:00') - new Date(a + 'T00:00:00')) / 86400000); }
export function fmtDate(iso, opts) {
  if (!iso) return '';
  const d = new Date(iso.length <= 10 ? iso + 'T00:00:00' : iso.replace(' ', 'T'));
  if (isNaN(d)) return esc(iso);
  return d.toLocaleDateString(LOCALE, opts || { day: 'numeric', month: 'short', year: 'numeric' });
}
export function fmtDateTime(s) {
  if (!s) return '';
  const d = new Date(s.replace(' ', 'T'));
  return d.toLocaleString(LOCALE, { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' });
}
export function money(v) {
  const n = Number(v || 0);
  return `${n < 0 ? '-' : ''}${Math.abs(n).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })} ${settings.currency || ''}`.trim();
}
/** "≈ 146.00 USD" when the hotel has a second currency and a rate, otherwise ''. */
export function second(v) {
  const rate = Number(settings.exchange_rate || 0);
  if (!settings.second_currency || !(rate > 0)) return '';
  return `≈ ${(Number(v || 0) / rate).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })} ${settings.second_currency}`;
}
export const qty = (v) => Number(v).toLocaleString(undefined, { maximumFractionDigits: 3 });
export const label = (s) => String(s || '').replace(/_/g, ' ').replace(/^./, (c) => c.toUpperCase());

// ------------------------------------------------------------------ badges
const TONE = {
  booked: 'info', checked_in: 'good', checked_out: '', cancelled: 'bad', no_show: 'warn',
  clean: 'good', inspected: 'good', dirty: 'warn', maintenance: 'bad',
  open: 'warn', in_progress: 'info', done: 'good', resolved: 'good', closed: '',
  pending: 'warn', preparing: 'info', ready: 'violet', delivered: 'good', issued: 'good', rejected: 'bad',
  draft: '', ordered: 'info', received: 'good', stored: 'warn', returned: 'good', disposed: '',
  receive: 'good', issue: 'warn', adjust: 'violet', sale: 'info', return: '', consume: 'warn',
  low: '', normal: '', high: 'warn', urgent: 'bad',
};
export const badge = (s, text) => `<span class="badge ${TONE[s] ? 'b-' + TONE[s] : ''}">${esc(text || label(s))}</span>`;
export const vip = (v) => (v ? '<span class="vip" title="VIP guest">VIP</span>' : '');

// ------------------------------------------------------------------ toasts
export function toast(msg, type = '') {
  let box = $('#toasts');
  if (!box) { box = document.createElement('div'); box.id = 'toasts'; box.className = 'toasts'; box.setAttribute('aria-live', 'polite'); document.body.appendChild(box); }
  const el = document.createElement('div');
  el.className = 'toast ' + type;
  el.textContent = msg;
  box.appendChild(el);
  setTimeout(() => el.remove(), type === 'error' ? 6500 : 3500);
}

export async function guarded(fn, okMsg) {
  try {
    const r = await fn();
    if (okMsg) toast(okMsg, 'success');
    return r ?? true;
  } catch (e) {
    toast(e.message, 'error');
    return null;
  }
}

// ------------------------------------------------------------------ forms
export function formValues(form) {
  const out = {};
  for (const el of form.elements) {
    if (!el.name || el.disabled) continue;
    if (el.type === 'checkbox') out[el.name] = el.checked;
    else if (el.type === 'radio') { if (el.checked) out[el.name] = el.value; }
    else out[el.name] = el.value;
  }
  return out;
}
export const options = (list, sel) => list.map((o) => {
  const [v, t] = Array.isArray(o) ? o : [o, o];
  return `<option value="${esc(v)}" ${String(v) === String(sel ?? '') ? 'selected' : ''}>${esc(t)}</option>`;
}).join('');
export function field(lbl, name, value = '', attrs = '', cls = '') {
  return `<label class="field ${cls}"><span>${esc(lbl)}</span><input name="${name}" value="${esc(value)}" ${attrs}></label>`;
}
export function selectField(lbl, name, opts, value, cls = '', attrs = '') {
  return `<label class="field ${cls}"><span>${esc(lbl)}</span><select name="${name}" ${attrs}>${options(opts, value)}</select></label>`;
}
export function textField(lbl, name, value = '', cls = 'full') {
  return `<label class="field ${cls}"><span>${esc(lbl)}</span><textarea name="${name}">${esc(value)}</textarea></label>`;
}
export function check(lbl, name, checked, cls = '') {
  return `<label class="check ${cls}"><input type="checkbox" name="${name}" ${checked ? 'checked' : ''}> ${esc(lbl)}</label>`;
}
export const emptyRow = (cols, text) => `<tr><td colspan="${cols}" class="empty">${esc(text)}</td></tr>`;

export function table(head, rowsHtml, empty = 'Nothing here yet') {
  return `<div class="table-wrap"><table><thead><tr>${head.map((h) => {
    const [t, cls] = Array.isArray(h) ? h : [h, ''];
    return `<th class="${cls}">${esc(t)}</th>`;
  }).join('')}</tr></thead><tbody>${rowsHtml || emptyRow(head.length, empty)}</tbody></table></div>`;
}

// ------------------------------------------------------------------ files
/** Shrinks a picture in the browser (longest edge 1600 px, JPEG) so uploads stay small and fast. Returns base64. */
export async function shrinkImage(file, maxEdge = 1600) {
  const img = await createImageBitmap(file);
  const scale = Math.min(1, maxEdge / Math.max(img.width, img.height));
  const canvas = document.createElement('canvas');
  canvas.width = Math.round(img.width * scale);
  canvas.height = Math.round(img.height * scale);
  canvas.getContext('2d').drawImage(img, 0, 0, canvas.width, canvas.height);
  return canvas.toDataURL('image/jpeg', 0.85).split(',')[1];
}
/** A file's bytes as base64, unchanged (for PDFs). */
export function fileToBase64(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result).split(',')[1]);
    reader.onerror = () => reject(new Error('The file could not be read'));
    reader.readAsDataURL(file);
  });
}

// ------------------------------------------------------------------ paging
export const PAGE_SIZE = 50;
/** Previous / next controls under a list. `p` is what the API returns for ?page=: {page, pages, total}. */
export function pager(p) {
  if (!p || !p.total) return '';
  return `<div class="pager"><button type="button" class="btn sm" data-page="${p.page - 1}" ${p.page <= 1 ? 'disabled' : ''}>‹ Previous</button>
    <span class="small muted">Page ${p.page} of ${p.pages} · ${p.total} in total</span>
    <button type="button" class="btn sm" data-page="${p.page + 1}" ${p.page >= p.pages ? 'disabled' : ''}>Next ›</button></div>`;
}
export function bindPager(root, go) {
  $$('.pager [data-page]', root).forEach((b) => b.addEventListener('click', () => go(+b.dataset.page)));
}

export const MEAL_PLANS = [['room_only', 'Room only'], ['breakfast', 'Breakfast included'], ['half_board', 'Half board'], ['full_board', 'Full board']];
export const mealLabel = (m) => (MEAL_PLANS.find(([k]) => k === m) || ['', ''])[1];

export function tile(lbl, value, sub = '') {
  return `<div class="card tile"><div class="tile-label">${esc(lbl)}</div><div class="tile-value">${esc(value)}</div><div class="tile-sub">${esc(sub)}</div></div>`;
}

export function bindRowLinks(root) {
  $$('tr[data-href]', root).forEach((tr) => tr.addEventListener('click', (e) => {
    if (e.target.closest('a,button,input,select,textarea')) return;
    location.hash = tr.dataset.href;
  }));
}

export function on(root, selector, event, handler) {
  $$(selector, root).forEach((el) => el.addEventListener(event, (e) => handler(e, el)));
}

// ------------------------------------------------------------------ modal
/**
 * Opens a modal dialog. onSubmit(values, root) may throw to show an inline error.
 * Resolves to onSubmit's return value, or null if dismissed.
 */
export function modal({ title, body, submit = 'Save', danger = false, wide = false, onSubmit, onOpen, cancel = 'Cancel' }) {
  return new Promise((resolve) => {
    const back = document.createElement('div');
    back.className = 'modal-back';
    back.innerHTML = `
      <form class="modal ${wide ? 'wide' : ''}" novalidate role="dialog" aria-modal="true" aria-label="${esc(title)}">
        <div class="modal-head"><h2>${esc(title)}</h2><button type="button" class="btn ghost sm" data-close aria-label="Close">✕</button></div>
        <div class="modal-body"><div class="form-error hidden" role="alert"></div>${body}</div>
        <div class="modal-foot"><button type="button" class="btn" data-close>${esc(cancel)}</button>
          ${onSubmit ? `<button type="submit" class="btn ${danger ? 'danger solid' : 'primary'}">${esc(submit)}</button>` : ''}</div>
      </form>`;
    document.body.appendChild(back);
    const form = $('form', back);
    const err = $('.form-error', back);
    const onKey = (e) => { if (e.key === 'Escape') close(null); };
    function close(v) { back.remove(); document.removeEventListener('keydown', onKey); resolve(v); }
    document.addEventListener('keydown', onKey);
    $$('[data-close]', back).forEach((b) => b.addEventListener('click', () => close(null)));
    back.addEventListener('mousedown', (e) => { if (e.target === back) close(null); });
    form.addEventListener('submit', async (e) => {
      e.preventDefault();
      if (!onSubmit) return close(true);
      const btn = $('button[type=submit]', form);
      btn.disabled = true;
      err.classList.add('hidden');
      try {
        const r = await onSubmit(formValues(form), back);
        close(r === undefined ? true : r);
      } catch (ex) {
        err.textContent = ex.message;
        err.classList.remove('hidden');
        btn.disabled = false;
        if (ex.field) { const f = form.elements[ex.field]; if (f && f.focus) f.focus(); }
      }
    });
    if (onOpen) onOpen(back);
    const first = $('input:not([type=hidden]):not([type=radio]):not([type=checkbox]), select, textarea', form);
    if (first) first.focus({ preventScroll: true });   // at once: a delayed focus could steal text being typed into another field
  });
}

export function confirmBox(title, message, submit = 'Confirm', danger = true) {
  return modal({ title, body: `<p style="margin:0">${message}</p>`, submit, danger, onSubmit: async () => true });
}

export function showSecret(title, intro, secret) {
  return modal({ title, cancel: 'Done', body: `<p>${intro}</p><div class="secret">${esc(secret)}</div>
    <p class="small muted">Copy it now — it will not be shown again.</p>` });
}

// ------------------------------------------------------------------ icons
const ICONS = {
  dashboard: '<path d="M3 13h8V3H3zm0 8h8v-6H3zm10 0h8V11h-8zm0-18v6h8V3z"/>',
  calendar: '<path d="M7 2v2H5a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2V6a2 2 0 0 0-2-2h-2V2h-2v2H9V2zM5 9h14v11H5z"/>',
  reservations: '<path d="M4 4h16v4H4zm0 6h16v10H4zm3 3v2h6v-2z"/>',
  guests: '<path d="M12 12a4 4 0 1 0-4-4 4 4 0 0 0 4 4zm0 2c-3.3 0-8 1.7-8 5v1h16v-1c0-3.3-4.7-5-8-5z"/>',
  rooms: '<path d="M3 11V5h2v5h14a2 2 0 0 1 2 2v7h-2v-2H5v2H3zm4-4a2 2 0 1 1 2 2 2 2 0 0 1-2-2z"/>',
  housekeeping: '<path d="M19.4 3.6l1 1-6.8 6.8 1.4 1.4-1.4 1.4-1.4-1.4L5 20H3v-2l7.2-7.2-1.4-1.4 1.4-1.4 1.4 1.4z"/>',
  inventory: '<path d="M20 7l-8-4-8 4v10l8 4 8-4zM12 5.2L17.6 8 12 10.8 6.4 8zM6 9.6l5 2.5v6.3l-5-2.5zm7 8.8v-6.3l5-2.5v6.3z"/>',
  reports: '<path d="M5 3v16h16v2H3V3zm4 10h2v4H9zm4-6h2v10h-2zm4 3h2v7h-2z"/>',
  settings: '<path d="M19.4 13a7.5 7.5 0 0 0 0-2l2.1-1.6-2-3.5-2.5 1a7.3 7.3 0 0 0-1.7-1L15 3h-4l-.4 2.6a7.3 7.3 0 0 0-1.7 1l-2.5-1-2 3.5L6.6 11a7.5 7.5 0 0 0 0 2l-2.1 1.6 2 3.5 2.5-1a7.3 7.3 0 0 0 1.7 1L11 21h4l.4-2.6a7.3 7.3 0 0 0 1.7-1l2.5 1 2-3.5zM13 15.5A3.5 3.5 0 1 1 16.5 12 3.5 3.5 0 0 1 13 15.5z"/>',
  kitchen: '<path d="M8 2v9a3 3 0 0 1-2 2.8V22H4v-8.2A3 3 0 0 1 2 11V2h1.5v6h1V2H6v6h1V2zm9 0c2.2 0 4 2.5 4 6v6h-3v8h-2V2z"/>',
  wrench: '<path d="M22 19.6l-9.1-9.1a6 6 0 0 0-7.4-7.9l3.9 3.9-2.8 2.8-3.9-3.9a6 6 0 0 0 7.9 7.4l9.1 9.1z"/>',
  bell: '<path d="M12 22a2 2 0 0 0 2-2h-4a2 2 0 0 0 2 2zm6-6V11a6 6 0 0 0-5-5.9V4h-2v1.1A6 6 0 0 0 6 11v5l-2 2v1h16v-1z"/>',
  box: '<path d="M3 3h18v4H3zm1 5h16v13H4zm5 3v2h6v-2z"/>',
  cash: '<path d="M2 6h20v12H2zm10 9a3 3 0 1 0-3-3 3 3 0 0 0 3 3zM5 9v6h1V9zm13 0v6h1V9z"/>',
  building: '<path d="M4 22V2h12v6h4v14h-7v-4h-2v4zm3-17v2h2V5zm4 0v2h2V5zM7 9v2h2V9zm4 0v2h2V9zm-4 4v2h2v-2zm4 0v2h2v-2zm6-2v2h2v-2zm0 4v2h2v-2z"/>',
  star: '<path d="M12 2l3 7h7l-5.6 4.3 2.1 7.2L12 16.2l-6.5 4.3 2.1-7.2L2 9h7z"/>',
  search: '<path d="M10 2a8 8 0 0 1 6.3 12.9l5.4 5.4-1.4 1.4-5.4-5.4A8 8 0 1 1 10 2zm0 2a6 6 0 1 0 0 12 6 6 0 0 0 0-12z"/>',
  shield: '<path d="M12 2l8 3v6c0 5-3.4 9.7-8 11-4.6-1.3-8-6-8-11V5z"/>',
  moon: '<path d="M21 14.5A9 9 0 0 1 9.5 3a9 9 0 1 0 11.5 11.5z"/>',
  list: '<path d="M4 5h2v2H4zm4 0h12v2H8zm-4 6h2v2H4zm4 0h12v2H8zm-4 6h2v2H4zm4 0h12v2H8z"/>',
};
export const icon = (n) => `<svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">${ICONS[n] || ICONS.list}</svg>`;
