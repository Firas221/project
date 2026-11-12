// Finance: cashier shifts, corporate accounts (city ledger), invoices, management reports, VAT report, night audit.
import { GET, POST, PUT, qs } from '../core/api.js';
import {
  $, $$, PAGE_SIZE, addDays, badge, bindPager, bindRowLinks, check, esc, field, fmtDate, fmtDateTime, guarded, label, modal, money, on,
  pager, qty, selectField, table, textField, tile, toast, todayISO,
} from '../core/ui.js';

const METHODS = { card: 'Card', cash: 'Cash', bank_transfer: 'Bank transfer', other: 'Other / city ledger' };

// ====================================================================== cashier
export async function cashierView(el, { ctx, alive }) {
  const data = await GET('/cashier/shifts');
  if (!alive()) return;
  const cur = data.current;
  el.innerHTML = `<div class="page-head"><div class="grow"><h1>Cashier</h1><div class="sub">Open a shift with a cash float before taking cash; close it with a cash count.</div></div></div>
    <div class="grid g2"><div class="card"><div class="card-head"><h2 class="grow">My shift</h2>${cur ? badge('in_progress', 'Open') : badge('closed', 'No open shift')}</div><div class="card-body">
      ${cur ? `<dl class="kv"><dt>Opened</dt><dd>${fmtDateTime(cur.opened_at)}</dd><dt>Opening float</dt><dd>${money(cur.opening_float)}</dd>
        <dt>Cash taken</dt><dd>${money(cur.cash_taken)}</dd>
        ${cur.foreign_cash_taken ? `<dt>Foreign cash taken</dt><dd id="foreign-cash">${cur.foreign_cash_taken.toFixed(2)} ${esc(cur.foreign_currency)} <span class="small muted">(kept apart from the drawer count)</span></dd>` : ''}<dt>All payments</dt><dd>${money(cur.total_taken)} (${cur.payment_count})</dd>
        <dt>Expected in drawer</dt><dd><b>${money(cur.opening_float + cur.cash_taken)}</b></dd></dl><button class="btn primary" id="close" style="margin-top:12px">Close shift &amp; count cash</button>`
        : '<button class="btn primary" id="open">Open shift</button>'}</div></div>
      <div class="card"><div class="card-head"><h2>Recent shifts</h2></div>${table(['Cashier', 'Opened', 'Closed', ['Expected', 'num'], ['Counted', 'num'], ['Variance', 'num']],
        data.shifts.map((s) => `<tr class="clickable" data-shift="${s.id}"><td>${esc(s.user_name)}</td><td class="small">${fmtDateTime(s.opened_at)}</td><td class="small">${s.closed_at ? fmtDateTime(s.closed_at) : badge('in_progress', 'Open')}</td>
        <td class="num">${s.expected_cash != null ? money(s.expected_cash) : '—'}</td><td class="num">${s.counted_cash != null ? money(s.counted_cash) : '—'}</td>
        <td class="num ${s.variance < 0 ? 'text-bad' : s.variance > 0 ? 'text-warn' : ''}">${s.variance != null ? money(s.variance) : '—'}</td></tr>`).join(''), 'No shifts yet')}</div></div>`;
  if ($('#open', el)) $('#open', el).addEventListener('click', async () => {
    const ok = await modal({ title: 'Open cashier shift', submit: 'Open shift', body: field('Opening cash float', 'opening_float', '2000', 'type="number" step="0.01" min="0"'),
      onSubmit: (v) => POST('/cashier/open', v) });
    if (ok) { toast('Shift opened', 'success'); ctx.refresh(); }
  });
  if ($('#close', el)) $('#close', el).addEventListener('click', async () => {
    const ok = await modal({ title: 'Close shift', submit: 'Close shift', body: `${field('Cash counted in drawer *', 'counted_cash', '', 'type="number" step="0.01" min="0"')}${textField('Notes', 'notes')}`,
      onSubmit: (v) => POST('/cashier/close', v) });
    if (ok) { toast(`Shift closed. Variance ${money(ok.variance)}`, ok.variance ? 'error' : 'success'); ctx.refresh(); }
  });
  on(el, '[data-shift]', 'click', async (e, tr) => {
    const s = await GET('/cashier/shifts/' + tr.dataset.shift);
    modal({ title: `Shift of ${s.user_name}`, wide: true, cancel: 'Close', body: table(['Time', 'Reservation', 'Method', 'Reference', ['Amount', 'num']],
      s.payments.map((p) => `<tr><td class="small">${fmtDateTime(p.created_at)}</td><td>${esc(p.reservation_code)}</td><td>${esc(METHODS[p.method])}</td><td>${esc(p.reference)}</td><td class="num">${money(p.amount)}${p.currency ? `<div class="small muted">${p.foreign_amount.toFixed(2)} ${esc(p.currency)}</div>` : ''}</td></tr>`).join(''), 'No payments in this shift') });
  });
}

