/* Hotel Manager — single-page GUI (vanilla JS, no build step). */
'use strict';

// ======================================================================= utilities
const $ = (sel, el = document) => el.querySelector(sel);
const $$ = (sel, el = document) => Array.from(el.querySelectorAll(sel));
const ESC = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' };
const esc = (v) => String(v ?? '').replace(/[&<>"']/g, (c) => ESC[c]);
const state = { user: null, settings: {}, roomTypes: [] };
const isAdmin = () => state.user && state.user.role === 'admin';

function isoDate(d) {
  const z = (n) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${z(d.getMonth() + 1)}-${z(d.getDate())}`;
}
function todayISO() { return isoDate(new Date()); }
function addDays(iso, n) { const d = new Date(iso + 'T00:00:00'); d.setDate(d.getDate() + n); return isoDate(d); }
function fmtDate(iso, opts) {
  if (!iso) return '';
  const d = new Date(iso.length <= 10 ? iso + 'T00:00:00' : iso.replace(' ', 'T'));
  return d.toLocaleDateString(undefined, opts || { day: 'numeric', month: 'short', year: 'numeric' });
}
function fmtDateTime(s) {
  if (!s) return '';
  const d = new Date(s.replace(' ', 'T'));
  return d.toLocaleString(undefined, { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' });
}
function money(v) {
  const n = Number(v || 0);
  const s = Math.abs(n).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  return (n < 0 ? '-' : '') + (state.settings.currency || '$') + s;
}
function qty(v) { return Number(v).toLocaleString(undefined, { maximumFractionDigits: 3 }); }
function label(s) { return String(s || '').replace(/_/g, ' ').replace(/^./, (c) => c.toUpperCase()); }

const RES_BADGE = { booked: 'b-info', checked_in: 'b-good', checked_out: '', cancelled: 'b-bad', no_show: 'b-warn' };
const ROOM_BADGE = { clean: 'b-good', dirty: 'b-warn', maintenance: 'b-bad' };
const MOVE_BADGE = { receive: 'b-good', issue: 'b-warn', adjust: 'b-violet', sale: 'b-info', return: '' };
const resBadge = (s) => `<span class="badge ${RES_BADGE[s] || ''}">${esc(label(s))}</span>`;
const roomBadge = (s) => `<span class="badge ${ROOM_BADGE[s] || ''}">${esc(label(s))}</span>`;
const vip = (g) => (g ? '<span class="vip" title="VIP guest">VIP</span>' : '');
const SOURCES = ['walk-in', 'direct', 'phone', 'email', 'booking.com', 'expedia', 'airbnb', 'corporate', 'other'];
const METHODS = { card: 'Card', cash: 'Cash', bank_transfer: 'Bank transfer', other: 'Other' };
const options = (list, sel) => list.map((o) => {
  const [v, t] = Array.isArray(o) ? o : [o, o];
  return `<option value="${esc(v)}" ${String(v) === String(sel ?? '') ? 'selected' : ''}>${esc(t)}</option>`;
}).join('');

// ======================================================================= API
async function api(method, path, body) {
  const opts = { method, headers: {}, credentials: 'same-origin' };
  if (body !== undefined) {
    opts.headers['Content-Type'] = 'application/json';
    opts.body = JSON.stringify(body);
  }
  let res;
  try { res = await fetch('/api' + path, opts); } catch (e) { throw new Error('Cannot reach the server'); }
  let data = null;
  try { data = await res.json(); } catch (e) { /* empty */ }
  if (res.status === 401 && path !== '/login') {
    state.user = null;
    renderLogin('Your session has expired. Please sign in again.');
    throw new Error('Please sign in');
  }
  if (!res.ok) throw new Error((data && data.error) || `Request failed (${res.status})`);
  return data;
}
const GET = (p) => api('GET', p);
const POST = (p, b) => api('POST', p, b || {});
const PUT = (p, b) => api('PUT', p, b);
const DEL = (p) => api('DELETE', p);
const qs = (o) => Object.entries(o).filter(([, v]) => v !== '' && v != null && v !== false)
  .map(([k, v]) => `${encodeURIComponent(k)}=${encodeURIComponent(v)}`).join('&');

// ======================================================================= UI primitives
function toast(msg, type = '') {
  const el = document.createElement('div');
  el.className = 'toast ' + type;
  el.textContent = msg;
  $('#toasts').appendChild(el);
  setTimeout(() => el.remove(), type === 'error' ? 6000 : 3200);
}

function formValues(form) {
  const out = {};
  for (const el of form.elements) {
    if (!el.name || el.disabled) continue;
    if (el.type === 'checkbox') out[el.name] = el.checked;
    else if (el.type === 'radio') { if (el.checked) out[el.name] = el.value; }
    else out[el.name] = el.value;
  }
  return out;
}

/**
 * Opens a modal. onSubmit(values, modalEl) may throw to show an inline error.
 * Returns a promise resolving to onSubmit's result (or null if dismissed).
 */
function modal({ title, body, submit = 'Save', danger = false, wide = false, onSubmit, onOpen, cancel = 'Cancel' }) {
  return new Promise((resolve) => {
    const back = document.createElement('div');
    back.className = 'modal-back';
    back.innerHTML = `
      <form class="modal ${wide ? 'wide' : ''}" novalidate>
        <div class="modal-head"><h2>${esc(title)}</h2>
          <button type="button" class="btn ghost sm" data-close aria-label="Close">✕</button></div>
        <div class="modal-body"><div class="form-error hidden"></div>${body}</div>
        <div class="modal-foot">
          <button type="button" class="btn" data-close>${esc(cancel)}</button>
          ${onSubmit ? `<button type="submit" class="btn ${danger ? 'danger solid' : 'primary'}">${esc(submit)}</button>` : ''}
        </div>
      </form>`;
    document.body.appendChild(back);
    const form = $('form', back);
    const errBox = $('.form-error', back);
    const close = (val) => { back.remove(); document.removeEventListener('keydown', onKey); resolve(val); };
    const onKey = (e) => { if (e.key === 'Escape') close(null); };
    document.addEventListener('keydown', onKey);
    $$('[data-close]', back).forEach((b) => b.addEventListener('click', () => close(null)));
    back.addEventListener('mousedown', (e) => { if (e.target === back) close(null); });
    form.addEventListener('submit', async (e) => {
      e.preventDefault();
      if (!onSubmit) return close(true);
      const btn = $('button[type=submit]', form);
      btn.disabled = true;
      errBox.classList.add('hidden');
      try {
        const result = await onSubmit(formValues(form), back);
        close(result === undefined ? true : result);
      } catch (err) {
        errBox.textContent = err.message;
        errBox.classList.remove('hidden');
        btn.disabled = false;
        back.scrollTop = 0;
      }
    });
    if (onOpen) onOpen(back);
    const first = $('input:not([type=hidden]):not([type=radio]), select, textarea', form);
    if (first) setTimeout(() => first.focus(), 30);
  });
}

function confirmBox(title, message, submit = 'Confirm', danger = true) {
  return modal({ title, body: `<p style="margin:0">${message}</p>`, submit, danger, onSubmit: async () => true });
}

function field(lbl, name, value = '', attrs = '', cls = '') {
  return `<label class="field ${cls}"><span>${esc(lbl)}</span><input name="${name}" value="${esc(value)}" ${attrs}></label>`;
}
function selectField(lbl, name, opts, value, cls = '', attrs = '') {
  return `<label class="field ${cls}"><span>${esc(lbl)}</span><select name="${name}" ${attrs}>${options(opts, value)}</select></label>`;
}
function textField(lbl, name, value = '', cls = 'full') {
  return `<label class="field ${cls}"><span>${esc(lbl)}</span><textarea name="${name}">${esc(value)}</textarea></label>`;
}
function emptyRow(cols, text) { return `<tr><td colspan="${cols}" class="empty">${esc(text)}</td></tr>`; }

async function guarded(fn, okMsg) {
  try {
    const r = await fn();
    if (okMsg) toast(okMsg, 'success');
    return r;
  } catch (e) {
    toast(e.message, 'error');
    return null;
  }
}

// ======================================================================= icons
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
};
const icon = (n) => `<svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">${ICONS[n]}</svg>`;

// ======================================================================= shell & routing
const NAV = [
  ['dashboard', 'Dashboard', ''],
  ['calendar', 'Room Calendar', 'calendar'],
  ['reservations', 'Reservations', 'reservations'],
  ['guests', 'Guests', 'guests'],
  ['sep'],
  ['rooms', 'Rooms', 'rooms'],
  ['housekeeping', 'Housekeeping', 'housekeeping'],
  ['inventory', 'Inventory', 'inventory'],
  ['sep'],
  ['reports', 'Reports', 'reports'],
  ['settings', 'Settings', 'settings'],
];

function renderShell() {
  const s = state.settings;
  $('#root').innerHTML = `
    <div class="app">
      <aside class="sidebar" id="sidebar">
        <div class="brand"><div class="brand-logo">${esc((s.hotel_name || 'H')[0])}</div>
          <div><div class="brand-name">${esc(s.hotel_name || 'Hotel')}</div><div class="brand-sub">Property management</div></div></div>
        <nav class="nav">
          ${NAV.map(([k, t, h]) => k === 'sep' ? '<div class="nav-sep"></div>'
            : `<a href="#/${h}" data-nav="${k}">${icon(k)}<span>${t}</span></a>`).join('')}
        </nav>
        <div class="sidebar-foot">
          <div class="who">${esc(state.user.full_name)}</div>
          <div>${esc(label(state.user.role))} · <a href="#" id="logout" style="color:inherit;text-decoration:underline">Sign out</a></div>
        </div>
      </aside>
      <div class="main">
        <header class="topbar">
          <button class="btn sm menu-btn" id="menu-btn" aria-label="Menu">☰</button>
          <div class="grow"><b id="top-title"></b></div>
          <span class="muted small" id="top-date"></span>
          <button class="btn primary sm" id="quick-book">+ New reservation</button>
        </header>
        <main class="content" id="view"></main>
      </div>
    </div>`;
  $('#top-date').textContent = fmtDate(todayISO(), { weekday: 'long', day: 'numeric', month: 'long', year: 'numeric' });
  $('#logout').addEventListener('click', async (e) => {
    e.preventDefault();
    await api('POST', '/logout', {}).catch(() => {});
    state.user = null;
    location.hash = '';
    renderLogin();
  });
  $('#menu-btn').addEventListener('click', () => $('#sidebar').classList.toggle('open'));
  $('#quick-book').addEventListener('click', () => newReservation());
}

const ROUTES = [
  [/^$/, 'dashboard', viewDashboard],
  [/^calendar$/, 'calendar', viewCalendar],
  [/^reservations$/, 'reservations', viewReservations],
  [/^reservations\/(\d+)$/, 'reservations', viewReservation],
  [/^invoice\/(\d+)$/, 'reservations', viewInvoice],
  [/^guests$/, 'guests', viewGuests],
  [/^guests\/(\d+)$/, 'guests', viewGuest],
  [/^rooms$/, 'rooms', viewRooms],
  [/^housekeeping$/, 'housekeeping', viewHousekeeping],
  [/^inventory$/, 'inventory', viewInventory],
  [/^inventory\/(\d+)$/, 'inventory', viewItem],
  [/^reports$/, 'reports', viewReports],
  [/^settings$/, 'settings', viewSettings],
];

let routeToken = 0;
async function router() {
  if (!state.user) return;
  const hash = decodeURIComponent(location.hash.replace(/^#\/?/, ''));
  const [path, query] = hash.split('?');
  const params = Object.fromEntries(new URLSearchParams(query || ''));
  const match = ROUTES.find(([rx]) => rx.test(path));
  const view = $('#view');
  if (!view) return;
  $('#sidebar').classList.remove('open');
  if (!match) { view.innerHTML = '<div class="empty">Page not found</div>'; return; }
  const [rx, nav, fn] = match;
  $$('.nav a').forEach((a) => a.classList.toggle('active', a.dataset.nav === nav));
  const navItem = NAV.find((n) => n[0] === nav);
  $('#top-title').textContent = navItem ? navItem[1] : '';
  const token = ++routeToken;
  view.innerHTML = '<div class="empty">Loading…</div>';
  try {
    await fn(view, ...(path.match(rx).slice(1)), params, () => token === routeToken);
  } catch (e) {
    if (token === routeToken && state.user) view.innerHTML = `<div class="card card-body"><div class="form-error">${esc(e.message)}</div></div>`;
  }
  window.scrollTo(0, 0);
}
function refresh() { router(); }
window.addEventListener('hashchange', router);

// ======================================================================= login
function renderLogin(message) {
  $$('.modal-back').forEach((m) => m.remove());
  $('#root').innerHTML = `
    <div class="login-wrap">
      <form class="card login-card" id="login-form">
        <div class="brand"><div class="brand-logo">H</div>
          <div><div class="brand-name">Hotel Manager</div><div class="brand-sub">Reservations · Front desk · Inventory</div></div></div>
        ${message ? `<div class="notice warn" style="margin-bottom:12px">${esc(message)}</div>` : ''}
        <div class="form-error hidden"></div>
        <div class="stack">
          ${field('Username', 'username', '', 'autocomplete="username" required')}
          ${field('Password', 'password', '', 'type="password" autocomplete="current-password" required')}
          <button class="btn primary" style="width:100%" type="submit">Sign in</button>
        </div>
      </form>
    </div>`;
  const form = $('#login-form');
  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    const err = $('.form-error', form);
    err.classList.add('hidden');
    try {
      await api('POST', '/login', formValues(form));
      await boot();
    } catch (ex) {
      err.textContent = ex.message;
      err.classList.remove('hidden');
    }
  });
  $('input[name=username]', form).focus();
}

async function boot() {
  try {
    const me = await GET('/me');
    state.user = me;
    state.settings = me.settings;
    document.title = (state.settings.hotel_name || 'Hotel') + ' · Manager';
    renderShell();
    router();
  } catch (e) {
    renderLogin();
  }
}

// ======================================================================= dashboard
async function viewDashboard(view, params, alive) {
  const d = await GET('/dashboard');
  if (!alive()) return;
  const r = d.rooms;
  view.innerHTML = `
    <div class="page-head"><div class="grow"><h1>Good ${greeting()}, ${esc(state.user.full_name.split(' ')[0])}</h1>
      <div class="sub">Here is what's happening at ${esc(state.settings.hotel_name)} today.</div></div>
      <a class="btn" href="#/calendar">Open calendar</a></div>
    <div class="tiles">
      ${tile('Occupancy', r.occupancy + '%', `${r.occupied} of ${r.total - r.maintenance} sellable rooms`)}
      ${tile('In-house guests', d.in_house_guests, `${r.occupied} rooms occupied`)}
      ${tile('Arrivals today', d.arrivals.length, 'awaiting check-in')}
      ${tile('Departures', d.departures.length, 'due to check out')}
      ${tile('Payments today', money(d.revenue_today), 'collected')}
      ${tile('Payments this month', money(d.revenue_month), 'collected')}
    </div>
    <div class="card card-body" style="margin-bottom:16px">
      <div class="statusbar">
        ${seg('Occupied', r.occupied, 'b-info')}${seg('Vacant & clean', r.vacant_clean, 'b-good')}
        ${seg('Dirty', r.dirty, 'b-warn')}${seg('Maintenance', r.maintenance, 'b-bad')}
      </div>
    </div>
    <div class="grid g2">
      <div class="card"><div class="card-head"><h2 class="grow">Arrivals</h2><span class="muted small">${d.arrivals.length}</span></div>
        <div class="table-wrap"><table><thead><tr><th>Guest</th><th>Room</th><th>Nights</th><th></th></tr></thead><tbody>
        ${d.arrivals.map((a) => `<tr><td><a href="#/reservations/${a.id}">${esc(a.guest_name)}</a>${vip(a.guest_vip)}
            <div class="small muted">${esc(a.code)}${a.check_in < d.date ? ' · <span class="balance-due">late arrival</span>' : ''}</div></td>
            <td>${esc(a.room_number)}<div class="small muted">${esc(a.room_type)}</div></td>
            <td>${nightsOf(a)}</td>
            <td class="actions"><button class="btn sm good" data-checkin="${a.id}">Check in</button></td></tr>`).join('')
          || emptyRow(4, 'No arrivals pending today')}
        </tbody></table></div></div>
      <div class="card"><div class="card-head"><h2 class="grow">Departures</h2><span class="muted small">${d.departures.length}</span></div>
        <div class="table-wrap"><table><thead><tr><th>Guest</th><th>Room</th><th class="num">Balance</th><th></th></tr></thead><tbody>
        ${d.departures.map((a) => `<tr><td><a href="#/reservations/${a.id}">${esc(a.guest_name)}</a>${vip(a.guest_vip)}
            <div class="small muted">${esc(a.code)}${a.check_out < d.date ? ' · <span class="balance-due">overdue</span>' : ''}</div></td>
            <td>${esc(a.room_number)}</td>
            <td class="num ${a.balance > 0 ? 'balance-due' : ''}">${money(a.balance)}</td>
            <td class="actions"><button class="btn sm" data-checkout="${a.id}">Check out</button></td></tr>`).join('')
          || emptyRow(4, 'No departures due')}
        </tbody></table></div></div>
      <div class="card"><div class="card-head"><h2 class="grow">Low stock</h2><a class="small" href="#/inventory?low=1">View inventory</a></div>
        <div class="table-wrap"><table><thead><tr><th>Item</th><th class="num">On hand</th><th class="num">Reorder at</th><th></th></tr></thead><tbody>
        ${d.low_stock.map((i) => `<tr><td><a href="#/inventory/${i.id}">${esc(i.name)}</a><div class="small muted">${esc(i.sku)} · ${esc(i.supplier_name || 'No supplier')}</div></td>
            <td class="num balance-due">${qty(i.quantity)} ${esc(i.unit)}</td><td class="num">${qty(i.reorder_level)}</td>
            <td class="actions"><button class="btn sm" data-receive="${i.id}">Receive</button></td></tr>`).join('')
          || emptyRow(4, 'All items are above their reorder level')}
        </tbody></table></div></div>
      <div class="card"><div class="card-head"><h2 class="grow">Upcoming arrivals</h2><a class="small" href="#/reservations">All reservations</a></div>
        <div class="table-wrap"><table><thead><tr><th>Date</th><th>Guest</th><th>Room</th><th>Nights</th></tr></thead><tbody>
        ${d.upcoming.map((a) => `<tr class="clickable" data-href="#/reservations/${a.id}"><td class="nowrap">${fmtDate(a.check_in)}</td>
            <td>${esc(a.guest_name)}${vip(a.guest_vip)}</td><td>${esc(a.room_number)}</td><td>${nightsOf(a)}</td></tr>`).join('')
          || emptyRow(4, 'No upcoming arrivals')}
        </tbody></table></div></div>
    </div>
    ${isAdmin() ? `<div class="card" style="margin-top:16px"><div class="card-head"><h2 class="grow">Recent activity</h2></div>
      <div class="table-wrap"><table><tbody>${d.recent_activity.map(activityRow).join('') || emptyRow(3, 'No activity yet')}</tbody></table></div></div>` : ''}`;

  bindRowLinks(view);
  $$('[data-checkin]', view).forEach((b) => b.addEventListener('click', () => doCheckIn(+b.dataset.checkin, refresh)));
  $$('[data-checkout]', view).forEach((b) => b.addEventListener('click', async () => {
    const res = await GET('/reservations/' + b.dataset.checkout);
    doCheckOut(res, refresh);
  }));
  $$('[data-receive]', view).forEach((b) => b.addEventListener('click', async () => {
    const item = await GET('/items/' + b.dataset.receive);
    stockMove(item, 'receive', refresh);
  }));
}
function greeting() { const h = new Date().getHours(); return h < 12 ? 'morning' : h < 18 ? 'afternoon' : 'evening'; }
function tile(lbl, value, sub) {
  return `<div class="card tile"><div class="tile-label">${esc(lbl)}</div><div class="tile-value">${esc(value)}</div><div class="tile-sub">${esc(sub)}</div></div>`;
}
function seg(lbl, n, cls) { return `<div class="seg"><b>${n}</b><span class="badge ${cls}">${esc(lbl)}</span></div>`; }
function nightsOf(r) { return Math.round((new Date(r.check_out) - new Date(r.check_in)) / 86400000); }
function activityRow(a) {
  return `<tr><td class="nowrap small muted">${fmtDateTime(a.created_at)}</td><td class="nowrap">${esc(a.user_name || 'System')}</td>
    <td><b>${esc(label(a.action))}</b> <span class="muted">${esc(a.details)}</span></td></tr>`;
}
function bindRowLinks(root) {
  $$('tr[data-href]', root).forEach((tr) => tr.addEventListener('click', (e) => {
    if (e.target.closest('a,button,input,select')) return;
    location.hash = tr.dataset.href;
  }));
}

// ======================================================================= calendar
async function viewCalendar(view, params, alive) {
  const start = params.start || addDays(todayISO(), -2);
  const days = Math.min(+(params.days || (window.innerWidth < 820 ? 10 : 21)), 62);
  const data = await GET('/calendar?' + qs({ start, days }));
  if (!alive()) return;
  const dates = Array.from({ length: days }, (_, i) => addDays(start, i));
  const end = addDays(start, days);
  const t = todayISO();
  const cols = `150px repeat(${days}, minmax(42px, 1fr))`;
  const byRoom = {};
  data.reservations.forEach((r) => (byRoom[r.room_id] = byRoom[r.room_id] || []).push(r));
  const dayCls = (d) => [d === t ? 'today' : '', [0, 6].includes(new Date(d + 'T00:00:00').getDay()) ? 'weekend' : ''].join(' ');

  view.innerHTML = `
    <div class="page-head"><div class="grow"><h1>Room calendar</h1>
      <div class="sub">Click an empty day to book that room; click a booking to open it.</div></div>
      <div class="btn-row">
        <button class="btn" data-shift="-7">‹ Week</button>
        <button class="btn" data-shift="today">Today</button>
        <button class="btn" data-shift="7">Week ›</button>
        <input type="date" id="cal-start" value="${start}" style="width:auto">
        <select id="cal-days" style="width:auto">${options([[7, '7 days'], [14, '14 days'], [21, '21 days'], [31, '31 days']], days)}</select>
      </div></div>
    <div class="legend" style="margin-bottom:10px">
      <span class="badge b-info">Booked</span><span class="badge b-good">In house</span>
      <span class="badge">Checked out</span><span class="badge b-bad">Room under maintenance</span></div>
    <div class="card cal"><div class="cal-inner">
      <div class="cal-row head" style="grid-template-columns:${cols}">
        <div class="cal-room">Room</div>
        ${dates.map((d, i) => `<div class="cal-cell ${dayCls(d)}" style="grid-column:${i + 2}">
          ${fmtDate(d, { weekday: 'short' })}<br>${fmtDate(d, { day: 'numeric', month: 'short' })}</div>`).join('')}
      </div>
      ${data.rooms.map((room) => `
        <div class="cal-row ${room.status === 'maintenance' ? 'maint' : ''}" style="grid-template-columns:${cols}">
          <div class="cal-room"><b>${esc(room.number)}</b>${room.status === 'maintenance' ? ' 🔧' : ''}<small>${esc(room.type_name)}</small></div>
          ${dates.map((d, i) => `<div class="cal-cell ${dayCls(d)}" style="grid-column:${i + 2}" data-room="${room.id}" data-date="${d}"
            title="Book room ${esc(room.number)} from ${d}"></div>`).join('')}
          ${(byRoom[room.id] || []).map((r) => {
            const s = r.check_in < start ? start : r.check_in;
            const e = r.check_out > end ? end : r.check_out;
            const c0 = dates.indexOf(s) + 2;
            const span = Math.max(1, Math.round((new Date(e) - new Date(s)) / 86400000));
            return `<a class="cal-bar ${r.status}" href="#/reservations/${r.id}" style="grid-column:${c0} / span ${span}"
              title="${esc(r.guest_name)} · ${esc(r.code)} · ${fmtDate(r.check_in)} → ${fmtDate(r.check_out)} · ${esc(label(r.status))}">
              ${esc(r.guest_name)}</a>`;
          }).join('')}
        </div>`).join('')}
    </div></div>`;

  const go = (s, n = days) => { location.hash = `#/calendar?${qs({ start: s, days: n })}`; };
  $$('[data-shift]', view).forEach((b) => b.addEventListener('click', () =>
    go(b.dataset.shift === 'today' ? addDays(todayISO(), -2) : addDays(start, +b.dataset.shift))));
  $('#cal-start', view).addEventListener('change', (e) => e.target.value && go(e.target.value));
  $('#cal-days', view).addEventListener('change', (e) => go(start, e.target.value));
  $$('.cal-cell[data-room]', view).forEach((c) => c.addEventListener('click', () => {
    const d = c.dataset.date < t ? t : c.dataset.date;
    newReservation({ room_id: +c.dataset.room, check_in: d, check_out: addDays(d, 1) });
  }));
}

// ======================================================================= reservations list
async function viewReservations(view, params, alive) {
  view.innerHTML = `
    <div class="page-head"><div class="grow"><h1>Reservations</h1><div class="sub">Search, filter and manage bookings.</div></div>
      <a class="btn" id="res-export" href="#">Export CSV</a>
      <button class="btn primary" id="res-new">+ New reservation</button></div>
    <div class="toolbar">
      <input type="search" id="f-q" placeholder="Search code, guest, room, email…" value="${esc(params.q || '')}">
      <select id="f-status">${options([['active', 'Active (booked + in house)'], ['', 'All statuses'], ['booked', 'Booked'],
        ['checked_in', 'In house'], ['checked_out', 'Checked out'], ['cancelled', 'Cancelled'], ['no_show', 'No-show']], params.status ?? 'active')}</select>
      <label class="check small">From <input type="date" id="f-from" value="${esc(params.from || '')}"></label>
      <label class="check small">To <input type="date" id="f-to" value="${esc(params.to || '')}"></label>
      <button class="btn sm ghost" id="f-clear">Clear</button>
    </div>
    <div class="card"><div class="table-wrap"><table>
      <thead><tr><th>Code</th><th>Guest</th><th>Room</th><th>Check-in</th><th>Check-out</th><th>Nights</th><th>Status</th>
        <th class="num">Total</th><th class="num">Balance</th></tr></thead>
      <tbody id="res-body"><tr><td colspan="9" class="empty">Loading…</td></tr></tbody></table></div></div>`;

  const load = async () => {
    const filters = { q: $('#f-q').value.trim(), status: $('#f-status').value, from: $('#f-from').value, to: $('#f-to').value };
    $('#res-export').href = '/api/export/reservations.csv?' + qs(filters);
    const list = await GET('/reservations?' + qs(filters));
    if (!alive()) return;
    $('#res-body').innerHTML = list.map((r) => `
      <tr class="clickable" data-href="#/reservations/${r.id}">
        <td><b>${esc(r.code)}</b></td><td>${esc(r.guest_name)}${vip(r.guest_vip)}<div class="small muted">${esc(r.source)}</div></td>
        <td>${esc(r.room_number)}<div class="small muted">${esc(r.room_type)}</div></td>
        <td class="nowrap">${fmtDate(r.check_in)}</td><td class="nowrap">${fmtDate(r.check_out)}</td><td>${r.nights}</td>
        <td>${resBadge(r.status)}</td><td class="num">${money(r.total)}</td>
        <td class="num ${r.balance > 0.004 ? 'balance-due' : ''}">${money(r.balance)}</td></tr>`).join('')
      || emptyRow(9, 'No reservations match these filters');
    bindRowLinks(view);
  };
  let timer;
  $('#f-q').addEventListener('input', () => { clearTimeout(timer); timer = setTimeout(load, 250); });
  ['#f-status', '#f-from', '#f-to'].forEach((s) => $(s).addEventListener('change', load));
  $('#f-clear').addEventListener('click', () => { $('#f-q').value = ''; $('#f-from').value = ''; $('#f-to').value = ''; $('#f-status').value = 'active'; load(); });
  $('#res-new').addEventListener('click', () => newReservation());
  await load();
}

// ======================================================================= new reservation
async function newReservation(prefill = {}) {
  const types = await guarded(() => GET('/room-types'));
  if (!types) return;
  const ci = prefill.check_in || todayISO();
  const co = prefill.check_out || addDays(ci, 1);
  let selectedRoom = null;
  let rooms = [];

  const body = `
    <div class="stack">
      <div class="form-section">Guest</div>
      <div class="btn-row">
        <label class="check"><input type="radio" name="guest_mode" value="existing" ${prefill.guest_id ? 'checked' : ''}> Existing guest</label>
        <label class="check"><input type="radio" name="guest_mode" value="new" ${prefill.guest_id ? '' : 'checked'}> New guest</label>
      </div>
      <div id="g-existing" class="${prefill.guest_id ? '' : 'hidden'}">
        <input type="search" id="g-search" placeholder="Search by name, email, phone or ID…" value="${esc(prefill.guest_name || '')}">
        <input type="hidden" name="guest_id" value="${esc(prefill.guest_id || '')}">
        <div class="guest-results hidden" id="g-results"></div>
        <div class="small muted" id="g-picked" style="margin-top:6px">${prefill.guest_id ? 'Selected: ' + esc(prefill.guest_name) : 'No guest selected'}</div>
      </div>
      <div id="g-new" class="form-grid ${prefill.guest_id ? 'hidden' : ''}">
        ${field('First name *', 'first_name')}${field('Last name *', 'last_name')}
        ${field('Email', 'email', '', 'type="email"')}${field('Phone', 'phone')}
        ${field('ID / passport no.', 'id_number')}<label class="check" style="align-self:end"><input type="checkbox" name="vip"> VIP guest</label>
      </div>
      <div class="form-section">Stay</div>
      <div class="form-grid g4">
        ${field('Check-in *', 'check_in', ci, 'type="date"')}${field('Check-out *', 'check_out', co, 'type="date"')}
        ${field('Adults', 'adults', 1, 'type="number" min="1" max="20"')}${field('Children', 'children', 0, 'type="number" min="0" max="20"')}
        ${selectField('Room type', 'type_id', [['', 'Any type']].concat(types.map((t) => [t.id, `${t.name} (${money(t.base_rate)})`])), '', 'full')}
      </div>
      <div><div class="small muted" id="avail-info" style="margin-bottom:6px"></div><div class="room-options" id="room-options"></div></div>
      <div class="form-section">Rate &amp; payment</div>
      <div class="form-grid g4">
        ${field('Nightly rate *', 'rate', '', 'type="number" step="0.01" min="0"')}
        ${selectField('Source', 'source', SOURCES.map((s) => [s, label(s)]), 'walk-in')}
        ${field('Deposit', 'deposit', '', 'type="number" step="0.01" min="0" placeholder="0.00"')}
        ${selectField('Deposit method', 'deposit_method', Object.entries(METHODS), 'card')}
        <div class="full small muted" id="est-total"></div>
        ${textField('Notes / special requests', 'notes')}
      </div>
    </div>`;

  const res = await modal({
    title: 'New reservation', wide: true, submit: 'Create reservation', body,
    onOpen: (m) => {
      const f = $('form', m);
      const searchAvail = async () => {
        const p = { check_in: f.check_in.value, check_out: f.check_out.value,
          guests: (+f.adults.value || 1) + (+f.children.value || 0), type_id: f.type_id.value };
        const info = $('#avail-info', m);
        const box = $('#room-options', m);
        if (!p.check_in || !p.check_out || p.check_out <= p.check_in) {
          info.textContent = 'Choose valid check-in and check-out dates.'; box.innerHTML = ''; return;
        }
        try {
          rooms = await GET('/availability?' + qs(p));
        } catch (e) { info.textContent = e.message; box.innerHTML = ''; return; }
        const nights = nightsOf(p);
        info.textContent = rooms.length ? `${rooms.length} room(s) available for ${nights} night(s) — select one:` : 'No rooms available for these dates and guest count.';
        if (selectedRoom && !rooms.find((r) => r.id === selectedRoom.id)) selectedRoom = null;
        if (!selectedRoom && prefill.room_id) selectedRoom = rooms.find((r) => r.id === prefill.room_id) || null;
        box.innerHTML = rooms.map((r) => `
          <label class="room-opt ${selectedRoom && selectedRoom.id === r.id ? 'selected' : ''}">
            <input type="radio" name="room_id" value="${r.id}" ${selectedRoom && selectedRoom.id === r.id ? 'checked' : ''}>
            <b>${esc(r.number)}</b> ${r.status === 'dirty' ? '<span class="badge b-warn">Dirty</span>' : ''}
            <div class="small">${esc(r.type_name)}</div>
            <div class="small muted">${money(r.base_rate)}/night · up to ${r.capacity}</div></label>`).join('');
        $$('.room-opt input', box).forEach((inp) => inp.addEventListener('change', () => {
          selectedRoom = rooms.find((r) => r.id === +inp.value);
          $$('.room-opt', box).forEach((l) => l.classList.toggle('selected', $('input', l).checked));
          f.rate.value = selectedRoom.base_rate.toFixed(2);
          updateEst();
        }));
        if (selectedRoom && !f.rate.value) f.rate.value = selectedRoom.base_rate.toFixed(2);
        updateEst();
      };
      const updateEst = () => {
        const n = nightsOf({ check_in: f.check_in.value, check_out: f.check_out.value });
        const rate = parseFloat(f.rate.value);
        const tax = parseFloat(state.settings.tax_rate || 0);
        $('#est-total', m).textContent = selectedRoom && n > 0 && rate >= 0
          ? `Estimated: ${n} night(s) × ${money(rate)} = ${money(n * rate)} + ${tax}% tax = ${money(n * rate * (1 + tax / 100))}` : '';
      };
      ['check_in', 'check_out', 'adults', 'children', 'type_id'].forEach((n) => f[n].addEventListener('change', () => {
        if (n === 'check_in' && f.check_out.value <= f.check_in.value) f.check_out.value = addDays(f.check_in.value, 1);
        searchAvail();
      }));
      f.rate.addEventListener('input', updateEst);
      // guest mode
      $$('input[name=guest_mode]', m).forEach((r) => r.addEventListener('change', () => {
        const existing = f.guest_mode.value === 'existing';
        $('#g-existing', m).classList.toggle('hidden', !existing);
        $('#g-new', m).classList.toggle('hidden', existing);
        if (existing) $('#g-search', m).focus();
      }));
      let t;
      $('#g-search', m).addEventListener('input', (e) => {
        clearTimeout(t);
        t = setTimeout(async () => {
          const q = e.target.value.trim();
          const box = $('#g-results', m);
          if (!q) { box.classList.add('hidden'); return; }
          const list = await GET('/guests?' + qs({ q })).catch(() => []);
          box.classList.remove('hidden');
          box.innerHTML = list.slice(0, 30).map((g) => `<div data-id="${g.id}" data-name="${esc(g.first_name + ' ' + g.last_name)}">
            <b>${esc(g.first_name)} ${esc(g.last_name)}</b>${vip(g.vip)} <span class="small muted">${esc(g.email || g.phone || '')}</span></div>`).join('')
            || '<div class="muted">No guests found — switch to "New guest"</div>';
          $$('[data-id]', box).forEach((el) => el.addEventListener('click', () => {
            f.guest_id.value = el.dataset.id;
            $('#g-search', m).value = el.dataset.name;
            $('#g-picked', m).textContent = 'Selected: ' + el.dataset.name;
            box.classList.add('hidden');
          }));
        }, 200);
      });
      searchAvail();
    },
    onSubmit: async (v) => {
      const payload = {
        room_id: v.room_id ? +v.room_id : null, check_in: v.check_in, check_out: v.check_out,
        adults: v.adults, children: v.children, rate: v.rate, source: v.source, notes: v.notes,
        deposit: v.deposit || 0, deposit_method: v.deposit_method,
      };
      if (!payload.room_id) throw new Error('Please select a room');
      if (v.guest_mode === 'existing') {
        if (!v.guest_id) throw new Error('Please search and select a guest');
        payload.guest_id = +v.guest_id;
      } else {
        payload.guest = { first_name: v.first_name, last_name: v.last_name, email: v.email, phone: v.phone, id_number: v.id_number, vip: v.vip };
      }
      return POST('/reservations', payload);
    },
  });
  if (res && res.id) {
    toast(`Reservation ${res.code} created`, 'success');
    location.hash = '#/reservations/' + res.id;
  }
}

// ======================================================================= reservation detail
async function viewReservation(view, id, params, alive) {
  const r = await GET('/reservations/' + id);
  if (!alive()) return;
  const f = r.folio;
  const t = todayISO();
  const active = ['booked', 'checked_in'].includes(r.status);
  const g = r.guest;
  view.innerHTML = `
    <div class="page-head">
      <div class="grow"><h1>${esc(r.code)} ${resBadge(r.status)}</h1>
        <div class="sub">${esc(r.guest_name)} · Room ${esc(r.room_number)} · ${fmtDate(r.check_in)} → ${fmtDate(r.check_out)}</div></div>
      <div class="btn-row">
        ${r.status === 'booked' ? '<button class="btn good" id="a-checkin">Check in</button>' : ''}
        ${r.status === 'checked_in' ? '<button class="btn good" id="a-checkout">Check out</button>' : ''}
        ${active ? '<button class="btn" id="a-edit">Edit</button><button class="btn" id="a-move">Change room</button>' : ''}
        ${r.status === 'booked' && r.check_in <= t ? '<button class="btn" id="a-noshow">No-show</button>' : ''}
        ${r.status === 'booked' ? '<button class="btn danger" id="a-cancel">Cancel</button>' : ''}
        <a class="btn" href="#/invoice/${r.id}">Invoice</a>
      </div>
    </div>
    <div class="grid g-main-side">
      <div class="stack">
        <div class="card"><div class="card-head"><h2 class="grow">Folio</h2>
          ${active ? '<button class="btn sm" id="a-charge">+ Add charge</button>' : ''}
          ${r.status !== 'checked_out' ? '<button class="btn sm primary" id="a-pay">+ Payment</button>' : ''}</div>
          <div class="table-wrap"><table>
            <thead><tr><th>Date</th><th>Description</th><th class="num">Qty</th><th class="num">Unit</th><th class="num">Amount</th><th></th></tr></thead>
            <tbody>
              <tr><td class="nowrap">${fmtDate(r.check_in)}</td><td>Room ${esc(r.room_number)} — ${esc(r.room_type)}
                ${['cancelled', 'no_show'].includes(r.status) ? '<span class="small muted">(not charged)</span>' : ''}</td>
                <td class="num">${f.nights}</td><td class="num">${money(r.rate)}</td><td class="num">${money(f.room_total)}</td><td></td></tr>
              ${f.charges.map((c) => `<tr><td class="nowrap">${fmtDate(c.created_at)}</td>
                <td>${esc(c.description)} <span class="small muted">${esc(c.category)}</span></td>
                <td class="num">${qty(c.quantity)}</td><td class="num">${money(c.unit_price)}</td><td class="num">${money(c.amount)}</td>
                <td class="actions">${active ? `<button class="btn sm ghost danger" data-void="${c.id}" title="Void charge">✕</button>` : ''}</td></tr>`).join('')}
              <tr><td></td><td colspan="3" class="right muted">Subtotal</td><td class="num">${money(f.subtotal)}</td><td></td></tr>
              <tr><td></td><td colspan="3" class="right muted">Tax (${f.tax_rate}%)</td><td class="num">${money(f.tax)}</td><td></td></tr>
              <tr class="total"><td></td><td colspan="3" class="right">Total</td><td class="num">${money(f.total)}</td><td></td></tr>
              <tr><td></td><td colspan="3" class="right muted">Paid</td><td class="num">${money(-f.paid)}</td><td></td></tr>
              <tr class="total"><td></td><td colspan="3" class="right">Balance due</td>
                <td class="num ${f.balance > 0.004 ? 'balance-due' : 'balance-ok'}">${money(f.balance)}</td><td></td></tr>
            </tbody></table></div></div>
        <div class="card"><div class="card-head"><h2 class="grow">Payments</h2></div>
          <div class="table-wrap"><table><thead><tr><th>Date</th><th>Method</th><th>Reference</th><th>By</th><th class="num">Amount</th><th></th></tr></thead><tbody>
          ${f.payments.map((p) => `<tr><td class="nowrap">${fmtDateTime(p.created_at)}</td><td>${esc(METHODS[p.method] || p.method)}</td>
            <td>${esc(p.reference)}</td><td>${esc(p.created_by_name || '')}</td>
            <td class="num ${p.amount < 0 ? 'balance-due' : ''}">${money(p.amount)}</td>
            <td class="actions">${isAdmin() && r.status !== 'checked_out' ? `<button class="btn sm ghost danger" data-voidpay="${p.id}" title="Void payment">✕</button>` : ''}</td></tr>`).join('')
            || emptyRow(6, 'No payments recorded')}
          </tbody></table></div></div>
      </div>
      <div class="stack">
        <div class="card"><div class="card-head"><h2 class="grow">Stay</h2></div><div class="card-body">
          <dl class="kv" style="margin:0">
            <dt>Room</dt><dd>${esc(r.room_number)} · ${esc(r.room_type)}</dd>
            <dt>Check-in</dt><dd>${fmtDate(r.check_in)} ${r.checked_in_at ? `<div class="small muted">Arrived ${fmtDateTime(r.checked_in_at)}</div>` : ''}</dd>
            <dt>Check-out</dt><dd>${fmtDate(r.check_out)} ${r.checked_out_at ? `<div class="small muted">Departed ${fmtDateTime(r.checked_out_at)}</div>` : ''}</dd>
            <dt>Nights</dt><dd>${f.nights}</dd>
            <dt>Guests</dt><dd>${r.adults} adult(s)${r.children ? `, ${r.children} child(ren)` : ''}</dd>
            <dt>Rate</dt><dd>${money(r.rate)} / night</dd>
            <dt>Source</dt><dd>${esc(label(r.source))}</dd>
            <dt>Booked</dt><dd>${fmtDateTime(r.created_at)}</dd>
            <dt>Notes</dt><dd style="white-space:pre-wrap">${esc(r.notes) || '<span class="muted">—</span>'}</dd>
          </dl></div></div>
        <div class="card"><div class="card-head"><h2 class="grow">Guest</h2><a class="small" href="#/guests/${g.id}">Profile</a></div><div class="card-body">
          <dl class="kv" style="margin:0">
            <dt>Name</dt><dd>${esc(g.first_name)} ${esc(g.last_name)}${vip(g.vip)}</dd>
            <dt>Email</dt><dd>${g.email ? `<a href="mailto:${esc(g.email)}">${esc(g.email)}</a>` : '—'}</dd>
            <dt>Phone</dt><dd>${esc(g.phone) || '—'}</dd>
            <dt>ID / passport</dt><dd>${esc(g.id_number) || '—'}</dd>
            <dt>Address</dt><dd>${esc(g.address) || '—'}</dd>
            ${g.notes ? `<dt>Notes</dt><dd>${esc(g.notes)}</dd>` : ''}
          </dl></div></div>
      </div>
    </div>`;

  const on = (sel, fn) => { const el = $(sel, view); if (el) el.addEventListener('click', fn); };
  on('#a-checkin', () => doCheckIn(r.id, refresh));
  on('#a-checkout', () => doCheckOut(r, refresh));
  on('#a-edit', () => editReservation(r));
  on('#a-move', () => moveRoom(r));
  on('#a-cancel', () => cancelReservation(r));
  on('#a-noshow', () => noShow(r));
  on('#a-charge', () => addCharge(r));
  on('#a-pay', () => addPayment(r));
  $$('[data-void]', view).forEach((b) => b.addEventListener('click', async () => {
    if (!(await confirmBox('Void charge', 'Remove this charge from the folio? Inventory items will be returned to stock.', 'Void charge'))) return;
    if (await guarded(() => DEL(`/reservations/${r.id}/charges/${b.dataset.void}`), 'Charge voided')) refresh();
  }));
  $$('[data-voidpay]', view).forEach((b) => b.addEventListener('click', async () => {
    if (!(await confirmBox('Void payment', 'Delete this payment record?', 'Void payment'))) return;
    if (await guarded(() => DEL(`/reservations/${r.id}/payments/${b.dataset.voidpay}`), 'Payment voided')) refresh();
  }));
}

async function doCheckIn(id, after) {
  try {
    await POST(`/reservations/${id}/checkin`);
    toast('Guest checked in', 'success');
    after();
  } catch (e) {
    if (/not cleaned/.test(e.message)) {
      if (await confirmBox('Room not clean', esc(e.message) + '. Check the guest in anyway?', 'Check in anyway', false)) {
        if (await guarded(() => POST(`/reservations/${id}/checkin`, { force: true }), 'Guest checked in')) after();
      }
    } else toast(e.message, 'error');
  }
}

async function doCheckOut(r, after) {
  const f = r.folio;
  const early = r.check_out > todayISO();
  const due = f.balance > 0.004;
  const body = `
    <div class="stack">
      <dl class="kv" style="margin:0"><dt>Guest</dt><dd>${esc(r.guest_name)}</dd><dt>Room</dt><dd>${esc(r.room_number)}</dd>
        <dt>Folio total</dt><dd>${money(f.total)}</dd><dt>Paid</dt><dd>${money(f.paid)}</dd>
        <dt>Balance</dt><dd class="${due ? 'balance-due' : 'balance-ok'}">${money(f.balance)}</dd></dl>
      ${early ? `<label class="check"><input type="checkbox" name="early_departure" checked> Early departure — shorten stay to today (scheduled ${fmtDate(r.check_out)})</label>` : ''}
      ${due ? `<div class="notice warn">The balance must be settled. Record the final payment below.</div>
        <div class="form-grid">${field('Payment amount', 'amount', f.balance.toFixed(2), 'type="number" step="0.01"')}
        ${selectField('Method', 'method', Object.entries(METHODS), 'card')}${field('Reference', 'reference', '', '', 'full')}</div>
        ${isAdmin() ? '<label class="check small"><input type="checkbox" name="force"> Check out without settling (admin override — balance stays open)</label>' : ''}` : ''}
      <div class="small muted">The room will be marked dirty for housekeeping.</div>
    </div>`;
  let paymentPosted = false;
  const ok = await modal({
    title: 'Check out ' + r.code, body, submit: 'Complete check-out',
    onOpen: (m) => {
      const cb = $('[name=early_departure]', m);
      if (cb && due) cb.addEventListener('change', async () => {
        // recompute the balance preview for an early departure
        const n = cb.checked ? Math.max(1, nightsOf({ check_in: r.check_in, check_out: todayISO() })) : f.nights;
        const sub = n * r.rate + f.extras_total;
        const bal = Math.round((sub * (1 + f.tax_rate / 100) - f.paid) * 100) / 100;
        $('[name=amount]', m).value = Math.max(0, bal).toFixed(2);
      });
    },
    onSubmit: async (v) => {
      const amt = parseFloat(v.amount);
      if (due && !v.force && amt > 0 && !paymentPosted) {
        await POST(`/reservations/${r.id}/payments`, { amount: amt, method: v.method, reference: v.reference || 'Check-out' });
        paymentPosted = true;
      }
      return POST(`/reservations/${r.id}/checkout`, { early_departure: !!v.early_departure, force: !!v.force });
    },
  });
  if (ok) { toast('Guest checked out', 'success'); after(); }
  else if (paymentPosted) after(); // payment was recorded even though check-out did not complete
}

async function editReservation(r) {
  const inHouse = r.status === 'checked_in';
  const ok = await modal({
    title: 'Edit ' + r.code, wide: false,
    body: `<div class="form-grid">
      ${field('Check-in', 'check_in', r.check_in, `type="date" ${inHouse ? 'disabled' : ''}`)}
      ${field('Check-out', 'check_out', r.check_out, 'type="date"')}
      ${field('Adults', 'adults', r.adults, 'type="number" min="1"')}${field('Children', 'children', r.children, 'type="number" min="0"')}
      ${field('Nightly rate', 'rate', r.rate.toFixed(2), 'type="number" step="0.01" min="0"')}
      ${selectField('Source', 'source', SOURCES.map((s) => [s, label(s)]), r.source)}
      ${textField('Notes', 'notes', r.notes)}
      <div class="full small muted">Room ${esc(r.room_number)} must be free for the new dates. Use “Change room” to switch rooms.</div></div>`,
    onSubmit: (v) => PUT('/reservations/' + r.id, v),
  });
  if (ok) { toast('Reservation updated', 'success'); refresh(); }
}

async function moveRoom(r) {
  const from = r.status === 'checked_in' && r.check_in < todayISO() ? todayISO() : r.check_in;
  const rooms = await guarded(() => GET('/availability?' + qs({
    check_in: from < r.check_out ? from : r.check_in, check_out: r.check_out, guests: r.adults + r.children, exclude: r.id })));
  if (!rooms) return;
  const list = rooms.filter((x) => x.id !== r.room_id);
  const ok = await modal({
    title: 'Change room — ' + r.code,
    body: list.length ? `<div class="stack"><div class="small muted">Rooms free for the remaining stay (current: ${esc(r.room_number)}):</div>
      <div class="room-options">${list.map((x) => `<label class="room-opt"><input type="radio" name="room_id" value="${x.id}">
        <b>${esc(x.number)}</b><div class="small">${esc(x.type_name)}</div><div class="small muted">${money(x.base_rate)}/night</div></label>`).join('')}</div>
      <label class="check"><input type="checkbox" name="use_rate"> Apply the new room's standard rate</label>
      ${r.status === 'checked_in' ? '<div class="small muted">The current room will be marked dirty.</div>' : ''}</div>`
      : '<div class="notice warn">No other rooms are available for these dates.</div>',
    submit: 'Move guest',
    onOpen: (m) => $$('.room-opt input', m).forEach((i) => i.addEventListener('change', () =>
      $$('.room-opt', m).forEach((l) => l.classList.toggle('selected', $('input', l).checked)))),
    onSubmit: list.length ? (v) => {
      if (!v.room_id) throw new Error('Select a room');
      const target = list.find((x) => x.id === +v.room_id);
      const body = { room_id: +v.room_id };
      if (v.use_rate) body.rate = target.base_rate;
      return POST(`/reservations/${r.id}/move`, body);
    } : undefined,
  });
  if (ok && ok.id) { toast('Room changed', 'success'); refresh(); }
}

async function cancelReservation(r) {
  const ok = await modal({
    title: 'Cancel ' + r.code, danger: true, submit: 'Cancel reservation', cancel: 'Keep reservation',
    body: `<div class="form-grid">${field('Cancellation fee', 'fee', '', 'type="number" step="0.01" min="0" placeholder="0.00"')}
      <div></div>${field('Reason', 'reason', '', '', 'full')}
      <div class="full small muted">The room is released immediately. Refund any deposit via a negative payment if needed.</div></div>`,
    onSubmit: (v) => POST(`/reservations/${r.id}/cancel`, v),
  });
  if (ok) { toast('Reservation cancelled', 'success'); refresh(); }
}

async function noShow(r) {
  const ok = await modal({
    title: 'Mark ' + r.code + ' as no-show', danger: true, submit: 'Mark no-show',
    body: `<div class="form-grid">${field('No-show fee', 'fee', r.rate.toFixed(2), 'type="number" step="0.01" min="0"')}</div>`,
    onSubmit: (v) => POST(`/reservations/${r.id}/noshow`, v),
  });
  if (ok) { toast('Marked as no-show', 'success'); refresh(); }
}

async function addCharge(r) {
  const items = await guarded(() => GET('/items?chargeable=1'));
  if (!items) return;
  const ok = await modal({
    title: 'Post charge to ' + r.code,
    body: `<div class="stack">
      <div class="btn-row"><label class="check"><input type="radio" name="mode" value="item" checked> Inventory item</label>
        <label class="check"><input type="radio" name="mode" value="custom"> Service / other</label></div>
      <div id="c-item" class="form-grid">
        ${selectField('Item', 'item_id', items.map((i) => [i.id, `${i.name} — ${money(i.price)} (${qty(i.quantity)} ${i.unit} left)`]), '', 'full')}
      </div>
      <div id="c-custom" class="form-grid hidden">
        ${field('Description', 'description', '', 'placeholder="e.g. Laundry, Spa, Airport transfer"', 'full')}
        ${selectField('Category', 'category', ['Service', 'Food & Beverage', 'Laundry', 'Spa', 'Transport', 'Telephone', 'Fee', 'Discount', 'Other'], 'Service')}
        ${field('Unit price', 'unit_price', '', 'type="number" step="0.01"')}
        <div class="full small muted">Use a negative price for discounts or adjustments.</div>
      </div>
      <div class="form-grid">${field('Quantity', 'quantity', 1, 'type="number" step="any" min="0.01"')}<div class="small muted" id="c-total" style="align-self:end"></div></div>
    </div>`,
    submit: 'Post charge',
    onOpen: (m) => {
      const f = $('form', m);
      const upd = () => {
        const custom = f.mode.value === 'custom';
        $('#c-item', m).classList.toggle('hidden', custom);
        $('#c-custom', m).classList.toggle('hidden', !custom);
        const price = custom ? parseFloat(f.unit_price.value) : (items.find((i) => i.id === +f.item_id.value) || {}).price;
        const q = parseFloat(f.quantity.value);
        $('#c-total', m).textContent = price != null && !isNaN(price) && q > 0 ? 'Amount: ' + money(price * q) : '';
      };
      $$('input,select', f).forEach((el) => el.addEventListener('input', upd));
      $$('input[name=mode]', f).forEach((el) => el.addEventListener('change', upd));
      upd();
    },
    onSubmit: (v) => {
      const body = v.mode === 'item' ? { item_id: +v.item_id, quantity: v.quantity }
        : { description: v.description, category: v.category, unit_price: v.unit_price, quantity: v.quantity };
      if (v.mode === 'item' && !v.item_id) throw new Error('No chargeable items exist — add some in Inventory');
      return POST(`/reservations/${r.id}/charges`, body);
    },
  });
  if (ok) { toast('Charge posted', 'success'); refresh(); }
}

async function addPayment(r) {
  const bal = r.folio.balance;
  const ok = await modal({
    title: 'Record payment — ' + r.code,
    body: `<div class="form-grid">
      ${field('Amount', 'amount', bal > 0 ? bal.toFixed(2) : '', 'type="number" step="0.01"')}
      ${selectField('Method', 'method', Object.entries(METHODS), 'card')}
      ${field('Reference', 'reference', '', 'placeholder="Receipt / transaction no."', 'full')}
      <div class="full small muted">Balance due: ${money(bal)}. Enter a negative amount to record a refund.</div></div>`,
    submit: 'Record payment',
    onSubmit: (v) => POST(`/reservations/${r.id}/payments`, v),
  });
  if (ok) { toast('Payment recorded', 'success'); refresh(); }
}

// ======================================================================= invoice
async function viewInvoice(view, id, params, alive) {
  const r = await GET('/reservations/' + id);
  if (!alive()) return;
  const s = state.settings, f = r.folio, g = r.guest;
  view.innerHTML = `
    <div class="page-head no-print"><div class="grow"><a href="#/reservations/${r.id}">‹ Back to reservation</a></div>
      <button class="btn primary" id="print">Print / Save PDF</button></div>
    <div class="invoice">
      <div class="inv-head">
        <div><div class="inv-title">${esc(s.hotel_name)}</div><div class="muted">${esc(s.address)}<br>${esc(s.phone)} · ${esc(s.email)}</div></div>
        <div class="right"><div class="inv-title">INVOICE</div><div class="muted">No. ${esc(r.code)}<br>Date: ${fmtDate(todayISO())}</div></div>
      </div>
      <div class="inv-head">
        <div><b>Bill to</b><br>${esc(g.first_name)} ${esc(g.last_name)}<br><span class="muted">${esc(g.address)}<br>${esc(g.email)} ${esc(g.phone)}</span></div>
        <div class="right"><b>Stay</b><br>Room ${esc(r.room_number)} (${esc(r.room_type)})<br>
          <span class="muted">${fmtDate(r.check_in)} – ${fmtDate(r.check_out)} · ${f.nights} night(s)<br>Status: ${esc(label(r.status))}</span></div>
      </div>
      <table><thead><tr><th>Description</th><th class="num">Qty</th><th class="num">Unit price</th><th class="num">Amount</th></tr></thead><tbody>
        <tr><td>Accommodation — ${esc(r.room_type)}</td><td class="num">${f.nights}</td><td class="num">${money(r.rate)}</td><td class="num">${money(f.room_total)}</td></tr>
        ${f.charges.map((c) => `<tr><td>${esc(c.description)} <span class="muted small">(${fmtDate(c.created_at)})</span></td>
          <td class="num">${qty(c.quantity)}</td><td class="num">${money(c.unit_price)}</td><td class="num">${money(c.amount)}</td></tr>`).join('')}
        <tr><td colspan="3" class="right">Subtotal</td><td class="num">${money(f.subtotal)}</td></tr>
        <tr><td colspan="3" class="right">Tax (${f.tax_rate}%)</td><td class="num">${money(f.tax)}</td></tr>
        <tr class="total"><td colspan="3" class="right">Total</td><td class="num">${money(f.total)}</td></tr>
        ${f.payments.map((p) => `<tr><td colspan="3" class="right muted">${p.amount < 0 ? 'Refund' : 'Payment'} — ${esc(METHODS[p.method] || p.method)} ${fmtDate(p.created_at)} ${esc(p.reference)}</td>
          <td class="num">${money(-p.amount)}</td></tr>`).join('')}
        <tr class="total"><td colspan="3" class="right">Balance due</td><td class="num">${money(f.balance)}</td></tr>
      </tbody></table>
      <p class="muted small" style="margin-top:28px">Thank you for staying with us. Check-in ${esc(s.check_in_time)} · Check-out ${esc(s.check_out_time)}</p>
    </div>`;
  $('#print').addEventListener('click', () => window.print());
}

// ======================================================================= guests
async function viewGuests(view, params, alive) {
  view.innerHTML = `
    <div class="page-head"><div class="grow"><h1>Guests</h1><div class="sub">Guest profiles and stay history.</div></div>
      <a class="btn" href="/api/export/guests.csv">Export CSV</a><button class="btn primary" id="g-new">+ New guest</button></div>
    <div class="toolbar"><input type="search" id="g-q" placeholder="Search name, email, phone, ID…"></div>
    <div class="card"><div class="table-wrap"><table><thead><tr><th>Name</th><th>Email</th><th>Phone</th><th>ID / passport</th>
      <th class="num">Stays</th><th>Last stay</th></tr></thead><tbody id="g-body"></tbody></table></div></div>`;
  const load = async () => {
    const list = await GET('/guests?' + qs({ q: $('#g-q').value.trim() }));
    if (!alive()) return;
    $('#g-body').innerHTML = list.map((g) => `<tr class="clickable" data-href="#/guests/${g.id}">
      <td><b>${esc(g.last_name)}, ${esc(g.first_name)}</b>${vip(g.vip)}</td><td>${esc(g.email)}</td><td>${esc(g.phone)}</td>
      <td>${esc(g.id_number)}</td><td class="num">${g.stays}</td><td>${g.last_stay ? fmtDate(g.last_stay) : '—'}</td></tr>`).join('')
      || emptyRow(6, 'No guests found');
    bindRowLinks(view);
  };
  let t;
  $('#g-q').addEventListener('input', () => { clearTimeout(t); t = setTimeout(load, 250); });
  $('#g-new').addEventListener('click', async () => {
    const g = await guestForm();
    if (g) location.hash = '#/guests/' + g.id;
  });
  await load();
}

async function guestForm(g = {}) {
  const res = await modal({
    title: g.id ? 'Edit guest' : 'New guest',
    body: `<div class="form-grid">
      ${field('First name *', 'first_name', g.first_name)}${field('Last name *', 'last_name', g.last_name)}
      ${field('Email', 'email', g.email, 'type="email"')}${field('Phone', 'phone', g.phone)}
      ${field('ID / passport no.', 'id_number', g.id_number)}
      <label class="check" style="align-self:end"><input type="checkbox" name="vip" ${g.vip ? 'checked' : ''}> VIP guest</label>
      ${field('Address', 'address', g.address, '', 'full')}${textField('Notes / preferences', 'notes', g.notes)}</div>`,
    onSubmit: (v) => (g.id ? PUT('/guests/' + g.id, v) : POST('/guests', v)),
  });
  if (res) toast(g.id ? 'Guest updated' : 'Guest created', 'success');
  return res;
}

async function viewGuest(view, id, params, alive) {
  const g = await GET('/guests/' + id);
  if (!alive()) return;
  view.innerHTML = `
    <div class="page-head"><div class="grow"><h1>${esc(g.first_name)} ${esc(g.last_name)} ${vip(g.vip)}</h1>
      <div class="sub">Guest since ${fmtDate(g.created_at)} · ${g.stays} stay(s) · Lifetime value ${money(g.lifetime_value)}</div></div>
      <button class="btn" id="g-edit">Edit</button>
      ${g.reservations.length ? '' : '<button class="btn danger" id="g-del">Delete</button>'}
      <button class="btn primary" id="g-book">+ Book stay</button></div>
    <div class="grid g-main-side">
      <div class="card"><div class="card-head"><h2>Reservations</h2></div><div class="table-wrap"><table>
        <thead><tr><th>Code</th><th>Room</th><th>Dates</th><th>Status</th><th class="num">Total</th></tr></thead><tbody>
        ${g.reservations.map((r) => `<tr class="clickable" data-href="#/reservations/${r.id}"><td><b>${esc(r.code)}</b></td><td>${esc(r.room_number)}</td>
          <td class="nowrap">${fmtDate(r.check_in)} → ${fmtDate(r.check_out)}</td><td>${resBadge(r.status)}</td><td class="num">${money(r.total)}</td></tr>`).join('')
          || emptyRow(5, 'No reservations yet')}
        </tbody></table></div></div>
      <div class="card"><div class="card-head"><h2>Details</h2></div><div class="card-body"><dl class="kv" style="margin:0">
        <dt>Email</dt><dd>${g.email ? `<a href="mailto:${esc(g.email)}">${esc(g.email)}</a>` : '—'}</dd>
        <dt>Phone</dt><dd>${esc(g.phone) || '—'}</dd><dt>ID / passport</dt><dd>${esc(g.id_number) || '—'}</dd>
        <dt>Address</dt><dd>${esc(g.address) || '—'}</dd><dt>Notes</dt><dd style="white-space:pre-wrap">${esc(g.notes) || '—'}</dd>
      </dl></div></div>
    </div>`;
  bindRowLinks(view);
  $('#g-edit').addEventListener('click', async () => { if (await guestForm(g)) refresh(); });
  $('#g-book').addEventListener('click', () => newReservation({ guest_id: g.id, guest_name: `${g.first_name} ${g.last_name}` }));
  const del = $('#g-del');
  if (del) del.addEventListener('click', async () => {
    if (!(await confirmBox('Delete guest', `Delete ${esc(g.first_name)} ${esc(g.last_name)} permanently?`, 'Delete'))) return;
    if (await guarded(() => DEL('/guests/' + g.id), 'Guest deleted')) location.hash = '#/guests';
  });
}

// ======================================================================= rooms
async function viewRooms(view, params, alive) {
  const tab = params.tab || 'rooms';
  const [rooms, types] = await Promise.all([GET('/rooms'), GET('/room-types')]);
  if (!alive()) return;
  state.roomTypes = types;
  view.innerHTML = `
    <div class="page-head"><div class="grow"><h1>Rooms</h1><div class="sub">${rooms.length} rooms · ${types.length} room types</div></div>
      ${isAdmin() ? `<button class="btn primary" id="add">${tab === 'types' ? '+ New room type' : '+ New room'}</button>` : ''}</div>
    <div class="tabs"><button data-tab="rooms" class="${tab === 'rooms' ? 'active' : ''}">Rooms</button>
      <button data-tab="types" class="${tab === 'types' ? 'active' : ''}">Room types &amp; rates</button></div>
    <div class="card"><div class="table-wrap"><table>
    ${tab === 'rooms' ? `
      <thead><tr><th>Room</th><th>Floor</th><th>Type</th><th class="num">Rate</th><th>Housekeeping</th><th>Occupancy</th><th>Notes</th><th></th></tr></thead>
      <tbody>${rooms.map((r) => `<tr><td><b>${esc(r.number)}</b></td><td>${r.floor}</td><td>${esc(r.type_name)}</td>
        <td class="num">${money(r.base_rate)}</td><td>${roomBadge(r.status)}</td>
        <td>${r.occupied ? `<a href="#/reservations/${r.current_reservation_id}">${esc(r.current_guest)}</a><div class="small muted">until ${fmtDate(r.current_check_out)}</div>` : '<span class="muted">Vacant</span>'}</td>
        <td class="small muted">${esc(r.notes)}</td>
        <td class="actions">${isAdmin() ? `<button class="btn sm" data-edit="${r.id}">Edit</button> <button class="btn sm ghost danger" data-del="${r.id}">Delete</button>` : ''}</td></tr>`).join('')
        || emptyRow(8, 'No rooms yet')}</tbody>` : `
      <thead><tr><th>Name</th><th>Description</th><th>Amenities</th><th class="num">Capacity</th><th class="num">Base rate</th><th class="num">Rooms</th><th></th></tr></thead>
      <tbody>${types.map((t) => `<tr><td><b>${esc(t.name)}</b></td><td>${esc(t.description)}</td><td class="small">${esc(t.amenities)}</td>
        <td class="num">${t.capacity}</td><td class="num">${money(t.base_rate)}</td><td class="num">${t.room_count}</td>
        <td class="actions">${isAdmin() ? `<button class="btn sm" data-tedit="${t.id}">Edit</button> <button class="btn sm ghost danger" data-tdel="${t.id}">Delete</button>` : ''}</td></tr>`).join('')
        || emptyRow(7, 'No room types yet')}</tbody>`}
    </table></div></div>`;
  $$('[data-tab]', view).forEach((b) => b.addEventListener('click', () => { location.hash = '#/rooms?tab=' + b.dataset.tab; }));
  const add = $('#add', view);
  if (add) add.addEventListener('click', () => (tab === 'types' ? roomTypeForm() : roomForm()));
  $$('[data-edit]', view).forEach((b) => b.addEventListener('click', () => roomForm(rooms.find((r) => r.id === +b.dataset.edit))));
  $$('[data-tedit]', view).forEach((b) => b.addEventListener('click', () => roomTypeForm(types.find((t) => t.id === +b.dataset.tedit))));
  $$('[data-del]', view).forEach((b) => b.addEventListener('click', async () => {
    const r = rooms.find((x) => x.id === +b.dataset.del);
    if (await confirmBox('Delete room', `Delete room ${esc(r.number)}?`, 'Delete') && await guarded(() => DEL('/rooms/' + r.id), 'Room deleted')) refresh();
  }));
  $$('[data-tdel]', view).forEach((b) => b.addEventListener('click', async () => {
    const t = types.find((x) => x.id === +b.dataset.tdel);
    if (await confirmBox('Delete room type', `Delete ${esc(t.name)}?`, 'Delete') && await guarded(() => DEL('/room-types/' + t.id), 'Room type deleted')) refresh();
  }));
}

async function roomForm(r = {}) {
  if (!state.roomTypes.length) { toast('Create a room type first', 'error'); return; }
  const ok = await modal({
    title: r.id ? 'Edit room ' + r.number : 'New room',
    body: `<div class="form-grid">${field('Room number *', 'number', r.number)}${field('Floor', 'floor', r.floor ?? 1, 'type="number"')}
      ${selectField('Room type *', 'type_id', state.roomTypes.map((t) => [t.id, `${t.name} (${money(t.base_rate)})`]), r.type_id)}
      ${selectField('Status', 'status', [['clean', 'Clean'], ['dirty', 'Dirty'], ['maintenance', 'Maintenance']], r.status || 'clean')}
      ${field('Notes', 'notes', r.notes, '', 'full')}</div>`,
    onSubmit: (v) => (r.id ? PUT('/rooms/' + r.id, v) : POST('/rooms', v)),
  });
  if (ok) { toast('Room saved', 'success'); refresh(); }
}

async function roomTypeForm(t = {}) {
  const ok = await modal({
    title: t.id ? 'Edit room type' : 'New room type',
    body: `<div class="form-grid">${field('Name *', 'name', t.name, '', 'full')}
      ${field('Base rate / night *', 'base_rate', t.base_rate, 'type="number" step="0.01" min="0"')}
      ${field('Max guests *', 'capacity', t.capacity || 2, 'type="number" min="1"')}
      ${field('Description', 'description', t.description, '', 'full')}${field('Amenities', 'amenities', t.amenities, 'placeholder="Wi-Fi, TV, …"', 'full')}</div>`,
    onSubmit: (v) => (t.id ? PUT('/room-types/' + t.id, v) : POST('/room-types', v)),
  });
  if (ok) { toast('Room type saved', 'success'); refresh(); }
}

// ======================================================================= housekeeping
async function viewHousekeeping(view, params, alive) {
  const rooms = await GET('/rooms');
  if (!alive()) return;
  const filter = params.f || 'all';
  const shown = rooms.filter((r) => filter === 'all' || r.status === filter || (filter === 'occupied' && r.occupied));
  const floors = [...new Set(shown.map((r) => r.floor))];
  const count = (s) => rooms.filter((r) => r.status === s).length;
  view.innerHTML = `
    <div class="page-head"><div class="grow"><h1>Housekeeping</h1><div class="sub">Update room cleaning and maintenance status.</div></div></div>
    <div class="tabs">${[['all', `All (${rooms.length})`], ['dirty', `Dirty (${count('dirty')})`], ['clean', `Clean (${count('clean')})`],
      ['maintenance', `Maintenance (${count('maintenance')})`], ['occupied', `Occupied (${rooms.filter((r) => r.occupied).length})`]]
      .map(([k, t]) => `<button data-f="${k}" class="${filter === k ? 'active' : ''}">${t}</button>`).join('')}</div>
    ${floors.map((fl) => `<div class="hk-floor"><h3>Floor ${fl}</h3><div class="hk-grid">
      ${shown.filter((r) => r.floor === fl).map((r) => `
        <div class="card hk-card ${r.status}">
          <div style="display:flex;align-items:center;gap:8px"><span class="room-no">${esc(r.number)}</span><span class="grow"></span>${roomBadge(r.status)}</div>
          <div class="meta">${esc(r.type_name)}<br>
            ${r.occupied ? `<span class="badge b-info plain">Occupied</span> ${esc(r.current_guest)}` : r.arriving_reservation_id ? '<span class="badge b-violet plain">Arrival today</span>' : 'Vacant'}
            ${r.notes ? `<br><i>${esc(r.notes)}</i>` : ''}</div>
          <div class="btn-row">
            ${r.status !== 'clean' ? `<button class="btn sm good" data-s="clean" data-id="${r.id}">Mark clean</button>` : ''}
            ${r.status !== 'dirty' ? `<button class="btn sm" data-s="dirty" data-id="${r.id}">Mark dirty</button>` : ''}
            ${r.status !== 'maintenance' ? `<button class="btn sm danger" data-s="maintenance" data-id="${r.id}">Maintenance</button>` : ''}
          </div>
        </div>`).join('')}</div></div>`).join('') || '<div class="card empty">No rooms in this view</div>'}`;
  $$('[data-f]', view).forEach((b) => b.addEventListener('click', () => { location.hash = '#/housekeeping?f=' + b.dataset.f; }));
  $$('[data-s]', view).forEach((b) => b.addEventListener('click', async () => {
    const room = rooms.find((r) => r.id === +b.dataset.id);
    let body = { status: b.dataset.s };
    if (b.dataset.s === 'maintenance') {
      const v = await modal({ title: `Room ${room.number} — maintenance`, submit: 'Set maintenance',
        body: field('Issue / notes', 'notes', room.notes, 'placeholder="e.g. Leaking tap"'), onSubmit: async (x) => x });
      if (!v) return;
      body.notes = v.notes;
    } else if (room.status === 'maintenance') body.notes = '';
    if (await guarded(() => POST(`/rooms/${room.id}/status`, body), `Room ${room.number} marked ${label(b.dataset.s).toLowerCase()}`)) refresh();
  }));
}

// ======================================================================= inventory
async function viewInventory(view, params, alive) {
  const tab = params.tab || 'items';
  view.innerHTML = `
    <div class="page-head"><div class="grow"><h1>Inventory</h1><div class="sub">Stock levels, movements and suppliers.</div></div>
      <div class="btn-row" id="inv-actions"></div></div>
    <div class="tabs">${[['items', 'Items'], ['movements', 'Stock movements'], ['suppliers', 'Suppliers']]
      .map(([k, t]) => `<button data-tab="${k}" class="${tab === k ? 'active' : ''}">${t}</button>`).join('')}</div>
    <div id="inv-body"></div>`;
  $$('[data-tab]', view).forEach((b) => b.addEventListener('click', () => { location.hash = '#/inventory?tab=' + b.dataset.tab; }));
  const body = $('#inv-body', view);
  const actions = $('#inv-actions', view);
  if (tab === 'items') return inventoryItems(body, actions, params, alive);
  if (tab === 'movements') return inventoryMovements(body, actions, alive);
  return inventorySuppliers(body, actions, alive);
}

async function inventoryItems(body, actions, params, alive) {
  const all = await GET('/items?include_inactive=1');
  if (!alive()) return;
  const cats = [...new Set(all.map((i) => i.category))].sort();
  actions.innerHTML = `<a class="btn" href="/api/export/items.csv">Export CSV</a><button class="btn primary" id="i-new">+ New item</button>`;
  body.innerHTML = `
    <div class="toolbar">
      <input type="search" id="i-q" placeholder="Search name or SKU…">
      <select id="i-cat">${options([['', 'All categories']].concat(cats))}</select>
      <label class="check"><input type="checkbox" id="i-low" ${params.low ? 'checked' : ''}> Low stock only</label>
      <label class="check"><input type="checkbox" id="i-inactive"> Show inactive</label>
      <span class="grow"></span><span class="muted small" id="i-sum"></span>
    </div>
    <div class="card"><div class="table-wrap"><table><thead><tr><th>SKU</th><th>Item</th><th>Category</th><th class="num">On hand</th>
      <th class="num">Reorder at</th><th class="num">Unit cost</th><th class="num">Sale price</th><th class="num">Stock value</th><th></th></tr></thead>
      <tbody id="i-body"></tbody></table></div></div>`;
  const draw = () => {
    const q = $('#i-q').value.trim().toLowerCase();
    const cat = $('#i-cat').value;
    const low = $('#i-low').checked;
    const inactive = $('#i-inactive').checked;
    const list = all.filter((i) => (inactive || i.active) && (!cat || i.category === cat) && (!low || i.low_stock)
      && (!q || i.name.toLowerCase().includes(q) || i.sku.toLowerCase().includes(q)));
    $('#i-sum').textContent = `${list.length} items · value ${money(list.reduce((a, i) => a + i.stock_value, 0))}`;
    $('#i-body').innerHTML = list.map((i) => `<tr class="clickable" data-href="#/inventory/${i.id}">
      <td class="nowrap"><b>${esc(i.sku)}</b></td>
      <td>${esc(i.name)} ${i.chargeable ? '<span class="badge b-info plain">Chargeable</span>' : ''} ${i.active ? '' : '<span class="badge plain">Inactive</span>'}
        <div class="small muted">${esc(i.supplier_name || '')}</div></td>
      <td>${esc(i.category)}</td>
      <td class="num">${i.low_stock ? '<span class="badge b-bad">Low</span> ' : ''}<b>${qty(i.quantity)}</b> ${esc(i.unit)}</td>
      <td class="num">${qty(i.reorder_level)}</td><td class="num">${money(i.cost)}</td>
      <td class="num">${i.chargeable ? money(i.price) : '—'}</td><td class="num">${money(i.stock_value)}</td>
      <td class="actions"><button class="btn sm" data-m="receive" data-id="${i.id}">Receive</button>
        <button class="btn sm" data-m="issue" data-id="${i.id}">Issue</button>
        <button class="btn sm" data-m="adjust" data-id="${i.id}">Count</button></td></tr>`).join('')
      || emptyRow(9, 'No items match');
    bindRowLinks(body);
    $$('[data-m]', body).forEach((b) => b.addEventListener('click', () =>
      stockMove(all.find((i) => i.id === +b.dataset.id), b.dataset.m, refresh)));
  };
  ['#i-q', '#i-cat', '#i-low', '#i-inactive'].forEach((s) => $(s).addEventListener('input', draw));
  $('#i-new').addEventListener('click', async () => { if (await itemForm()) refresh(); });
  draw();
}

async function inventoryMovements(body, actions, alive) {
  actions.innerHTML = `<a class="btn" href="/api/export/movements.csv">Export CSV</a>`;
  body.innerHTML = `<div class="toolbar">
      <select id="m-kind">${options([['', 'All movement types'], ['receive', 'Received'], ['issue', 'Issued'], ['adjust', 'Adjustments'], ['sale', 'Guest sales'], ['return', 'Returns']])}</select>
      <label class="check small">From <input type="date" id="m-from"></label><label class="check small">To <input type="date" id="m-to"></label></div>
    <div class="card"><div class="table-wrap"><table><thead><tr><th>Date</th><th>Item</th><th>Type</th><th class="num">Change</th>
      <th class="num">Balance</th><th>Reason</th><th>Reservation</th><th>By</th></tr></thead><tbody id="m-body"></tbody></table></div></div>`;
  const load = async () => {
    const list = await GET('/movements?' + qs({ kind: $('#m-kind').value, from: $('#m-from').value, to: $('#m-to').value }));
    if (!alive()) return;
    $('#m-body').innerHTML = list.map(movementRow).join('') || emptyRow(8, 'No stock movements');
  };
  ['#m-kind', '#m-from', '#m-to'].forEach((s) => $(s).addEventListener('change', load));
  await load();
}
function movementRow(m) {
  return `<tr><td class="nowrap small">${fmtDateTime(m.created_at)}</td>
    <td>${m.item_name ? `<a href="#/inventory/${m.item_id}">${esc(m.item_name)}</a>` : ''}</td>
    <td><span class="badge ${MOVE_BADGE[m.kind] || ''}">${esc(label(m.kind))}</span></td>
    <td class="num ${m.change < 0 ? 'balance-due' : 'balance-ok'}">${m.change > 0 ? '+' : ''}${qty(m.change)}</td>
    <td class="num">${qty(m.balance_after)}</td><td>${esc(m.reason)}</td>
    <td>${m.reservation_code ? `<a href="#/reservations/${m.reservation_id}">${esc(m.reservation_code)}</a>` : ''}</td>
    <td class="small">${esc(m.user_name || '')}</td></tr>`;
}

async function inventorySuppliers(body, actions, alive) {
  const list = await GET('/suppliers');
  if (!alive()) return;
  actions.innerHTML = '<button class="btn primary" id="s-new">+ New supplier</button>';
  body.innerHTML = `<div class="card"><div class="table-wrap"><table><thead><tr><th>Name</th><th>Contact</th><th>Phone</th><th>Email</th>
    <th class="num">Items</th><th></th></tr></thead><tbody>
    ${list.map((s) => `<tr><td><b>${esc(s.name)}</b></td><td>${esc(s.contact)}</td><td>${esc(s.phone)}</td>
      <td>${s.email ? `<a href="mailto:${esc(s.email)}">${esc(s.email)}</a>` : ''}</td><td class="num">${s.item_count}</td>
      <td class="actions"><button class="btn sm" data-edit="${s.id}">Edit</button>
      ${isAdmin() ? `<button class="btn sm ghost danger" data-del="${s.id}">Delete</button>` : ''}</td></tr>`).join('') || emptyRow(6, 'No suppliers yet')}
    </tbody></table></div></div>`;
  const form = async (s = {}) => {
    const ok = await modal({
      title: s.id ? 'Edit supplier' : 'New supplier',
      body: `<div class="form-grid">${field('Name *', 'name', s.name, '', 'full')}${field('Contact person', 'contact', s.contact)}
        ${field('Phone', 'phone', s.phone)}${field('Email', 'email', s.email, 'type="email"', 'full')}</div>`,
      onSubmit: (v) => (s.id ? PUT('/suppliers/' + s.id, v) : POST('/suppliers', v)),
    });
    if (ok) { toast('Supplier saved', 'success'); refresh(); }
  };
  $('#s-new').addEventListener('click', () => form());
  $$('[data-edit]', body).forEach((b) => b.addEventListener('click', () => form(list.find((s) => s.id === +b.dataset.edit))));
  $$('[data-del]', body).forEach((b) => b.addEventListener('click', async () => {
    const s = list.find((x) => x.id === +b.dataset.del);
    if (await confirmBox('Delete supplier', `Delete ${esc(s.name)}? Items will keep their history.`, 'Delete') && await guarded(() => DEL('/suppliers/' + s.id), 'Supplier deleted')) refresh();
  }));
}

async function itemForm(i = {}) {
  const suppliers = await guarded(() => GET('/suppliers'));
  if (!suppliers) return null;
  const res = await modal({
    title: i.id ? 'Edit ' + i.name : 'New inventory item',
    body: `<div class="form-grid">
      ${field('SKU *', 'sku', i.sku, 'placeholder="e.g. MB-WATER"')}${field('Name *', 'name', i.name)}
      ${field('Category', 'category', i.category || 'General', 'list="cat-list"')}${field('Unit', 'unit', i.unit || 'pcs', 'placeholder="pcs, bottle, kg…"')}
      ${i.id ? '' : field('Opening quantity', 'quantity', 0, 'type="number" step="any" min="0"')}
      ${field('Reorder level', 'reorder_level', i.reorder_level ?? 0, 'type="number" step="any" min="0"')}
      ${field('Unit cost', 'cost', i.cost ?? 0, 'type="number" step="0.01" min="0"')}
      ${field('Sale price (to guests)', 'price', i.price ?? 0, 'type="number" step="0.01" min="0"')}
      ${selectField('Supplier', 'supplier_id', [['', '— None —']].concat(suppliers.map((s) => [s.id, s.name])), i.supplier_id)}
      <div class="full btn-row"><label class="check"><input type="checkbox" name="chargeable" ${i.chargeable ? 'checked' : ''}> Can be charged to guest folios</label>
        <label class="check"><input type="checkbox" name="active" ${i.id && !i.active ? '' : 'checked'}> Active</label></div>
      <datalist id="cat-list">${['Minibar', 'Food & Beverage', 'Amenities', 'Cleaning', 'Linen', 'Maintenance', 'Office', 'General'].map((c) => `<option value="${c}">`).join('')}</datalist>
    </div>`,
    onSubmit: (v) => (i.id ? PUT('/items/' + i.id, v) : POST('/items', v)),
  });
  if (res) toast('Item saved', 'success');
  return res;
}

async function stockMove(item, kind, after) {
  const titles = { receive: 'Receive stock', issue: 'Issue stock', adjust: 'Stock count / adjustment' };
  const bodyHtml = {
    receive: `${field(`Quantity received (${item.unit}) *`, 'quantity', '', 'type="number" step="any" min="0"')}
      ${field('Unit cost (optional)', 'unit_cost', item.cost, 'type="number" step="0.01" min="0"')}
      ${field('Reference / note', 'reason', '', 'placeholder="PO / delivery note"', 'full')}
      <div class="full small muted">Cost is updated using the weighted average.</div>`,
    issue: `${field(`Quantity issued (${item.unit}) *`, 'quantity', '', 'type="number" step="any" min="0"')}
      ${field('Issued to / reason', 'reason', '', 'placeholder="e.g. Housekeeping floor 2"')}`,
    adjust: `${field(`Counted quantity (${item.unit}) *`, 'counted', item.quantity, 'type="number" step="any" min="0"')}
      ${field('Reason *', 'reason', '', 'placeholder="e.g. Monthly count, breakage"')}`,
  }[kind];
  const ok = await modal({
    title: `${titles[kind]} — ${item.name}`, submit: titles[kind],
    body: `<div class="notice" style="margin-bottom:12px">Currently on hand: <b>${qty(item.quantity)} ${esc(item.unit)}</b></div><div class="form-grid">${bodyHtml}</div>`,
    onSubmit: (v) => {
      const b = Object.assign({ kind }, v);
      if (kind === 'receive' && v.unit_cost === '') delete b.unit_cost;
      return POST(`/items/${item.id}/movements`, b);
    },
  });
  if (ok) { toast('Stock updated', 'success'); after(); }
}

async function viewItem(view, id, params, alive) {
  const i = await GET('/items/' + id);
  if (!alive()) return;
  view.innerHTML = `
    <div class="page-head"><div class="grow"><a href="#/inventory" class="small">‹ Inventory</a><h1>${esc(i.name)}</h1>
      <div class="sub">${esc(i.sku)} · ${esc(i.category)} ${i.active ? '' : '· <b>Inactive</b>'}</div></div>
      <div class="btn-row"><button class="btn" data-m="receive">Receive</button><button class="btn" data-m="issue">Issue</button>
      <button class="btn" data-m="adjust">Count</button><button class="btn" id="i-edit">Edit</button>
      ${isAdmin() ? '<button class="btn danger" id="i-del">Delete</button>' : ''}</div></div>
    <div class="tiles">
      ${tile('On hand', `${qty(i.quantity)} ${i.unit}`, i.low_stock ? 'Below reorder level — reorder now' : `Reorder at ${qty(i.reorder_level)}`)}
      ${tile('Unit cost', money(i.cost), 'weighted average')}
      ${tile('Sale price', i.chargeable ? money(i.price) : '—', i.chargeable ? 'chargeable to guests' : 'internal use only')}
      ${tile('Stock value', money(i.stock_value), i.supplier_name || 'No supplier')}
    </div>
    <div class="card"><div class="card-head"><h2>Movement history</h2></div><div class="table-wrap"><table>
      <thead><tr><th>Date</th><th></th><th>Type</th><th class="num">Change</th><th class="num">Balance</th><th>Reason</th><th>Reservation</th><th>By</th></tr></thead>
      <tbody>${i.movements.map((m) => movementRow(Object.assign({}, m, { item_name: '' }))).join('') || emptyRow(8, 'No movements')}</tbody></table></div></div>`;
  $$('[data-m]', view).forEach((b) => b.addEventListener('click', () => stockMove(i, b.dataset.m, refresh)));
  $('#i-edit').addEventListener('click', async () => { if (await itemForm(i)) refresh(); });
  const del = $('#i-del');
  if (del) del.addEventListener('click', async () => {
    if (!(await confirmBox('Delete item', `Delete ${esc(i.name)}? Items used on guest folios are deactivated instead.`, 'Delete'))) return;
    const r = await guarded(() => DEL('/items/' + i.id));
    if (r) { toast(r.deactivated ? 'Item deactivated (has sales history)' : 'Item deleted', 'success'); location.hash = '#/inventory'; }
  });
}

// ======================================================================= reports
async function viewReports(view, params, alive) {
  const to = params.to || todayISO();
  const from = params.from || addDays(to, -29);
  const r = await GET('/reports/summary?' + qs({ from, to }));
  if (!alive()) return;
  const T = r.totals;
  const tbl = (head, rowsHtml, empty) => `<div class="table-wrap"><table><thead><tr>${head.map((h, i) => `<th class="${i ? 'num' : ''}">${h}</th>`).join('')}</tr></thead>
    <tbody>${rowsHtml || emptyRow(head.length, empty || 'No data')}</tbody></table></div>`;
  view.innerHTML = `
    <div class="page-head"><div class="grow"><h1>Reports</h1><div class="sub">${fmtDate(r.from)} – ${fmtDate(r.to)} · ${r.room_count} rooms</div></div>
      <div class="btn-row">
        ${[[7, '7d'], [30, '30d'], [90, '90d']].map(([n, t]) => `<button class="btn sm" data-preset="${n}">${t}</button>`).join('')}
        <button class="btn sm" data-preset="month">This month</button>
        <input type="date" id="r-from" value="${r.from}" style="width:auto"><input type="date" id="r-to" value="${r.to}" style="width:auto">
        <a class="btn sm" href="/api/export/daily_report.csv?${qs({ from: r.from, to: r.to })}">Export CSV</a></div></div>
    <div class="tiles">
      ${tile('Occupancy', T.occupancy + '%', `${T.room_nights} room-nights sold`)}
      ${tile('Room revenue', money(T.room_revenue), 'accrued, excl. tax')}
      ${tile('ADR', money(T.adr), 'average daily rate')}
      ${tile('RevPAR', money(T.revpar), 'revenue per available room')}
      ${tile('Extras revenue', money(T.extras_revenue), 'charges posted')}
      ${tile('Payments', money(T.payments), 'collected in period')}
    </div>
    <div class="card" style="margin-bottom:16px"><div class="card-head"><h2 class="grow">Daily occupancy</h2>
      <span class="small muted">% of rooms occupied each night · hover a bar for details</span></div>
      <div class="card-body"><div class="chart" id="occ-chart"></div></div></div>
    <div class="grid g3" style="margin-bottom:16px">
      <div class="card"><div class="card-head"><h2>Payments by method</h2></div>
        ${tbl(['Method', 'Count', 'Amount'], r.payments.map((p) => `<tr><td>${esc(METHODS[p.method] || p.method)}</td><td class="num">${p.count}</td><td class="num">${money(p.amount)}</td></tr>`).join(''))}</div>
      <div class="card"><div class="card-head"><h2>Extras by category</h2></div>
        ${tbl(['Category', 'Count', 'Amount'], r.extras.map((p) => `<tr><td>${esc(p.category)}</td><td class="num">${p.count}</td><td class="num">${money(p.amount)}</td></tr>`).join(''))}</div>
      <div class="card"><div class="card-head"><h2>Booking sources</h2></div>
        ${tbl(['Source', 'Bookings'], r.sources.map((p) => `<tr><td>${esc(label(p.source))}</td><td class="num">${p.count}</td></tr>`).join(''))}</div>
      <div class="card"><div class="card-head"><h2>Top-selling items</h2></div>
        ${tbl(['Item', 'Qty', 'Revenue'], r.top_items.map((p) => `<tr><td>${esc(p.name)}</td><td class="num">${qty(p.qty)}</td><td class="num">${money(p.revenue)}</td></tr>`).join(''))}</div>
      <div class="card"><div class="card-head"><h2>Internal consumption</h2></div>
        ${tbl(['Item', 'Qty', 'Cost'], r.usage.map((p) => `<tr><td>${esc(p.name)}</td><td class="num">${qty(p.qty)} ${esc(p.unit)}</td><td class="num">${money(p.cost)}</td></tr>`).join(''), 'No stock issued in this period')}</div>
      <div class="card"><div class="card-head"><h2 class="grow">Inventory valuation</h2><span class="small muted">now</span></div>
        ${tbl(['Category', 'Low', 'Value'], r.inventory.map((p) => `<tr><td>${esc(p.category)} <span class="small muted">(${p.items})</span></td><td class="num">${p.low ? `<span class="badge b-bad">${p.low}</span>` : '0'}</td><td class="num">${money(p.value)}</td></tr>`).join('')
          + `<tr class="total"><td>Total</td><td></td><td class="num">${money(T.inventory_value)}</td></tr>`)}</div>
    </div>
    <div class="card"><div class="card-head"><h2>Daily detail</h2></div>
      ${tbl(['Date', 'Rooms sold', 'Occupancy', 'Room revenue', 'ADR', 'RevPAR'],
        r.daily.slice().reverse().map((d) => `<tr><td>${fmtDate(d.date, { weekday: 'short', day: 'numeric', month: 'short' })}</td><td class="num">${d.occupied}</td>
          <td class="num">${d.occupancy}%</td><td class="num">${money(d.room_revenue)}</td><td class="num">${money(d.adr)}</td><td class="num">${money(d.revpar)}</td></tr>`).join(''))}</div>`;

  const go = (f, t) => { location.hash = '#/reports?' + qs({ from: f, to: t }); };
  $$('[data-preset]', view).forEach((b) => b.addEventListener('click', () => {
    const t = todayISO();
    if (b.dataset.preset === 'month') go(t.slice(0, 8) + '01', t);
    else go(addDays(t, -(+b.dataset.preset - 1)), t);
  }));
  $('#r-from').addEventListener('change', (e) => e.target.value && go(e.target.value, r.to));
  $('#r-to').addEventListener('change', (e) => e.target.value && go(r.from, e.target.value));
  occupancyChart($('#occ-chart', view), r.daily);
}

/** Single-series bar chart with hover tooltip (one hue; table view below). */
function occupancyChart(el, daily) {
  const W = Math.max(el.clientWidth || 800, 300), H = 220, padL = 36, padR = 8, padT = 10, padB = 26;
  const n = daily.length;
  const bw = (W - padL - padR) / n;
  const gap = Math.min(2, bw * 0.2);
  const y = (v) => padT + (H - padT - padB) * (1 - v / 100);
  const every = Math.ceil(n / Math.max(1, Math.floor((W - padL) / 70)));
  let svg = `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Daily occupancy bar chart">`;
  [0, 25, 50, 75, 100].forEach((v) => {
    svg += `<line class="grid-line" x1="${padL}" x2="${W - padR}" y1="${y(v)}" y2="${y(v)}"/>`;
    svg += `<text class="axis-label" x="${padL - 6}" y="${y(v) + 4}" text-anchor="end">${v}%</text>`;
  });
  daily.forEach((d, i) => {
    const x = padL + i * bw + gap / 2;
    const w = Math.max(1, bw - gap);
    const top = y(d.occupancy);
    const h = Math.max(0, y(0) - top);
    const rr = Math.min(4, w / 2, h);
    // bar with rounded data-end, anchored to the baseline
    const path = h > 0 ? `M${x},${y(0)} V${top + rr} Q${x},${top} ${x + rr},${top} H${x + w - rr} Q${x + w},${top} ${x + w},${top + rr} V${y(0)} Z` : '';
    svg += `<g data-i="${i}"><rect class="bar-hit" x="${padL + i * bw}" y="${padT}" width="${bw}" height="${H - padT - padB}"/>${path ? `<path class="bar" d="${path}"/>` : ''}</g>`;
    if (i % every === 0) svg += `<text class="axis-label" x="${x + w / 2}" y="${H - 8}" text-anchor="middle">${fmtDate(d.date, { day: 'numeric', month: 'short' })}</text>`;
  });
  svg += '</svg><div class="chart-tip hidden"></div>';
  el.innerHTML = svg;
  const tip = $('.chart-tip', el);
  $$('g[data-i]', el).forEach((g) => {
    g.addEventListener('mouseenter', () => {
      const d = daily[+g.dataset.i];
      tip.innerHTML = `<b>${fmtDate(d.date, { weekday: 'short', day: 'numeric', month: 'short' })}</b><br>
        Occupancy ${d.occupancy}% (${d.occupied} rooms)<br>Room revenue ${money(d.room_revenue)} · ADR ${money(d.adr)}`;
      tip.classList.remove('hidden');
    });
    g.addEventListener('mousemove', (e) => {
      const box = el.getBoundingClientRect();
      let left = e.clientX - box.left + 12;
      if (left + tip.offsetWidth > box.width) left = e.clientX - box.left - tip.offsetWidth - 12;
      tip.style.left = Math.max(0, left) + 'px';
      tip.style.top = Math.max(0, e.clientY - box.top - tip.offsetHeight - 8) + 'px';
    });
    g.addEventListener('mouseleave', () => tip.classList.add('hidden'));
  });
}

// ======================================================================= settings
async function viewSettings(view, params, alive) {
  const admin = isAdmin();
  const [settings, users, activity] = await Promise.all([
    GET('/settings'), admin ? GET('/users') : [], admin ? GET('/activity?limit=100') : []]);
  if (!alive()) return;
  view.innerHTML = `
    <div class="page-head"><div class="grow"><h1>Settings</h1></div></div>
    <div class="grid g2">
      <form class="card" id="hotel-form"><div class="card-head"><h2 class="grow">Hotel</h2>
        ${admin ? '<button class="btn primary sm" type="submit">Save</button>' : '<span class="small muted">Admin only</span>'}</div>
        <div class="card-body"><div class="form-grid">
          ${field('Hotel name', 'hotel_name', settings.hotel_name, '', 'full')}${field('Address', 'address', settings.address, '', 'full')}
          ${field('Phone', 'phone', settings.phone)}${field('Email', 'email', settings.email)}
          ${field('Currency symbol', 'currency', settings.currency)}${field('Tax rate (%)', 'tax_rate', settings.tax_rate, 'type="number" step="0.01" min="0" max="100"')}
          ${field('Check-in time', 'check_in_time', settings.check_in_time, 'type="time"')}${field('Check-out time', 'check_out_time', settings.check_out_time, 'type="time"')}
        </div></div></form>
      <form class="card" id="pw-form"><div class="card-head"><h2 class="grow">My password</h2><button class="btn sm" type="submit">Change password</button></div>
        <div class="card-body"><div class="form-grid">
          ${field('Current password', 'current_password', '', 'type="password" autocomplete="current-password"', 'full')}
          ${field('New password', 'new_password', '', 'type="password" autocomplete="new-password"')}
          ${field('Confirm new password', 'confirm', '', 'type="password" autocomplete="new-password"')}
        </div><p class="small muted">Signed in as <b>${esc(state.user.username)}</b> (${esc(state.user.role)}).</p></div></form>
    </div>
    ${admin ? `
    <div class="card" style="margin-top:16px"><div class="card-head"><h2 class="grow">Users</h2><button class="btn primary sm" id="u-new">+ New user</button></div>
      <div class="table-wrap"><table><thead><tr><th>Username</th><th>Name</th><th>Role</th><th>Status</th><th>Created</th><th></th></tr></thead><tbody>
      ${users.map((u) => `<tr><td><b>${esc(u.username)}</b></td><td>${esc(u.full_name)}</td><td>${esc(label(u.role))}</td>
        <td>${u.active ? '<span class="badge b-good">Active</span>' : '<span class="badge">Disabled</span>'}</td><td>${fmtDate(u.created_at)}</td>
        <td class="actions"><button class="btn sm" data-u="${u.id}">Edit</button></td></tr>`).join('')}
      </tbody></table></div></div>
    <div class="card" style="margin-top:16px"><div class="card-head"><h2>Activity log</h2></div>
      <div class="table-wrap" style="max-height:420px;overflow-y:auto"><table><tbody>${activity.map(activityRow).join('') || emptyRow(3, 'No activity')}</tbody></table></div></div>` : ''}`;

  const hotelForm = $('#hotel-form');
  if (!admin) $$('input', hotelForm).forEach((i) => (i.disabled = true));
  hotelForm.addEventListener('submit', async (e) => {
    e.preventDefault();
    const s = await guarded(() => PUT('/settings', formValues(hotelForm)), 'Settings saved');
    if (s) { state.settings = s; renderShell(); router(); }
  });
  const pw = $('#pw-form');
  pw.addEventListener('submit', async (e) => {
    e.preventDefault();
    const v = formValues(pw);
    if (v.new_password !== v.confirm) { toast('New passwords do not match', 'error'); return; }
    if (await guarded(() => POST('/me/password', v), 'Password changed')) pw.reset();
  });
  if (admin) {
    const userForm = async (u = {}) => {
      const ok = await modal({
        title: u.id ? 'Edit user ' + u.username : 'New user',
        body: `<div class="form-grid">
          ${u.id ? '' : field('Username *', 'username', '', 'autocomplete="off"')}
          ${field('Full name *', 'full_name', u.full_name, '', u.id ? 'full' : '')}
          ${selectField('Role', 'role', [['staff', 'Staff (front desk)'], ['admin', 'Administrator']], u.role || 'staff')}
          ${field(u.id ? 'New password (leave blank to keep)' : 'Password *', 'password', '', 'type="password" autocomplete="new-password"')}
          ${u.id ? `<label class="check full"><input type="checkbox" name="active" ${u.active ? 'checked' : ''}> Account active</label>` : ''}
          <div class="full small muted">Staff can run the front desk, guests, housekeeping and inventory. Admins can also manage rooms, rates, users and settings.</div></div>`,
        onSubmit: (v) => (u.id ? PUT('/users/' + u.id, v) : POST('/users', v)),
      });
      if (ok) { toast('User saved', 'success'); refresh(); }
    };
    $('#u-new').addEventListener('click', () => userForm());
    $$('[data-u]', view).forEach((b) => b.addEventListener('click', () => userForm(users.find((u) => u.id === +b.dataset.u))));
  }
}

// ======================================================================= start
boot();
