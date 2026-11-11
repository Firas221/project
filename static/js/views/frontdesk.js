// Front desk: dashboard, room calendar, reservations, booking wizard, folio, invoices, group bookings.
import { DEL, GET, POST, PUT, qs } from '../core/api.js';
import {
  $, $$, PAGE_SIZE, addDays, badge, bindPager, bindRowLinks, check, confirmBox, emptyRow, esc, field, fmtDate, fmtDateTime,
  guarded, label, mealLabel, modal, money, nightsBetween, on, options, pager, qty, selectField, settings, table, textField, tile,
  toast, todayISO, vip,
} from '../core/ui.js';

const METHODS = { card: 'Card', cash: 'Cash', bank_transfer: 'Bank transfer', other: 'Other' };
const SOURCES = ['walk-in', 'direct', 'phone', 'email', 'online', 'booking.com', 'expedia', 'airbnb', 'corporate', 'travel_agent', 'other'];

// ====================================================================== dashboard
export async function dashboardView(el, { ctx, alive }) {
  const d = await GET('/dashboard');
  if (!alive()) return;
  const r = d.rooms;
  el.innerHTML = `
    <div class="page-head"><div class="grow"><h1>Front desk</h1>
      <div class="sub">Business date ${fmtDate(d.business_date)} · ${esc(ctx.settings.hotel_name)}</div></div>
      <a class="btn" href="#/calendar">Room calendar</a></div>
    <div class="tiles">
      ${tile('Occupancy', r.occupancy + '%', `${r.occupied} of ${r.total - r.out_of_order} sellable rooms`)}
      ${tile('In-house guests', d.in_house_guests, `${r.occupied} rooms occupied`)}
      ${tile('Arrivals', d.arrivals.length, 'awaiting check-in')}
      ${tile('Departures', d.departures.length, 'due today or overdue')}
      ${tile('Payments today', money(d.payments_today), 'collected')}
      ${tile('Payments this month', money(d.payments_month), 'collected')}
    </div>
    <div class="statusbar card card-body" style="margin-bottom:16px">
      <div class="seg"><b>${r.vacant_ready}</b>${badge('clean', 'Vacant & ready')}</div>
      <div class="seg"><b>${r.dirty}</b>${badge('dirty', 'Dirty')}</div>
      <div class="seg"><b>${r.out_of_order}</b>${badge('maintenance', 'Out of order')}</div>
      <div class="seg"><b>${d.open_tasks}</b><a href="#/housekeeping">Housekeeping tasks</a></div>
      <div class="seg"><b>${d.open_requests}</b><a href="#/requests">Guest requests</a></div>
      <div class="seg"><b>${d.kitchen_open}</b><a href="#/orders">Room-service orders</a></div>
    </div>
    <div class="grid g2">
      <div class="card"><div class="card-head"><h2 class="grow">Arrivals</h2></div>
        ${table(['Guest', 'Room', 'Nights', ''], d.arrivals.map((a) => `<tr><td><a href="#/reservations/${a.id}">${esc(a.guest_name)}</a>${vip(a.guest_vip)}
          <div class="small muted">${esc(a.code)}${a.check_in < d.date ? ' · <span class="text-bad">late arrival</span>' : ''}${a.group_name ? ' · ' + esc(a.group_name) : ''}</div></td>
          <td>${esc(a.room_number)}<div class="small muted">${esc(a.room_type)}</div></td><td>${a.nights}</td>
          <td class="actions">${ctx.can('frontdesk.checkin') ? `<button class="btn sm good" data-checkin="${a.id}">Check in</button>` : ''}</td></tr>`).join(''), 'No arrivals pending')}</div>
      <div class="card"><div class="card-head"><h2 class="grow">Departures</h2></div>
        ${table(['Guest', 'Room', ['Balance', 'num'], ''], d.departures.map((a) => `<tr><td><a href="#/reservations/${a.id}">${esc(a.guest_name)}</a>
          <div class="small muted">${esc(a.code)}${a.check_out < d.date ? ' · <span class="text-bad">overdue</span>' : ''}</div></td>
          <td>${esc(a.room_number)}</td><td class="num ${a.balance > 0 ? 'text-bad' : ''}">${money(a.balance)}</td>
          <td class="actions"><a class="btn sm" href="#/reservations/${a.id}">Open</a></td></tr>`).join(''), 'No departures due')}</div>
      <div class="card"><div class="card-head"><h2 class="grow">Upcoming arrivals</h2></div>
        ${table(['Date', 'Guest', 'Room', 'Nights'], d.upcoming.map((a) => `<tr class="clickable" data-href="#/reservations/${a.id}">
          <td class="nowrap">${fmtDate(a.check_in)}</td><td>${esc(a.guest_name)}${vip(a.guest_vip)}</td><td>${esc(a.room_number)}</td><td>${a.nights}</td></tr>`).join(''), 'Nothing booked yet')}</div>
      ${ctx.can('inventory.view') ? `<div class="card"><div class="card-head"><h2 class="grow">Low stock</h2></div>
        ${table(['Item', ['On hand', 'num'], ['Reorder at', 'num']], d.low_stock.slice(0, 8).map((i) => `<tr><td>${esc(i.name)}<div class="small muted">${esc(i.sku)}</div></td>
          <td class="num text-bad">${qty(i.quantity)} ${esc(i.unit)}</td><td class="num">${qty(i.reorder_level)}</td></tr>`).join(''), 'All stock levels are healthy')}</div>` : ''}
    </div>`;
  bindRowLinks(el);
  on(el, '[data-checkin]', 'click', (e, b) => checkIn(+b.dataset.checkin, ctx.refresh));
}