// ====================================================================== companies (city ledger)
export async function companiesView(el, { ctx, alive }) {
  const list = await GET('/companies');
  if (!alive()) return;
  const manage = ctx.can('billing.void');
  el.innerHTML = `<div class="page-head"><div class="grow"><h1>Corporate accounts</h1><div class="sub">Negotiated discounts and invoiced (city-ledger) stays.</div></div>
      ${manage ? '<button class="btn primary" id="new">+ Company</button>' : ''}</div>
    <div class="card">${table(['Company', 'Tax no.', 'Contact', ['Discount', 'num'], ['Credit limit', 'num'], ['Balance owed', 'num'], ''], list.map((c) => `<tr class="clickable" data-href="#/companies/${c.id}">
      <td><b>${esc(c.name)}</b></td><td>${esc(c.tax_number)}</td><td>${esc(c.contact)}<div class="small muted">${esc(c.email)}</div></td><td class="num">${c.discount_pct}%</td>
      <td class="num">${c.credit_limit ? money(c.credit_limit) : '—'}</td><td class="num ${c.balance > 0 ? 'text-bad' : ''}">${money(c.balance)}</td><td></td></tr>`).join(''), 'No corporate accounts')}</div>`;
  bindRowLinks(el);
  if ($('#new', el)) $('#new', el).addEventListener('click', async () => { if (await companyForm()) ctx.refresh(); });
}

async function companyForm(c = {}) {
  const ok = await modal({ title: c.id ? 'Edit company' : 'New company', wide: true,
    body: `<div class="form-grid">${field('Name *', 'name', c.name, '', 'full')}${field('Tax registration no.', 'tax_number', c.tax_number)}${field('Contact person', 'contact', c.contact)}
      ${field('E-mail', 'email', c.email, 'type="email"')}${field('Phone', 'phone', c.phone)}${field('Address', 'address', c.address, '', 'full')}
      ${field('Corporate discount %', 'discount_pct', c.discount_pct ?? 0, 'type="number" step="0.5" min="0" max="100"')}${field('Credit limit (0 = none)', 'credit_limit', c.credit_limit ?? 0, 'type="number" step="0.01" min="0"')}</div>`,
    onSubmit: (v) => (c.id ? PUT('/companies/' + c.id, v) : POST('/companies', v)) });
  if (ok) toast('Company saved', 'success');
  return ok;
}