// ====================================================================== calendar
export async function calendarView(el, { params, alive }) {
  const start = params.start || addDays(todayISO(), -2);
  const days = Math.min(+(params.days || (innerWidth < 820 ? 10 : 21)), 62);
  const data = await GET('/calendar?' + qs({ start, days }));
  if (!alive()) return;
  const dates = Array.from({ length: days }, (_, i) => addDays(start, i));
  const end = addDays(start, days);
  const t = todayISO();
  const cols = `150px repeat(${days}, minmax(42px, 1fr))`;
  const byRoom = {};
  data.reservations.forEach((r) => (byRoom[r.room_id] = byRoom[r.room_id] || []).push(r));
  const dayCls = (d) => [d === t ? 'today' : '', [5, 6].includes(new Date(d + 'T00:00:00').getDay()) ? 'weekend' : ''].join(' ');
  el.innerHTML = `
    <div class="page-head"><div class="grow"><h1>Room calendar</h1><div class="sub">Click an empty day to book that room; click a booking to open it.</div></div>
      <div class="btn-row"><button class="btn" data-shift="-7">‹ Week</button><button class="btn" data-shift="today">Today</button>
        <button class="btn" data-shift="7">Week ›</button><input type="date" id="cal-start" value="${start}" style="width:auto">
        <select id="cal-days" style="width:auto">${options([[7, '7 days'], [14, '14 days'], [21, '21 days'], [31, '31 days']], days)}</select></div></div>
    <div class="legend">${badge('booked', 'Booked')}${badge('checked_in', 'In house')}${badge('checked_out', 'Checked out')}${badge('maintenance', 'Out of order')}</div>
    <div class="card cal"><div class="cal-inner">
      <div class="cal-row head" style="grid-template-columns:${cols}"><div class="cal-room">Room</div>
        ${dates.map((d, i) => `<div class="cal-cell ${dayCls(d)}" style="grid-column:${i + 2}">${fmtDate(d, { weekday: 'short' })}<br>${fmtDate(d, { day: 'numeric', month: 'short' })}</div>`).join('')}</div>
      ${data.rooms.map((room) => `<div class="cal-row ${room.status === 'maintenance' ? 'maint' : ''}" style="grid-template-columns:${cols}">
        <div class="cal-room"><b>${esc(room.number)}</b> ${room.status === 'maintenance' ? '<span class="badge b-bad plain">OOO</span>' : ''}<small>${esc(room.type_name)}</small></div>
        ${dates.map((d, i) => `<div class="cal-cell ${dayCls(d)}" style="grid-column:${i + 2}" data-room="${room.id}" data-date="${d}" title="Book room ${esc(room.number)} from ${d}"></div>`).join('')}
        ${(byRoom[room.id] || []).map((r) => {
          const s = r.check_in < start ? start : r.check_in;
          const e = r.check_out > end ? end : r.check_out;
          return `<a class="cal-bar ${r.status}" href="#/reservations/${r.id}" style="grid-column:${dates.indexOf(s) + 2} / span ${Math.max(1, nightsBetween(s, e))}"
            title="${esc(r.guest_name)} · ${esc(r.code)} · ${fmtDate(r.check_in)} → ${fmtDate(r.check_out)}">${esc(r.guest_name)}</a>`;
        }).join('')}</div>`).join('')}
    </div></div>`;
  const go = (s, n = days) => { location.hash = `#/calendar?${qs({ start: s, days: n })}`; };
  on(el, '[data-shift]', 'click', (e, b) => go(b.dataset.shift === 'today' ? addDays(todayISO(), -2) : addDays(start, +b.dataset.shift)));
  $('#cal-start', el).addEventListener('change', (e) => e.target.value && go(e.target.value));
  $('#cal-days', el).addEventListener('change', (e) => go(start, e.target.value));
  on(el, '.cal-cell[data-room]', 'click', (e, c) => {
    const d = c.dataset.date < t ? t : c.dataset.date;
    newReservation({ room_id: +c.dataset.room, check_in: d, check_out: addDays(d, 1) });
  });
}

// ====================================================================== reservations list
export async function reservationsView(el, { params, ctx, alive }) {
  el.innerHTML = `
    <div class="page-head"><div class="grow"><h1>Reservations</h1><div class="sub">Search, filter and manage bookings.</div></div>
      <a class="btn" id="exp" href="#">Export CSV</a>
      ${ctx.can('reservations.manage') ? '<button class="btn" id="grp">+ Group booking</button><button class="btn primary" id="new">+ New reservation</button>' : ''}</div>
    <div class="toolbar">
      <input type="search" id="f-q" placeholder="Code, guest, room, e-mail…" value="${esc(params.q || '')}">
      <select id="f-status">${options([['active', 'Active (booked + in house)'], ['', 'All statuses'], ['booked', 'Booked'], ['checked_in', 'In house'],
        ['checked_out', 'Checked out'], ['cancelled', 'Cancelled'], ['no_show', 'No-show']], params.status ?? 'active')}</select>
      <label class="check small">From <input type="date" id="f-from"></label><label class="check small">To <input type="date" id="f-to"></label>
    </div>
    <div class="card" id="list"></div>`;
  let page = 1;
  const load = async (to = 1) => {
    page = to;
    const f = { q: $('#f-q').value.trim(), status: $('#f-status').value, from: $('#f-from').value, to: $('#f-to').value };
    $('#exp').href = '/api/export/reservations?' + qs(f);
    const found = await GET('/reservations?' + qs({ ...f, page, per_page: PAGE_SIZE }));
    if (!alive()) return;
    const list = found.items;
    $('#list').innerHTML = table(['Code', 'Guest', 'Room', 'Check-in', 'Check-out', 'Nights', 'Status', ['Total', 'num'], ['Balance', 'num']],
      list.map((r) => `<tr class="clickable" data-href="#/reservations/${r.id}"><td><b>${esc(r.code)}</b>${r.group_code ? `<div class="small muted">${esc(r.group_name)}</div>` : ''}</td>
        <td>${esc(r.guest_name)}${vip(r.guest_vip)}<div class="small muted">${esc(r.company_name || r.source)}</div></td>
        <td>${esc(r.room_number)}<div class="small muted">${esc(r.room_type)}</div></td><td class="nowrap">${fmtDate(r.check_in)}</td>
        <td class="nowrap">${fmtDate(r.check_out)}</td><td>${r.nights}</td><td>${badge(r.status)}</td><td class="num">${money(r.total)}</td>
        <td class="num ${r.balance > 0.004 ? 'text-bad' : ''}">${money(r.balance)}</td></tr>`).join(''), 'No reservations match these filters') + pager(found);
    bindRowLinks(el);
    bindPager(el, load);
  };
  let timer;
  $('#f-q').addEventListener('input', () => { clearTimeout(timer); timer = setTimeout(() => load(), 250); });
  ['#f-status', '#f-from', '#f-to'].forEach((s) => $(s).addEventListener('change', () => load()));
  if ($('#new')) $('#new').addEventListener('click', () => newReservation());
  if ($('#grp')) $('#grp').addEventListener('click', () => groupBooking());
  await load();
}