export async function companyView(el, { args, ctx, alive }) {
  const c = await GET('/companies/' + args[0]);
  if (!alive()) return;
  el.innerHTML = `<div class="page-head"><div class="grow"><a class="small" href="#/companies">‹ Corporate accounts</a><h1>${esc(c.name)}</h1>
      <div class="sub">Tax no. ${esc(c.tax_number || '—')} · ${c.discount_pct}% discount · balance owed <b>${money(c.balance)}</b></div></div>
      ${ctx.can('billing.void') ? '<button class="btn" id="edit">Edit</button>' : ''}${ctx.can('billing.payment') ? '<button class="btn primary" id="pay">Record payment</button>' : ''}</div>
    <div class="card"><div class="card-head"><h2>Account statement</h2></div>${table(['Date', 'Type', 'Reference', 'Reservation', ['Amount', 'num']], c.ledger.map((l) => `<tr>
      <td class="small">${fmtDateTime(l.created_at)}</td><td>${esc(label(l.kind))}</td><td>${esc(l.reference)}</td><td>${l.reservation_code ? esc(l.reservation_code) : ''}</td>
      <td class="num ${l.amount < 0 ? 'text-good' : ''}">${money(l.amount)}</td></tr>`).join(''), 'No transactions')}</div>`;
  if ($('#edit', el)) $('#edit', el).addEventListener('click', async () => { if (await companyForm(c)) ctx.refresh(); });
  if ($('#pay', el)) $('#pay', el).addEventListener('click', async () => {
    const ok = await modal({ title: 'Payment received from ' + c.name, body: `<div class="form-grid">${field('Amount', 'amount', c.balance > 0 ? c.balance.toFixed(2) : '', 'type="number" step="0.01" min="0"')}
      ${selectField('Method', 'method', [['bank_transfer', 'Bank transfer'], ['card', 'Card'], ['cash', 'Cash'], ['other', 'Other']], 'bank_transfer')}${field('Reference', 'reference', '', '', 'full')}</div>`,
      onSubmit: (v) => POST(`/companies/${c.id}/payments`, v) });
    if (ok) { toast('Payment recorded', 'success'); ctx.refresh(); }
  });
}

// ====================================================================== invoices
export async function invoicesView(el, { params, alive }) {
  const found = await GET('/invoices?' + qs({ from: params.from, to: params.to, page: params.page || 1, per_page: PAGE_SIZE }));
  if (!alive()) return;
  const list = found.items;
  el.innerHTML = `<div class="page-head"><div class="grow"><h1>Tax invoices</h1><div class="sub">Issued automatically at check-out, numbered sequentially per year.</div></div></div>
    <div class="card">${table(['Number', 'Issued', 'Bill to', 'Stay', ['Subtotal', 'num'], ['Service', 'num'], ['VAT', 'num'], ['Total', 'num']], list.map((i) => `
      <tr class="clickable" data-href="#/invoices/${i.id}"><td><b>${esc(i.number)}</b></td><td class="small">${fmtDate(i.issued_at)}</td><td>${esc(i.bill_to)}${i.bill_to_tax_no ? `<div class="small muted">Tax no. ${esc(i.bill_to_tax_no)}</div>` : ''}</td>
      <td>${esc(i.reservation_code)}</td><td class="num">${money(i.subtotal)}</td><td class="num">${money(i.service_charge)}</td><td class="num">${money(i.vat)}</td><td class="num"><b>${money(i.total)}</b></td></tr>`).join(''), 'No invoices yet')}${pager(found)}</div>`;
  bindRowLinks(el);
  bindPager(el, (page) => { location.hash = '#/invoices?' + qs({ from: params.from, to: params.to, page }); });
}

// ====================================================================== reports
export async function reportsView(el, { params, ctx, alive }) {
  const to = params.to || todayISO();
  const from = params.from || addDays(to, -29);
  const r = await GET('/reports/summary?' + qs({ from, to }));
  if (!alive()) return;
  const T = r.totals;
  el.innerHTML = `<div class="page-head"><div class="grow"><h1>Reports</h1><div class="sub">${fmtDate(r.from)} – ${fmtDate(r.to)} · ${r.room_count} rooms</div></div>
      <div class="btn-row">${[[7, '7d'], [30, '30d'], [90, '90d']].map(([n, t]) => `<button class="btn sm" data-preset="${n}">${t}</button>`).join('')}
        <button class="btn sm" data-preset="month">This month</button><input type="date" id="from" value="${r.from}" style="width:auto"><input type="date" id="to" value="${r.to}" style="width:auto">
        <a class="btn sm" href="/api/export/daily?${qs({ from: r.from, to: r.to })}">CSV</a><a class="btn sm" href="#/tax?${qs({ from: r.from, to: r.to })}">VAT report</a></div></div>
    <div class="tiles">${tile('Occupancy', T.occupancy + '%', `${T.room_nights} room-nights`)}${tile('Room revenue', money(T.room_revenue), 'excl. service & VAT')}
      ${tile('ADR', money(T.adr), 'average daily rate')}${tile('RevPAR', money(T.revpar), 'per available room')}${tile('Extras', money(T.extras_revenue), 'F&B, minibar, services')}
      ${tile('Payments', money(T.payments), 'collected')}${tile('VAT invoiced', money(T.vat), `on ${money(T.invoiced_total)} invoiced`)}
      ${tile('Guest rating', r.reviews.average ? r.reviews.average + ' / 5' : '—', `${r.reviews.count} reviews`)}</div>
    <div class="card" style="margin-bottom:16px"><div class="card-head"><h2 class="grow">Daily occupancy</h2><span class="small muted">% of rooms sold each night · hover for details</span></div>
      <div class="card-body"><div class="chart" id="chart"></div></div></div>
    <div class="grid g3" style="margin-bottom:16px">
      ${mini('Payments by method', ['Method', ['Amount', 'num']], r.payments.map((p) => [METHODS[p.method] || p.method, money(p.amount)]))}
      ${mini('Extras by category', ['Category', ['Amount', 'num']], r.extras.map((p) => [p.category, money(p.amount)]))}
      ${mini('Booking sources', ['Source', ['Bookings', 'num']], r.sources.map((p) => [label(p.source), p.count]))}
      ${mini('Guest nationalities', ['Nationality', ['Stays', 'num']], r.nationalities.map((p) => [p.nationality, p.count]))}
      ${mini('Top dishes', ['Dish', ['Revenue', 'num']], r.top_menu.map((p) => [`${p.name} ×${p.qty}`, money(p.revenue)]))}
      ${mini('Housekeeping productivity', ['Housekeeper', ['Rooms', 'num']], r.housekeeping.map((p) => [`${p.name}${p.avg_minutes ? ` (~${p.avg_minutes} min)` : ''}`, p.done]))}
      ${mini('Consumption (kitchen & departments)', ['Item', ['Cost', 'num']], r.usage.map((p) => [`${p.name} (${qty(p.qty)} ${p.unit})`, money(p.cost)]))}
      ${mini('Minibar & item sales', ['Item', ['Revenue', 'num']], r.top_items.map((p) => [`${p.name} ×${qty(p.qty)}`, money(p.revenue)]))}
      ${mini('Inventory valuation', ['Category', ['Value', 'num']], r.inventory.map((p) => [`${p.category}${p.low ? ` (${p.low} low)` : ''}`, money(p.value)]).concat([['<b>Total</b>', `<b>${money(T.inventory_value)}</b>`]]), true)}
    </div>
    <div class="card"><div class="card-head"><h2>Daily detail</h2></div>${table(['Date', ['Rooms sold', 'num'], ['Occupancy', 'num'], ['Room revenue', 'num'], ['ADR', 'num'], ['RevPAR', 'num']],
      r.daily.slice().reverse().map((d) => `<tr><td>${fmtDate(d.date, { weekday: 'short', day: 'numeric', month: 'short' })}</td><td class="num">${d.occupied}</td><td class="num">${d.occupancy}%</td>
      <td class="num">${money(d.room_revenue)}</td><td class="num">${money(d.adr)}</td><td class="num">${money(d.revpar)}</td></tr>`).join(''))}</div>`;
  const go = (f, t) => { location.hash = '#/reports?' + qs({ from: f, to: t }); };
  on(el, '[data-preset]', 'click', (e, b) => { const t = todayISO(); go(b.dataset.preset === 'month' ? t.slice(0, 8) + '01' : addDays(t, -(+b.dataset.preset - 1)), t); });
  $('#from', el).addEventListener('change', (e) => e.target.value && go(e.target.value, r.to));
  $('#to', el).addEventListener('change', (e) => e.target.value && go(r.from, e.target.value));
  barChart($('#chart', el), r.daily);
  void ctx;
}