// ====================================================================== booking wizard
export async function newReservation(prefill = {}) {
  const [types, companies, plans] = await Promise.all([GET('/room-types'), GET('/companies').catch(() => []), GET('/rate-plans').catch(() => [])]);
  const ci = prefill.check_in || todayISO();
  let selected = null;
  let rooms = [];
  let quote = null;
  const body = `<div class="stack">
    <div class="form-section">Guest</div>
    <div class="btn-row"><label class="check"><input type="radio" name="guest_mode" value="existing" ${prefill.guest_id ? 'checked' : ''}> Existing guest</label>
      <label class="check"><input type="radio" name="guest_mode" value="new" ${prefill.guest_id ? '' : 'checked'}> New guest</label></div>
    <div id="g-existing" class="${prefill.guest_id ? '' : 'hidden'}"><input type="search" id="g-search" placeholder="Search name, e-mail, phone, ID…" value="${esc(prefill.guest_name || '')}">
      <input type="hidden" name="guest_id" value="${esc(prefill.guest_id || '')}"><div class="pick-list hidden" id="g-results"></div>
      <div class="small muted" id="g-picked">${prefill.guest_id ? 'Selected: ' + esc(prefill.guest_name) : 'No guest selected'}</div></div>
    <div id="g-new" class="form-grid ${prefill.guest_id ? 'hidden' : ''}">
      ${field('First name *', 'first_name')}${field('Last name *', 'last_name')}${field('E-mail', 'email', '', 'type="email"')}${field('Phone', 'phone')}
      ${field('Nationality', 'nationality', '', 'list="nat-list"')}${selectField('ID type', 'id_type', [['passport', 'Passport'], ['national_id', 'Egyptian national ID'], ['driving_license', 'Driving licence'], ['other', 'Other']], 'passport')}
      ${field('ID / passport no.', 'id_number')}${check('VIP guest', 'vip')}
      <datalist id="nat-list">${['Egyptian', 'Saudi', 'Emirati', 'Kuwaiti', 'Jordanian', 'Lebanese', 'British', 'German', 'Italian', 'French', 'American', 'Russian', 'Chinese'].map((n) => `<option value="${n}">`).join('')}</datalist></div>
    <div class="form-section">Stay</div>
    <div class="form-grid g4">${field('Check-in *', 'check_in', ci, 'type="date"')}${field('Check-out *', 'check_out', prefill.check_out || addDays(ci, 1), 'type="date"')}
      ${field('Adults', 'adults', 1, 'type="number" min="1" max="20"')}${field('Children', 'children', 0, 'type="number" min="0" max="20"')}
      ${selectField('Room type', 'type_id', [['', 'Any type']].concat(types.filter((t) => t.active).map((t) => [t.id, `${t.name} (${money(t.base_rate)})`])), '', 'full')}</div>
    <div><div class="small muted" id="avail-info"></div><div class="room-options" id="room-options"></div></div>
    <div class="form-section">Rate, company &amp; deposit</div>
    <div class="form-grid g4">
      ${selectField('Rate plan', 'rate_plan_id', [['', 'Room only, flexible']].concat(plans.map(planOption)), '')}
      ${field('Promo code', 'promo_code', '', 'style="text-transform:uppercase"')}
      ${selectField('Company (corporate rate)', 'company_id', [['', '— None —']].concat(companies.map((c) => [c.id, `${c.name}${c.discount_pct ? ` (-${c.discount_pct}%)` : ''}`])), '')}
      ${field('Nightly rate *', 'rate', '', 'type="number" step="0.01" min="0"')}${selectField('Source', 'source', SOURCES.map((s) => [s, label(s)]), 'walk-in')}
      ${check('Bill to company (city ledger)', 'bill_to_company', false, 'full')}
      ${field('Deposit', 'deposit', '', 'type="number" step="0.01" min="0" placeholder="0.00"')}${selectField('Deposit method', 'deposit_method', Object.entries(METHODS), 'card')}
      <div class="full small" id="est"></div>
      ${textField('Special requests', 'special_requests')}${textField('Internal notes', 'notes')}</div></div>`;

  const res = await modal({
    title: 'New reservation', wide: true, submit: 'Create reservation', body,
    onOpen: (m) => {
      const f = $('form', m);
      const updateQuote = async () => {
        quote = null;
        if (!selected || f.check_out.value <= f.check_in.value) { renderEst(); return; }
        try {
          quote = await GET('/quote?' + qs({ room_type_id: selected.type_id, check_in: f.check_in.value, check_out: f.check_out.value,
            promo_code: f.promo_code.value.trim(), company_id: f.company_id.value, rate_plan_id: f.rate_plan_id.value,
            adults: f.adults.value, children: f.children.value }));
          f.rate.value = quote.average_rate.toFixed(2);
        } catch (e) { $('#est', m).innerHTML = `<span class="text-bad">${esc(e.message)}</span>`; return; }
        renderEst();
      };
      const renderEst = () => {
        const n = nightsBetween(f.check_in.value, f.check_out.value);
        const rate = parseFloat(f.rate.value);
        const s = settings;
        const sc = parseFloat(s.service_charge_rate || 0), vat = parseFloat(s.vat_rate || 0);
        if (!selected || !(n > 0) || !(rate >= 0)) { $('#est', m).textContent = ''; return; }
        const sub = n * rate;
        const total = sub * (1 + sc / 100) * (1 + vat / 100);
        $('#est', m).innerHTML = `<b>${n} night(s) × ${money(rate)} = ${money(sub)}</b> + ${sc}% service + ${vat}% VAT ≈ <b>${money(total)}</b>
          ${quote && quote.discount ? ` · ${esc(quote.discount_label)} applied (-${quote.discount_pct}%)` : ''}
          ${quote && !quote.meets_min_stay ? `<div class="text-bad">Minimum stay for these dates is ${quote.min_nights} nights.</div>` : ''}
          ${quote && quote.nightly.some((x) => x.label) ? `<div class="muted">${quote.nightly.filter((x) => x.label).map((x) => `${fmtDate(x.date, { day: 'numeric', month: 'short' })}: ${money(x.rate)} (${esc(x.label)})`).join(' · ')}</div>` : ''}`;
      };
      const searchAvail = async () => {
        const p = { check_in: f.check_in.value, check_out: f.check_out.value, guests: (+f.adults.value || 1) + (+f.children.value || 0), type_id: f.type_id.value };
        const info = $('#avail-info', m);
        const box = $('#room-options', m);
        if (!p.check_in || !p.check_out || p.check_out <= p.check_in) { info.textContent = 'Choose valid dates.'; box.innerHTML = ''; return; }
        try { rooms = await GET('/availability?' + qs(p)); } catch (e) { info.textContent = e.message; box.innerHTML = ''; return; }
        info.textContent = rooms.length ? `${rooms.length} room(s) available for ${nightsBetween(p.check_in, p.check_out)} night(s) — select one:` : 'No rooms available for these dates and guests.';
        if (selected && !rooms.find((r) => r.id === selected.id)) selected = null;
        if (!selected && prefill.room_id) selected = rooms.find((r) => r.id === prefill.room_id) || null;
        box.innerHTML = rooms.map((r) => `<label class="room-opt ${selected && selected.id === r.id ? 'selected' : ''}">
          <input type="radio" name="room_id" value="${r.id}" ${selected && selected.id === r.id ? 'checked' : ''}>
          <b>${esc(r.number)}</b> ${r.status === 'dirty' ? badge('dirty') : ''}<div class="small">${esc(r.type_name)}</div>
          <div class="small muted">from ${money(r.base_rate)} · up to ${r.capacity}</div></label>`).join('');
        $$('.room-opt input', box).forEach((inp) => inp.addEventListener('change', () => {
          selected = rooms.find((r) => r.id === +inp.value);
          $$('.room-opt', box).forEach((l) => l.classList.toggle('selected', $('input', l).checked));
          updateQuote();
        }));
        updateQuote();
      };
      ['check_in', 'check_out', 'adults', 'children', 'type_id'].forEach((n) => f[n].addEventListener('change', () => {
        if (n === 'check_in' && f.check_out.value <= f.check_in.value) f.check_out.value = addDays(f.check_in.value, 1);
        searchAvail();
      }));
      ['promo_code', 'company_id', 'rate_plan_id'].forEach((n) => f[n].addEventListener('change', updateQuote));
      f.rate.addEventListener('input', renderEst);
      $$('input[name=guest_mode]', m).forEach((r) => r.addEventListener('change', () => {
        const ex = f.guest_mode.value === 'existing';
        $('#g-existing', m).classList.toggle('hidden', !ex);
        $('#g-new', m).classList.toggle('hidden', ex);
      }));
      guestPicker($('#g-search', m), $('#g-results', m), (g) => { f.guest_id.value = g.id; $('#g-picked', m).textContent = 'Selected: ' + g.name; });
      searchAvail();
    },
    onSubmit: async (v) => {
      if (!v.room_id) throw new Error('Please select a room');
      const payload = { room_id: +v.room_id, check_in: v.check_in, check_out: v.check_out, adults: v.adults, children: v.children,
        rate: v.rate, source: v.source, promo_code: v.promo_code, company_id: v.company_id || null, bill_to_company: v.bill_to_company,
        rate_plan_id: v.rate_plan_id || null,
        special_requests: v.special_requests, notes: v.notes, deposit: v.deposit || 0, deposit_method: v.deposit_method };
      if (v.guest_mode === 'existing') {
        if (!v.guest_id) throw new Error('Search and select a guest');
        payload.guest_id = +v.guest_id;
      } else {
        payload.guest = { first_name: v.first_name, last_name: v.last_name, email: v.email, phone: v.phone, nationality: v.nationality,
          id_type: v.id_type, id_number: v.id_number, vip: v.vip };
      }
      return POST('/reservations', payload);
    },
  });
  if (res && res.id) { toast(`Reservation ${res.code} created`, 'success'); location.hash = '#/reservations/' + res.id; }
}