function mini(title, head, rows, raw) {
  return `<div class="card"><div class="card-head"><h2>${esc(title)}</h2></div>${table(head, rows.map((cells) => `<tr>${cells.map((c, i) =>
    `<td class="${i ? 'num' : ''}">${raw ? c : esc(c)}</td>`).join('')}</tr>`).join(''), 'No data')}</div>`;
}

/** Single-series occupancy bar chart (one hue, rounded data ends, hover tooltip). */
function barChart(el, daily) {
  const W = Math.max(el.clientWidth || 800, 300), H = 220, L = 36, R = 8, T = 10, B = 26;
  const n = daily.length;
  const bw = (W - L - R) / n;
  const gap = Math.min(2, bw * 0.2);
  const y = (v) => T + (H - T - B) * (1 - v / 100);
  const every = Math.ceil(n / Math.max(1, Math.floor((W - L) / 70)));
  let svg = `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Daily occupancy">`;
  [0, 25, 50, 75, 100].forEach((v) => { svg += `<line class="grid-line" x1="${L}" x2="${W - R}" y1="${y(v)}" y2="${y(v)}"/><text class="axis-label" x="${L - 6}" y="${y(v) + 4}" text-anchor="end">${v}%</text>`; });
  daily.forEach((d, i) => {
    const x = L + i * bw + gap / 2, w = Math.max(1, bw - gap), top = y(d.occupancy), h = Math.max(0, y(0) - top), rr = Math.min(4, w / 2, h);
    const path = h > 0 ? `M${x},${y(0)} V${top + rr} Q${x},${top} ${x + rr},${top} H${x + w - rr} Q${x + w},${top} ${x + w},${top + rr} V${y(0)} Z` : '';
    svg += `<g data-i="${i}"><rect class="bar-hit" x="${L + i * bw}" y="${T}" width="${bw}" height="${H - T - B}"/>${path ? `<path class="bar" d="${path}"/>` : ''}</g>`;
    if (i % every === 0) svg += `<text class="axis-label" x="${x + w / 2}" y="${H - 8}" text-anchor="middle">${fmtDate(d.date, { day: 'numeric', month: 'short' })}</text>`;
  });
  el.innerHTML = svg + '</svg><div class="chart-tip hidden"></div>';
  const tip = $('.chart-tip', el);
  $$('g[data-i]', el).forEach((g) => {
    g.addEventListener('mouseenter', () => {
      const d = daily[+g.dataset.i];
      tip.innerHTML = `<b>${fmtDate(d.date, { weekday: 'short', day: 'numeric', month: 'short' })}</b><br>Occupancy ${d.occupancy}% (${d.occupied} rooms)<br>Room revenue ${money(d.room_revenue)}`;
      tip.classList.remove('hidden');
    });
    g.addEventListener('mousemove', (e) => {
      const b = el.getBoundingClientRect();
      let left = e.clientX - b.left + 12;
      if (left + tip.offsetWidth > b.width) left = e.clientX - b.left - tip.offsetWidth - 12;
      tip.style.left = Math.max(0, left) + 'px';
      tip.style.top = Math.max(0, e.clientY - b.top - tip.offsetHeight - 8) + 'px';
    });
    g.addEventListener('mouseleave', () => tip.classList.add('hidden'));
  });
}

export async function taxView(el, { params, alive }) {
  const to = params.to || todayISO();
  const from = params.from || to.slice(0, 8) + '01';
  const r = await GET('/reports/tax?' + qs({ from, to }));
  if (!alive()) return;
  el.innerHTML = `<div class="page-head"><div class="grow"><h1>VAT &amp; service charge report</h1><div class="sub">Invoices issued ${fmtDate(r.from)} – ${fmtDate(r.to)}, for the monthly VAT return.</div></div>
      <div class="btn-row"><input type="date" id="from" value="${r.from}" style="width:auto"><input type="date" id="to" value="${r.to}" style="width:auto">
      <a class="btn" href="/api/export/tax?${qs({ from: r.from, to: r.to })}">Export CSV</a></div></div>
    <div class="tiles">${tile('Taxable subtotal', money(r.totals.subtotal), `${r.invoices.length} invoices`)}${tile('Service charge', money(r.totals.service_charge))}
      ${tile('Output VAT', money(r.totals.vat))}${tile('Invoiced total', money(r.totals.total))}</div>
    <div class="card">${table(['Invoice', 'Date', 'Bill to', 'Tax no.', ['Subtotal', 'num'], ['Service', 'num'], ['VAT', 'num'], ['Total', 'num']], r.invoices.map((i) => `
      <tr class="clickable" data-href="#/invoices/${i.id}"><td>${esc(i.number)}</td><td class="small">${fmtDate(i.issued_at)}</td><td>${esc(i.bill_to)}</td><td>${esc(i.bill_to_tax_no)}</td>
      <td class="num">${money(i.subtotal)}</td><td class="num">${money(i.service_charge)}</td><td class="num">${money(i.vat)}</td><td class="num">${money(i.total)}</td></tr>`).join(''), 'No invoices in this period')}</div>`;
  bindRowLinks(el);
  const go = () => { location.hash = '#/tax?' + qs({ from: $('#from').value, to: $('#to').value }); };
  $('#from', el).addEventListener('change', go);
  $('#to', el).addEventListener('change', go);
}

// ====================================================================== night audit
export async function nightAuditView(el, { ctx, alive }) {
  const a = await GET('/night-audit');
  if (!alive()) return;
  const canClose = ctx.can('nightaudit.close');
  el.innerHTML = `<div class="page-head"><div class="grow"><h1>Night audit</h1><div class="sub">Close the business day: no-shows are posted, the day's figures are locked in, and the date rolls forward.</div></div></div>
    <div class="grid g2"><div class="card"><div class="card-head"><h2 class="grow">Business date ${fmtDate(a.business_date)}</h2></div><div class="card-body stack">
      ${a.pending_arrivals.length ? `<div class="notice warn">${a.pending_arrivals.length} arrival(s) not checked in: ${a.pending_arrivals.map((r) => esc(r.code + ' ' + r.guest_name)).join(', ')}. They will be marked as no-show.</div>` : '<div class="notice">All arrivals are checked in.</div>'}
      ${a.overdue_departures.length ? `<div class="notice warn">${a.overdue_departures.length} guest(s) past their departure date are still in house.</div>` : ''}
      ${a.open_shifts.length ? `<div class="notice warn">Open cashier shifts: ${a.open_shifts.map((s) => esc(s.user_name)).join(', ')}.</div>` : ''}
      ${canClose ? `<form id="close" class="stack">${check('Mark pending arrivals as no-show', 'mark_no_shows', true)}${field('Notes', 'notes')}
        <button class="btn primary" ${a.can_close ? '' : 'disabled'}>Close ${fmtDate(a.business_date)}</button>
        ${a.can_close ? '' : '<div class="small muted">This business date has not finished yet.</div>'}</form>` : '<p class="small muted">Only a manager or administrator can close the day.</p>'}</div></div>
      <div class="card"><div class="card-head"><h2>Closed days</h2></div>${table(['Date', ['Sold', 'num'], ['Room rev.', 'num'], ['Other', 'num'], ['Payments', 'num'], ['No-shows', 'num'], 'Closed by'],
        a.history.map((d) => `<tr><td>${fmtDate(d.business_date)}</td><td class="num">${d.rooms_sold}/${d.rooms_total}</td><td class="num">${money(d.room_revenue)}</td>
        <td class="num">${money(d.other_revenue)}</td><td class="num">${money(d.payments)}</td><td class="num">${d.no_shows}</td><td class="small">${esc(d.closed_by_name || '')}</td></tr>`).join(''), 'No days closed yet')}</div></div>`;
  if ($('#close', el)) $('#close', el).addEventListener('submit', async (e) => {
    e.preventDefault();
    const v = Object.fromEntries(new FormData(e.target));
    if (await guarded(() => POST('/night-audit/close', { mark_no_shows: !!v.mark_no_shows, notes: v.notes || '' }), 'Day closed')) ctx.refresh();
  });
}