/** One line describing a rate plan in a drop-down: "Bed & breakfast — Breakfast included, +350.00 EGP per adult". */
function planOption(p) {
  const bits = [mealLabel(p.meal_plan)];
  if (p.adjust_pct) bits.push(`${p.adjust_pct > 0 ? '+' : ''}${p.adjust_pct}%`);
  if (p.per_adult) bits.push(`+${money(p.per_adult)} per adult`);
  if (!p.refundable) bits.push('non-refundable');
  return [p.id, `${p.name} — ${bits.join(', ')}`];
}

/** "Bed & breakfast · Breakfast included · non-refundable" for a reservation. */
export function planSummary(r) {
  return [r.rate_plan_name, mealLabel(r.meal_plan), r.refundable ? '' : 'non-refundable'].filter(Boolean).join(' · ');
}

export function guestPicker(input, box, onPick) {
  let t;
  input.addEventListener('input', () => {
    clearTimeout(t);
    t = setTimeout(async () => {
      const q = input.value.trim();
      if (!q) { box.classList.add('hidden'); return; }
      const list = await GET('/guests?' + qs({ q })).catch(() => []);
      box.classList.remove('hidden');
      box.innerHTML = list.slice(0, 25).map((g) => `<div data-id="${g.id}" data-name="${esc(g.first_name + ' ' + g.last_name)}">
        <b>${esc(g.first_name)} ${esc(g.last_name)}</b>${vip(g.vip)} <span class="small muted">${esc(g.email || g.phone || g.nationality || '')}</span></div>`).join('')
        || '<div class="muted">No guests found</div>';
      $$('[data-id]', box).forEach((d) => d.addEventListener('click', () => {
        input.value = d.dataset.name;
        box.classList.add('hidden');
        onPick({ id: +d.dataset.id, name: d.dataset.name });
      }));
    }, 200);
  });
}

async function groupBooking() {
  const companies = await GET('/companies').catch(() => []);
  let rooms = [];
  const res = await modal({
    title: 'Group booking', wide: true, submit: 'Create group',
    body: `<div class="stack"><div class="form-grid">${field('Group name *', 'group_name', '', 'placeholder="e.g. Delta Petroleum conference"')}
      <div><span class="field-label">Lead guest *</span><input type="search" id="g-search" placeholder="Search guest…"><input type="hidden" name="guest_id">
        <div class="pick-list hidden" id="g-results"></div></div>
      ${field('Check-in', 'check_in', todayISO(), 'type="date"')}${field('Check-out', 'check_out', addDays(todayISO(), 2), 'type="date"')}
      ${selectField('Company', 'company_id', [['', '— None —']].concat(companies.map((c) => [c.id, c.name])), '')}${check('Bill to company', 'bill_to_company')}
      ${selectField('Source', 'source', SOURCES.map((s) => [s, label(s)]), 'corporate')}</div>
      <div class="small muted" id="info">Select at least two rooms. Each room becomes its own reservation linked by a group code.</div>
      <div class="room-options" id="opts"></div>${textField('Notes', 'notes')}</div>`,
    onOpen: (m) => {
      const f = $('form', m);
      guestPicker($('#g-search', m), $('#g-results', m), (g) => { f.guest_id.value = g.id; });
      const load = async () => {
        rooms = await GET('/availability?' + qs({ check_in: f.check_in.value, check_out: f.check_out.value })).catch(() => []);
        $('#opts', m).innerHTML = rooms.map((r) => `<label class="room-opt"><input type="checkbox" name="room_${r.id}" value="${r.id}">
          <b>${esc(r.number)}</b><div class="small">${esc(r.type_name)}</div><div class="small muted">up to ${r.capacity}</div></label>`).join('') || '<div class="muted">No rooms available</div>';
        $$('.room-opt input', m).forEach((i) => i.addEventListener('change', () => i.closest('.room-opt').classList.toggle('selected', i.checked)));
      };
      f.check_in.addEventListener('change', load);
      f.check_out.addEventListener('change', load);
      load();
    },
    onSubmit: (v) => {
      const picked = rooms.filter((r) => v['room_' + r.id]).map((r) => ({ room_id: r.id, adults: Math.min(2, r.capacity) }));
      if (!v.guest_id) throw new Error('Choose the lead guest');
      return POST('/reservations/group', { group_name: v.group_name, guest_id: +v.guest_id, check_in: v.check_in, check_out: v.check_out,
        company_id: v.company_id || null, bill_to_company: v.bill_to_company, source: v.source, notes: v.notes, rooms: picked });
    },
  });
  if (res && res.group_code) { toast(`Group ${res.group_code} created with ${res.reservations.length} rooms`, 'success'); location.hash = '#/reservations/' + res.reservations[0].id; }
}

// ====================================================================== reservation detail
export async function reservationView(el, { args, ctx, alive }) {
  const r = await GET('/reservations/' + args[0]);
  if (!alive()) return;
  const f = r.folio;
  const g = r.guest;
  const active = ['booked', 'checked_in'].includes(r.status);
  const can = ctx.can;
  el.innerHTML = `
    <div class="page-head"><div class="grow"><a class="small" href="#/reservations">‹ Reservations</a><h1>${esc(r.code)} ${badge(r.status)}</h1>
      <div class="sub">${esc(r.guest_name)} · Room ${esc(r.room_number)} · ${fmtDate(r.check_in)} → ${fmtDate(r.check_out)}${r.group_code ? ` · Group ${esc(r.group_name)}` : ''}</div>
      <div class="sub" id="plan-line">${esc(planSummary(r))}</div></div>
      <div class="btn-row">
        ${r.status === 'booked' && can('frontdesk.checkin') ? '<button class="btn good" id="a-in">Check in</button>' : ''}
        ${r.status === 'checked_in' && can('frontdesk.checkin') ? '<button class="btn good" id="a-out">Check out</button>' : ''}
        ${active && can('reservations.manage') ? '<button class="btn" id="a-edit">Edit</button><button class="btn" id="a-move">Change room</button>' : ''}
        ${r.status === 'booked' && r.check_in <= todayISO() && can('reservations.manage') ? '<button class="btn" id="a-noshow">No-show</button>' : ''}
        ${r.status === 'booked' && can('reservations.manage') ? '<button class="btn danger" id="a-cancel">Cancel</button>' : ''}
        ${r.invoice ? `<a class="btn" href="#/invoices/${r.invoice.id}">Tax invoice ${esc(r.invoice.number)}</a>` : `<a class="btn" href="#/folio/${r.id}">Print folio</a>`}
      </div></div>
    <div class="grid g-main-side">
      <div class="stack">
        <div class="card"><div class="card-head"><h2 class="grow">Folio</h2>
          ${active && can('billing.charge') ? '<button class="btn sm" id="a-charge">+ Charge</button>' : ''}
          ${r.status !== 'checked_out' && can('billing.payment') ? '<button class="btn sm primary" id="a-pay">+ Payment</button>' : ''}</div>
          ${table(['Date', 'Description', ['Qty', 'num'], ['Unit', 'num'], ['Amount', 'num'], ''], `
            <tr><td class="nowrap">${fmtDate(r.check_in)}</td><td>Room ${esc(r.room_number)} — ${esc(r.room_type)} ${r.rate_note ? `<span class="small muted">(${esc(r.rate_note)})</span>` : ''}
              ${['cancelled', 'no_show'].includes(r.status) ? '<span class="small muted">(not charged)</span>' : ''}</td>
              <td class="num">${f.nights}</td><td class="num">${money(r.rate)}</td><td class="num">${money(f.room_total)}</td><td></td></tr>
            ${f.charges.map((c) => `<tr><td class="nowrap">${fmtDate(c.created_at)}</td><td>${esc(c.description)} <span class="small muted">${esc(c.category)}</span></td>
              <td class="num">${qty(c.quantity)}</td><td class="num">${money(c.unit_price)}</td><td class="num">${money(c.amount)}</td>
              <td class="actions">${active && can('billing.charge') ? `<button class="btn sm ghost" data-transfer="${c.id}" title="Move to another folio">⇄</button>` : ''}
                ${active && can('billing.void') ? `<button class="btn sm ghost danger" data-void="${c.id}" title="Void">✕</button>` : ''}</td></tr>`).join('')}
            <tr><td></td><td colspan="3" class="right muted">Subtotal</td><td class="num">${money(f.subtotal)}</td><td></td></tr>
            <tr><td></td><td colspan="3" class="right muted">Service charge (${f.service_charge_rate}%)</td><td class="num">${money(f.service_charge)}</td><td></td></tr>
            <tr><td></td><td colspan="3" class="right muted">VAT (${f.vat_rate}%)</td><td class="num">${money(f.vat)}</td><td></td></tr>
            ${f.city_tax ? `<tr><td></td><td colspan="3" class="right muted">City tax (${f.city_tax_rate}%)</td><td class="num">${money(f.city_tax)}</td><td></td></tr>` : ''}
            <tr class="total"><td></td><td colspan="3" class="right">Total</td><td class="num">${money(f.total)}</td><td></td></tr>
            <tr><td></td><td colspan="3" class="right muted">Paid</td><td class="num">${money(-f.paid)}</td><td></td></tr>
            <tr class="total"><td></td><td colspan="3" class="right">Balance due</td><td class="num ${f.balance > 0.004 ? 'text-bad' : 'text-good'}">${money(f.balance)}</td><td></td></tr>`)}</div>
        <div class="card"><div class="card-head"><h2 class="grow">Payments</h2></div>
          ${table(['Date', 'Method', 'Reference', 'By', ['Amount', 'num'], ''], f.payments.map((p) => `<tr><td class="nowrap">${fmtDateTime(p.created_at)}</td>
            <td>${esc(METHODS[p.method] || p.method)}</td><td>${esc(p.reference)}</td><td>${esc(p.created_by_name || '')}</td>
            <td class="num ${p.amount < 0 ? 'text-bad' : ''}">${money(p.amount)}</td>
            <td class="actions">${can('billing.void') && r.status !== 'checked_out' ? `<button class="btn sm ghost danger" data-voidpay="${p.id}">✕</button>` : ''}</td></tr>`).join(''), 'No payments yet')}</div>
        ${r.orders.length ? `<div class="card"><div class="card-head"><h2>Room service</h2></div>${table(['Order', 'Status', 'Placed', ['Total', 'num']],
          r.orders.map((o) => `<tr><td>${esc(o.code)}</td><td>${badge(o.status)}</td><td>${fmtDateTime(o.created_at)}</td><td class="num">${money(o.total)}</td></tr>`).join(''))}</div>` : ''}
        ${r.requests.length ? `<div class="card"><div class="card-head"><h2>Guest requests</h2></div>${table(['When', 'Type', 'Request', 'Status'],
          r.requests.map((q) => `<tr><td class="nowrap">${fmtDateTime(q.created_at)}</td><td>${esc(label(q.kind))}</td><td>${esc(q.message)}</td><td>${badge(q.status)}</td></tr>`).join(''))}</div>` : ''}
      </div>
      <div class="stack">
        <div class="card"><div class="card-head"><h2>Stay</h2></div><div class="card-body"><dl class="kv">
          <dt>Room</dt><dd>${esc(r.room_number)} · ${esc(r.room_type)}</dd>
          <dt>Arrival</dt><dd>${fmtDate(r.check_in)}${r.checked_in_at ? `<div class="small muted">Checked in ${fmtDateTime(r.checked_in_at)}</div>` : ''}</dd>
          <dt>Departure</dt><dd>${fmtDate(r.check_out)}${r.checked_out_at ? `<div class="small muted">Checked out ${fmtDateTime(r.checked_out_at)}</div>` : ''}</dd>
          <dt>Guests</dt><dd>${r.adults} adult(s)${r.children ? `, ${r.children} child(ren)` : ''}</dd>
          <dt>Rate</dt><dd>${money(r.rate)} / night</dd><dt>Source</dt><dd>${esc(label(r.source))}</dd>
          ${r.company_name ? `<dt>Company</dt><dd>${esc(r.company_name)}${r.bill_to_company ? ' <span class="badge b-info plain">Bill to company</span>' : ''}</dd>` : ''}
          ${r.promo_code ? `<dt>Promo</dt><dd>${esc(r.promo_code)}</dd>` : ''}
          <dt>Requests</dt><dd class="pre">${esc(r.special_requests) || '—'}</dd><dt>Notes</dt><dd class="pre">${esc(r.notes) || '—'}</dd>
        </dl></div></div>
        <div class="card"><div class="card-head"><h2 class="grow">Guest</h2>${can('guests.view') ? `<a class="small" href="#/guests/${g.id}">Profile</a>` : ''}</div><div class="card-body"><dl class="kv">
          <dt>Name</dt><dd>${esc(g.first_name)} ${esc(g.last_name)}${vip(g.vip)}</dd><dt>Nationality</dt><dd>${esc(g.nationality) || '<span class="text-bad">missing</span>'}</dd>
          <dt>${esc(label(g.id_type))}</dt><dd>${esc(g.id_number) || '<span class="text-bad">missing</span>'}</dd>
          <dt>E-mail</dt><dd>${esc(g.email) || '—'}</dd><dt>Phone</dt><dd>${esc(g.phone) || '—'}</dd></dl>
          ${r.status === 'booked' && (!g.id_number || !g.nationality) && can('guests.manage') ? '<button class="btn sm" id="a-reg" style="margin-top:10px">Complete registration</button>' : ''}</div></div>
        ${r.group.length > 1 ? `<div class="card"><div class="card-head"><h2>Group: ${esc(r.group_name)}</h2></div>${table(['Code', 'Room', 'Status'],
          r.group.map((x) => `<tr class="clickable" data-href="#/reservations/${x.id}"><td>${esc(x.code)}</td><td>${esc(x.room_number)}</td><td>${badge(x.status)}</td></tr>`).join(''))}</div>` : ''}
      </div></div>`;
  bindRowLinks(el);
  const bind = (sel, fn) => { const b = $(sel, el); if (b) b.addEventListener('click', fn); };
  bind('#a-in', () => checkIn(r.id, ctx.refresh));
  bind('#a-out', () => checkOut(r, ctx));
  bind('#a-edit', () => editReservation(r, ctx));
  bind('#a-move', () => moveRoom(r, ctx));
  bind('#a-cancel', () => cancelReservation(r, ctx));
  bind('#a-noshow', () => noShow(r, ctx));
  bind('#a-charge', () => addCharge(r, ctx));
  bind('#a-pay', () => addPayment(r, ctx));
  bind('#a-reg', async () => { const { guestForm } = await import('./guests.js'); if (await guestForm(g)) ctx.refresh(); });
  on(el, '[data-void]', 'click', async (e, b) => {
    if (await confirmBox('Void charge', 'Remove this charge? Inventory items return to stock.', 'Void') && await guarded(() => DEL(`/reservations/${r.id}/charges/${b.dataset.void}`), 'Charge voided')) ctx.refresh();
  });
  on(el, '[data-voidpay]', 'click', async (e, b) => {
    if (await confirmBox('Void payment', 'Delete this payment record?', 'Void') && await guarded(() => DEL(`/reservations/${r.id}/payments/${b.dataset.voidpay}`), 'Payment voided')) ctx.refresh();
  });
  on(el, '[data-transfer]', 'click', async (e, b) => {
    const ok = await modal({ title: 'Transfer charge', submit: 'Transfer', body: field('Target reservation code', 'target_code', '', 'placeholder="e.g. RHV1004" style="text-transform:uppercase"'),
      onSubmit: (v) => POST(`/reservations/${r.id}/charges/${b.dataset.transfer}/transfer`, v) });
    if (ok) { toast('Charge transferred', 'success'); ctx.refresh(); }
  });
}

export async function checkIn(id, after) {
  try {
    await POST(`/reservations/${id}/checkin`);
    toast('Guest checked in', 'success');
    after();
  } catch (e) {
    if (/not cleaned/.test(e.message) && await confirmBox('Room not clean', esc(e.message) + '. Check in anyway?', 'Check in anyway', false)) {
      if (await guarded(() => POST(`/reservations/${id}/checkin`, { force: true }), 'Guest checked in')) after();
    } else if (!/not cleaned/.test(e.message)) toast(e.message, 'error');
  }
}

async function checkOut(r, ctx) {
  const f = r.folio;
  const early = r.check_out > todayISO();
  const due = f.balance > 0.004;
  const company = r.bill_to_company && r.company_name;
  let paid = false;
  const ok = await modal({
    title: 'Check out ' + r.code, submit: 'Complete check-out',
    body: `<div class="stack"><dl class="kv"><dt>Guest</dt><dd>${esc(r.guest_name)}</dd><dt>Total</dt><dd>${money(f.total)}</dd>
      <dt>Paid</dt><dd>${money(f.paid)}</dd><dt>Balance</dt><dd class="${due ? 'text-bad' : 'text-good'}">${money(f.balance)}</dd></dl>
      ${early ? `${check(`Early departure — shorten stay to today (was ${fmtDate(r.check_out)})`, 'early_departure', true)}` : ''}
      ${due && company ? `<div class="notice">The balance will be transferred to <b>${esc(r.company_name)}</b>'s account (city ledger).</div>` : ''}
      ${due && !company ? `<div class="notice warn">Settle the balance to complete check-out.</div><div class="form-grid">
        ${field('Payment amount', 'amount', f.balance.toFixed(2), 'type="number" step="0.01"')}${selectField('Method', 'method', Object.entries(METHODS), 'card')}
        ${field('Reference', 'reference', '', '', 'full')}</div>${ctx.can('billing.void') ? check('Supervisor override: check out with an open balance', 'force') : ''}` : ''}
      <div class="small muted">A numbered tax invoice is issued and the room goes to housekeeping.</div></div>`,
    onSubmit: async (v) => {
      if (due && !company && !v.force && parseFloat(v.amount) > 0 && !paid) {
        await POST(`/reservations/${r.id}/payments`, { amount: v.amount, method: v.method, reference: v.reference || 'Check-out' });
        paid = true;
      }
      return POST(`/reservations/${r.id}/checkout`, { early_departure: !!v.early_departure, force: !!v.force });
    },
  });
  if (ok) { toast('Checked out — invoice issued', 'success'); ctx.refresh(); } else if (paid) ctx.refresh();
}

async function editReservation(r, ctx) {
  const inHouse = r.status === 'checked_in';
  const [companies, plans] = await Promise.all([GET('/companies').catch(() => []), GET('/rate-plans').catch(() => [])]);
  const planChoices = [['', 'Room only, flexible']].concat(plans.map(planOption));
  if (r.rate_plan_name && !plans.find((p) => p.id === r.rate_plan_id)) planChoices.push([r.rate_plan_id || 'keep', `${r.rate_plan_name} (no longer offered)`]);
  const ok = await modal({
    title: 'Edit ' + r.code,
    body: `<div class="form-grid">${field('Check-in', 'check_in', r.check_in, `type="date" ${inHouse ? 'disabled' : ''}`)}${field('Check-out', 'check_out', r.check_out, 'type="date"')}
      ${field('Adults', 'adults', r.adults, 'type="number" min="1"')}${field('Children', 'children', r.children, 'type="number" min="0"')}
      ${field('Nightly rate (leave to reprice automatically)', 'rate', '', `type="number" step="0.01" min="0" placeholder="${r.rate.toFixed(2)}"`, 'full')}
      ${selectField('Rate plan', 'rate_plan_id', planChoices, r.rate_plan_id || (r.rate_plan_name ? 'keep' : ''), 'full')}
      ${selectField('Source', 'source', SOURCES.map((s) => [s, label(s)]), r.source)}
      ${selectField('Company', 'company_id', [['', '— None —']].concat(companies.map((c) => [c.id, c.name])), r.company_id || '')}
      ${check('Bill to company', 'bill_to_company', r.bill_to_company, 'full')}
      ${textField('Special requests', 'special_requests', r.special_requests)}${textField('Notes', 'notes', r.notes)}</div>`,
    onSubmit: (v) => {
      if (v.rate === '') delete v.rate;
      v.company_id = v.company_id || null;
      if (v.rate_plan_id === 'keep' || String(v.rate_plan_id) === String(r.rate_plan_id || '')) delete v.rate_plan_id;
      else v.rate_plan_id = v.rate_plan_id || null;
      return PUT('/reservations/' + r.id, v);
    },
  });
  if (ok) { toast('Reservation updated', 'success'); ctx.refresh(); }
}

async function moveRoom(r, ctx) {
  const from = r.status === 'checked_in' && r.check_in < todayISO() ? todayISO() : r.check_in;
  const list = (await guarded(() => GET('/availability?' + qs({ check_in: from < r.check_out ? from : r.check_in, check_out: r.check_out,
    guests: r.adults + r.children, exclude: r.id }))) || []).filter((x) => x.id !== r.room_id);
  const ok = await modal({
    title: 'Change room — ' + r.code, submit: 'Move guest',
    body: list.length ? `<div class="room-options">${list.map((x) => `<label class="room-opt"><input type="radio" name="room_id" value="${x.id}"><b>${esc(x.number)}</b>
      <div class="small">${esc(x.type_name)}</div></label>`).join('')}</div>${check("Reprice at the new room's rate", 'reprice')}`
      : '<div class="notice warn">No other rooms are available for these dates.</div>',
    onOpen: (m) => $$('.room-opt input', m).forEach((i) => i.addEventListener('change', () => $$('.room-opt', m).forEach((l) => l.classList.toggle('selected', $('input', l).checked)))),
    onSubmit: list.length ? (v) => { if (!v.room_id) throw new Error('Select a room'); return POST(`/reservations/${r.id}/move`, { room_id: +v.room_id, reprice: v.reprice }); } : undefined,
  });
  if (ok && ok.id) { toast('Room changed', 'success'); ctx.refresh(); }
}

async function cancelReservation(r, ctx) {
  const ok = await modal({ title: 'Cancel ' + r.code, danger: true, submit: 'Cancel reservation', cancel: 'Keep',
    body: `<div class="form-grid">${field('Cancellation fee', 'fee', '', 'type="number" step="0.01" min="0"')}${field('Reason', 'reason', '', '', 'full')}</div>`,
    onSubmit: (v) => POST(`/reservations/${r.id}/cancel`, v) });
  if (ok) { toast('Reservation cancelled', 'success'); ctx.refresh(); }
}

async function noShow(r, ctx) {
  const ok = await modal({ title: 'No-show ' + r.code, danger: true, submit: 'Mark no-show',
    body: field('No-show fee', 'fee', r.rate.toFixed(2), 'type="number" step="0.01" min="0"'), onSubmit: (v) => POST(`/reservations/${r.id}/noshow`, v) });
  if (ok) { toast('Marked as no-show', 'success'); ctx.refresh(); }
}

async function addCharge(r, ctx) {
  const items = await GET('/items/chargeable').catch(() => []);
  const ok = await modal({
    title: 'Post charge to ' + r.code, submit: 'Post charge',
    body: `<div class="stack"><div class="btn-row"><label class="check"><input type="radio" name="mode" value="item" checked> Minibar / item</label>
      <label class="check"><input type="radio" name="mode" value="custom"> Service / other</label></div>
      <div id="c-item">${selectField('Item', 'item_id', items.map((i) => [i.id, `${i.name} — ${money(i.price)} (${qty(i.quantity)} left)`]), '')}</div>
      <div id="c-custom" class="form-grid hidden">${field('Description', 'description', '', 'placeholder="Laundry, spa, airport transfer…"', 'full')}
        ${selectField('Category', 'category', ['Service', 'Laundry', 'Spa', 'Transport', 'Telephone', 'Food & Beverage', 'Fee', 'Discount', 'Other'], 'Service')}
        ${field('Unit price', 'unit_price', '', 'type="number" step="0.01"')}</div>
      ${field('Quantity', 'quantity', 1, 'type="number" step="any" min="0.01"')}</div>`,
    onOpen: (m) => $$('input[name=mode]', m).forEach((x) => x.addEventListener('change', () => {
      const custom = $('form', m).mode.value === 'custom';
      $('#c-item', m).classList.toggle('hidden', custom);
      $('#c-custom', m).classList.toggle('hidden', !custom);
    })),
    onSubmit: (v) => POST(`/reservations/${r.id}/charges`, v.mode === 'item' ? { item_id: +v.item_id, quantity: v.quantity }
      : { description: v.description, category: v.category, unit_price: v.unit_price, quantity: v.quantity }),
  });
  if (ok) { toast('Charge posted', 'success'); ctx.refresh(); }
}

async function addPayment(r, ctx) {
  const ok = await modal({
    title: 'Record payment — ' + r.code, submit: 'Record payment',
    body: `<div class="form-grid">${field('Amount', 'amount', r.folio.balance > 0 ? r.folio.balance.toFixed(2) : '', 'type="number" step="0.01"')}
      ${selectField('Method', 'method', Object.entries(METHODS), 'card')}${field('Reference', 'reference', '', 'placeholder="Receipt / POS no."', 'full')}
      <div class="full small muted">Balance due ${money(r.folio.balance)}. Supervisors can enter a negative amount for a refund. Cash requires an open cashier shift.</div></div>`,
    onSubmit: (v) => POST(`/reservations/${r.id}/payments`, v),
  });
  if (ok) { toast('Payment recorded', 'success'); ctx.refresh(); }
}

// ====================================================================== invoice & folio print
export async function invoiceView(el, { args, ctx, alive }) {
  const inv = await GET('/invoices/' + args[0]);
  if (!alive()) return;
  const d = inv.data;
  el.innerHTML = printable(ctx, {
    title: 'TAX INVOICE', titleAr: 'فاتورة ضريبية', number: inv.number, date: inv.issued_at, d,
    back: `<a href="javascript:history.back()">‹ Back</a>`,
  });
  $('#print', el).addEventListener('click', () => print());
}

export async function folioView(el, { args, ctx, alive }) {
  const r = await GET('/reservations/' + args[0]);
  if (!alive()) return;
  const f = r.folio;
  const d = {
    hotel: ctx.settings, guest: { name: r.guest_name, address: r.guest.address, nationality: r.guest.nationality }, company: null,
    stay: { code: r.code, room: r.room_number, room_type: r.room_type, check_in: r.check_in, check_out: r.check_out, nights: f.nights },
    lines: [{ description: `Accommodation — ${r.room_type}`, quantity: f.nights, unit_price: r.rate, amount: f.room_total }]
      .concat(f.charges.map((c) => ({ description: c.description, quantity: c.quantity, unit_price: c.unit_price, amount: c.amount }))),
    totals: f, payments: f.payments,
  };
  el.innerHTML = printable(ctx, { title: 'GUEST FOLIO (PRO-FORMA)', titleAr: 'كشف حساب', number: r.code, date: todayISO(), d,
    back: `<a href="#/reservations/${r.id}">‹ Back to reservation</a>` });
  $('#print', el).addEventListener('click', () => print());
}

function printable(ctx, { title, titleAr, number, date, d, back }) {
  const h = d.hotel;
  const t = d.totals;
  return `<div class="page-head no-print"><div class="grow">${back}</div><button class="btn primary" id="print">Print / Save PDF</button></div>
    <div class="invoice">
      <div class="inv-head"><div><div class="inv-title">${esc(h.hotel_name)}</div><div class="ar">${esc(h.hotel_name_ar || '')}</div>
        <div class="muted">${esc(h.address)}<br>${esc(h.phone)} · ${esc(h.email)}<br>Tax registration no.: <b>${esc(h.tax_registration_number || '—')}</b>
        ${h.commercial_register ? `<br>Commercial register: ${esc(h.commercial_register)}` : ''}</div></div>
        <div class="right"><div class="inv-title">${esc(title)}</div><div class="ar">${esc(titleAr)}</div><div class="muted">No. <b>${esc(number)}</b><br>Date: ${fmtDate(date)}</div></div></div>
      <div class="inv-head"><div><b>Bill to</b><br>${esc(d.company ? d.company.name : d.guest.name)}
        ${d.company ? `<br><span class="muted">Tax no. ${esc(d.company.tax_number)}<br>${esc(d.company.address)}<br>Guest: ${esc(d.guest.name)}</span>` : `<br><span class="muted">${esc(d.guest.address || '')} ${esc(d.guest.nationality || '')}</span>`}</div>
        <div class="right"><b>Stay</b><br>Room ${esc(d.stay.room)} (${esc(d.stay.room_type)})<br><span class="muted">${fmtDate(d.stay.check_in)} – ${fmtDate(d.stay.check_out)} · ${d.stay.nights} night(s)<br>Ref. ${esc(d.stay.code)}</span></div></div>
      <table><thead><tr><th>Description</th><th class="num">Qty</th><th class="num">Unit price</th><th class="num">Amount</th></tr></thead><tbody>
        ${d.lines.map((l) => `<tr><td>${esc(l.description)}</td><td class="num">${qty(l.quantity)}</td><td class="num">${money(l.unit_price)}</td><td class="num">${money(l.amount)}</td></tr>`).join('')}
        <tr><td colspan="3" class="right">Subtotal</td><td class="num">${money(t.subtotal)}</td></tr>
        <tr><td colspan="3" class="right">Service charge ${t.service_charge_rate}%</td><td class="num">${money(t.service_charge)}</td></tr>
        <tr><td colspan="3" class="right">VAT ${t.vat_rate}% (ضريبة القيمة المضافة)</td><td class="num">${money(t.vat)}</td></tr>
        ${t.city_tax ? `<tr><td colspan="3" class="right">City tax ${t.city_tax_rate}%</td><td class="num">${money(t.city_tax)}</td></tr>` : ''}
        <tr class="total"><td colspan="3" class="right">Total (الإجمالي)</td><td class="num">${money(t.total)}</td></tr>
        ${(d.payments || []).map((p) => `<tr><td colspan="3" class="right muted">${p.amount < 0 ? 'Refund' : 'Payment'} — ${esc(label(p.method))} ${fmtDate(p.date || p.created_at)} ${esc(p.reference || '')}</td><td class="num">${money(-p.amount)}</td></tr>`).join('')}
        <tr class="total"><td colspan="3" class="right">Balance due</td><td class="num">${money(t.balance)}</td></tr></tbody></table>
      <p class="muted small" style="margin-top:24px">Prices include ${t.service_charge_rate}% service charge and ${t.vat_rate}% VAT as shown. Thank you for staying with us.</p></div>`;
}

export { emptyRow };
