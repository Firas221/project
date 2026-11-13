// Restaurant point of sale: the floor (tables), a check, kitchen tickets and the printed receipt.
import { DEL, GET, POST, PUT } from '../core/api.js';
import { $, $$, badge, check as checkbox, confirmBox, esc, field, fmtDateTime, guarded, modal, money, on, selectField, table, toast } from '../core/ui.js';

const METHODS = [['cash', 'Cash'], ['card', 'Card'], ['bank_transfer', 'Bank transfer'], ['other', 'Other']];
const minutesSince = (stamp) => Math.max(0, Math.round((Date.now() - new Date(stamp.replace(' ', 'T'))) / 60000));

// ====================================================================== floor
export async function restaurantView(el, { ctx, alive }) {
  const floor = await GET('/restaurant/floor');
  if (!alive()) return;
  const manage = ctx.can('restaurant.manage');
  const areas = [...new Set(floor.tables.map((t) => t.area || ''))];
  const card = (t) => `<button type="button" class="table-card ${t.check ? 'busy' : ''}" data-table="${t.id}" ${t.check ? `data-check="${t.check.id}"` : ''}>
    <b>${esc(t.name)}</b><span class="small">${t.seats} seats</span>
    ${t.check ? `<span class="table-total">${money(t.check.total)}</span><span class="small">${t.check.covers} guest(s) · ${minutesSince(t.check.opened_at)} min</span>` : '<span class="small muted">Free</span>'}</button>`;
  el.innerHTML = `<div class="page-head"><div class="grow"><h1>Restaurant</h1><div class="sub">Tap a free table to open a check, or a busy one to add dishes and settle.</div></div>
      <div class="btn-row"><button class="btn" id="takeaway">+ Takeaway</button>${manage ? '<button class="btn" id="setup">Tables…</button>' : ''}</div></div>
    ${areas.map((a) => `${a ? `<h2 class="floor-area">${esc(a)}</h2>` : ''}<div class="table-grid">${floor.tables.filter((t) => (t.area || '') === a).map(card).join('')}</div>`).join('')
      || '<div class="card card-body empty">No tables yet. A manager adds them under “Tables…”.</div>'}
    ${floor.takeaway.length ? `<h2 class="floor-area">Takeaway</h2><div class="table-grid">${floor.takeaway.map((c) => `<button type="button" class="table-card busy" data-check="${c.id}">
      <b>${esc(c.customer_name || c.code)}</b><span class="table-total">${money(c.total)}</span><span class="small">${minutesSince(c.opened_at)} min</span></button>`).join('')}</div>` : ''}`;
  const openCheck = async (tableId, tableName) => {
    const made = await modal({ title: tableName ? `Open ${tableName}` : 'New takeaway order', submit: 'Open check',
      body: `<div class="form-grid">${tableName ? field('Guests', 'covers', 2, 'type="number" min="1" max="50"') : ''}${field('Name (optional)', 'customer_name', '', '', tableName ? '' : 'full')}</div>`,
      onSubmit: (v) => POST('/restaurant/checks', { table_id: tableId, covers: v.covers || 1, customer_name: v.customer_name }) });
    if (made) location.hash = '#/restaurant/check/' + made.id;
  };
  on(el, '.table-card', 'click', (e, b) => {
    if (b.dataset.check) { location.hash = '#/restaurant/check/' + b.dataset.check; return; }
    openCheck(+b.dataset.table, floor.tables.find((t) => t.id === +b.dataset.table).name);
  });
  $('#takeaway', el).addEventListener('click', () => openCheck(null, ''));
  if ($('#setup', el)) $('#setup', el).addEventListener('click', async () => { await tablesDialog(); ctx.refresh(); });
}

async function tablesDialog() {
  await modal({ title: 'Tables', wide: true, cancel: 'Done',
    body: `<div id="tables-list"></div><div class="row-form" style="margin-top:12px">${field('Name', 'name', '', 'placeholder="Table 9"')}${field('Seats', 'seats', 4, 'type="number" min="1" max="50"')}
      ${field('Area', 'area', '', 'placeholder="Terrace"')}<button type="button" class="btn primary" id="add-table">Add table</button></div>`,
    onOpen: (m) => {
      const list = $('#tables-list', m);
      const draw = async () => {
        const tables = await GET('/restaurant/tables');
        list.innerHTML = table(['Table', 'Seats', 'Area', 'In use', ''], tables.map((t) => `<tr><td><b>${esc(t.name)}</b></td><td>${t.seats}</td><td>${esc(t.area)}</td>
          <td>${checkbox('', 'active', t.active).replace('<input', `<input data-toggle="${t.id}"`)}</td>
          <td class="actions"><button type="button" class="btn sm ghost danger" data-del-table="${t.id}" title="Delete table" aria-label="Delete table">✕</button></td></tr>`).join(''), 'No tables yet');
        on(list, '[data-del-table]', 'click', async (e, b) => { if (await guarded(() => DEL('/restaurant/tables/' + b.dataset.delTable), 'Table deleted')) draw(); });
        on(list, '[data-toggle]', 'change', async (e, box) => {
          const t = tables.find((x) => x.id === +box.dataset.toggle);
          await guarded(() => PUT('/restaurant/tables/' + t.id, { name: t.name, seats: t.seats, area: t.area, active: box.checked }));
          draw();
        });
      };
      $('#add-table', m).addEventListener('click', async () => {
        const f = $('form', m);
        if (await guarded(() => POST('/restaurant/tables', { name: f.name.value, seats: f.seats.value, area: f.area.value }), 'Table added')) { f.name.value = ''; draw(); }
      });
      draw();
    } });
}

// ====================================================================== one check
export async function checkView(el, { args, ctx, alive }) {
  const [c, menu] = await Promise.all([GET('/restaurant/checks/' + args[0]), GET('/restaurant/menu')]);
  if (!alive()) return;
  const open = c.status === 'open';
  const pending = [];                       // dishes tapped but not yet sent to the kitchen
  const cats = [...new Set(menu.map((m) => m.category))];
  const state = { open: 'in_progress', paid: 'done', charged: 'done', void: 'cancelled' }[c.status];
  el.innerHTML = `<div class="page-head"><div class="grow"><a class="small" href="#/restaurant">‹ Restaurant</a>
      <h1>${esc(c.table_name)} ${badge(state, { open: 'Open', paid: 'Paid', charged: 'Charged to room', void: 'Void' }[c.status])}</h1>
      <div class="sub">${esc(c.code)} · ${c.covers} guest(s)${c.customer_name ? ' · ' + esc(c.customer_name) : ''} · opened ${fmtDateTime(c.opened_at)}${c.opened_by_name ? ' by ' + esc(c.opened_by_name) : ''}
        ${c.receipt_number ? ` · receipt ${esc(c.receipt_number)}` : ''}${c.room_number ? ` · room ${esc(c.room_number)}` : ''}${c.status === 'void' ? ` · ${esc(c.notes)}` : ''}</div></div>
      <div class="btn-row">${c.status === 'paid' ? `<a class="btn primary" href="#/restaurant/receipt/${c.id}">Receipt</a>` : ''}
        ${open && ctx.can('restaurant.manage') ? '<button class="btn danger" id="void">Void check</button>' : ''}</div></div>
    <div class="grid ${open ? 'g-main-side' : ''}">
      ${open ? `<div class="card"><div class="card-head"><h2>Menu</h2></div><div class="card-body">${cats.map((cat) => `<h3 class="menu-cat">${esc(cat)}</h3>
        <div class="dish-grid">${menu.filter((m) => m.category === cat).map((m) => `<button type="button" class="dish" data-dish="${m.id}"><b>${esc(m.name)}</b><span>${money(m.price)}</span></button>`).join('')}</div>`).join('')
        || '<div class="empty">The menu is empty.</div>'}</div></div>` : ''}
      <div class="card"><div class="card-head"><h2>Check</h2></div>
        <div id="bill">${table(['Dish', ['Qty', 'num'], ['Amount', 'num'], ''], c.lines.map((l) => `<tr class="${l.status === 'void' ? 'struck' : ''}">
          <td>${esc(l.name)}${l.notes ? `<div class="small muted">${esc(l.notes)}</div>` : ''}</td><td class="num">${l.quantity}</td><td class="num">${money(l.quantity * l.unit_price)}</td>
          <td class="actions">${l.status === 'void' ? badge('cancelled', 'Removed') : l.status === 'ready' ? badge('done', 'Ready') : badge('pending', 'In the kitchen')}
            ${open && l.status !== 'void' ? ` <button class="btn sm ghost danger" data-void-line="${l.id}" title="Remove dish" aria-label="Remove dish">✕</button>` : ''}</td></tr>`).join(''), 'Nothing ordered yet')}</div>
        <div class="card-body" id="pending-box"></div>
        <div class="card-body"><dl class="kv"><dt>Subtotal</dt><dd>${money(c.subtotal)}</dd><dt>Service charge ${esc(c.service_charge_rate)}%</dt><dd>${money(c.service_charge)}</dd>
          <dt>VAT ${esc(c.vat_rate)}%</dt><dd>${money(c.vat)}</dd><dt><b>Total</b></dt><dd><b id="check-total">${money(c.total)}</b></dd></dl>
          ${open ? '<div class="btn-row" style="margin-top:12px"><button class="btn primary" id="pay">Pay</button><button class="btn" id="to-room">Charge to room</button></div>' : ''}</div></div></div>`;
  const drawPending = () => {
    $('#pending-box', el).innerHTML = pending.length ? `<b>To send to the kitchen</b>${pending.map((p, i) => `<div class="line-item"><span>${p.quantity} × ${esc(p.name)}</span>
      <span><button type="button" class="btn sm" data-less="${i}">−</button> <button type="button" class="btn sm" data-more="${i}">+</button></span></div>`).join('')}
      <label class="field" style="margin-top:8px"><span>Note for the kitchen</span><input id="kitchen-note" maxlength="200"></label>
      <button class="btn primary" id="send" style="margin-top:10px">Send to kitchen</button>` : '';
    on(el, '[data-less]', 'click', (e, b) => { const p = pending[+b.dataset.less]; if (--p.quantity < 1) pending.splice(+b.dataset.less, 1); drawPending(); });
    on(el, '[data-more]', 'click', (e, b) => { pending[+b.dataset.more].quantity += 1; drawPending(); });
    const send = $('#send', el);
    if (send) send.addEventListener('click', async () => {
      const note = $('#kitchen-note', el).value;
      const lines = pending.map((p) => ({ menu_item_id: p.id, quantity: p.quantity, notes: note }));
      if (await guarded(() => POST(`/restaurant/checks/${c.id}/lines`, { lines }), 'Sent to the kitchen')) ctx.refresh();
    });
  };
  on(el, '[data-dish]', 'click', (e, b) => {
    const dish = menu.find((m) => m.id === +b.dataset.dish);
    const have = pending.find((p) => p.id === dish.id);
    if (have) have.quantity += 1; else pending.push({ id: dish.id, name: dish.name, quantity: 1 });
    drawPending();
  });
  on(el, '[data-void-line]', 'click', async (e, b) => {
    if (await confirmBox('Remove dish', 'Take this dish off the check?', 'Remove') && await guarded(() => DEL(`/restaurant/checks/${c.id}/lines/${b.dataset.voidLine}`), 'Dish removed')) ctx.refresh();
  });
  const bind = (id, fn) => { const b = $(id, el); if (b) b.addEventListener('click', fn); };
  bind('#pay', async () => {
    const paid = await modal({ title: `Pay ${money(c.total)}`, submit: 'Take payment', body: selectField('Paid by', 'method', METHODS, 'cash'),
      onSubmit: (v) => POST(`/restaurant/checks/${c.id}/pay`, v) });
    if (paid) { toast(`Paid. Receipt ${paid.receipt_number}`, 'success'); location.hash = '#/restaurant/receipt/' + c.id; }
  });
  bind('#to-room', async () => {
    const rooms = await GET('/restaurant/in-house');
    const done = await modal({ title: 'Charge to room', submit: 'Charge to room',
      body: `${selectField('Room', 'reservation_id', rooms.map((r) => [r.reservation_id, `${r.room_number} — ${r.guest_name}`]), '')}
        <p class="small muted" style="margin-top:8px">${money(c.subtotal)} goes on the room bill; service charge and VAT are added there.</p>`,
      onSubmit: (v) => POST(`/restaurant/checks/${c.id}/charge`, v) });
    if (done) { toast('Charged to the room', 'success'); location.hash = '#/restaurant'; }
  });
  bind('#void', async () => {
    const done = await modal({ title: 'Void check', submit: 'Void check', danger: true, body: field('Reason *', 'reason'),
      onSubmit: (v) => POST(`/restaurant/checks/${c.id}/void`, v) });
    if (done) { toast('Check voided', 'success'); location.hash = '#/restaurant'; }
  });
}

// ====================================================================== printed receipt
export async function receiptView(el, { args, alive }) {
  const r = await GET(`/restaurant/checks/${args[0]}/receipt`);
  if (!alive()) return;
  const h = r.hotel;
  el.innerHTML = `<div class="no-print btn-row" style="margin-bottom:12px"><a href="#/restaurant">‹ Restaurant</a><span class="grow"></span><button class="btn primary" id="print">Print</button></div>
    <div class="invoice receipt"><div class="inv-head"><div><div class="inv-title">${esc(h.hotel_name)}</div><div class="ar">${esc(h.hotel_name_ar || '')}</div>
      <div class="muted">${esc(h.address)}<br>Tax reg. no. ${esc(h.tax_registration_number)}</div></div>
      <div class="right"><div class="inv-title">RECEIPT</div><div class="ar">إيصال</div><div class="muted">${esc(r.receipt_number)}<br>${fmtDateTime(r.closed_at)}</div></div></div>
    <p>${esc(r.table_name)} · ${r.covers} guest(s) · ${esc(r.code)}${r.closed_by_name ? ' · ' + esc(r.closed_by_name) : ''}</p>
    <table><thead><tr><th>Dish</th><th class="num">Qty</th><th class="num">Unit</th><th class="num">Amount</th></tr></thead><tbody>
      ${r.lines.filter((l) => l.status !== 'void').map((l) => `<tr><td>${esc(l.name)}</td><td class="num">${l.quantity}</td><td class="num">${money(l.unit_price)}</td><td class="num">${money(l.quantity * l.unit_price)}</td></tr>`).join('')}
      <tr><td colspan="3" class="right">Subtotal</td><td class="num">${money(r.subtotal)}</td></tr>
      <tr><td colspan="3" class="right">Service charge ${esc(r.service_charge_rate)}%</td><td class="num">${money(r.service_charge)}</td></tr>
      <tr><td colspan="3" class="right">VAT ${esc(r.vat_rate)}%</td><td class="num">${money(r.vat)}</td></tr>
      <tr class="total"><td colspan="3" class="right">Total</td><td class="num">${money(r.total)}</td></tr></tbody></table>
    <p class="small muted">Paid by ${esc((METHODS.find(([k]) => k === r.paid_method) || ['', r.paid_method])[1])}. Thank you.</p></div>`;
  $('#print', el).addEventListener('click', () => print());
}

// ====================================================================== kitchen tickets
export async function ticketsView(el, { ctx, alive }) {
  const tickets = await GET('/restaurant/tickets');
  if (!alive()) return;
  const cook = ctx.can('kitchen.orders');
  const byCheck = {};
  tickets.forEach((t) => { (byCheck[t.check_id] ||= { table: t.table_name, code: t.code, lines: [] }).lines.push(t); });
  el.innerHTML = `<div class="page-head"><div class="grow"><h1>Restaurant tickets</h1><div class="sub">Dishes ordered at the tables, oldest first. Mark each one ready and the waiter is told.</div></div></div>
    <div class="ticket-grid">${Object.values(byCheck).map((k) => `<div class="card ticket"><div class="card-head"><h2 class="grow">${esc(k.table)}</h2><span class="small muted">${minutesSince(k.lines[0].created_at)} min</span></div>
      <div class="card-body">${k.lines.map((l) => `<div class="line-item"><span><b>${l.quantity} ×</b> ${esc(l.name)}${l.notes ? `<br><span class="small text-warn">${esc(l.notes)}</span>` : ''}</span>
        ${cook ? `<button class="btn sm good" data-ready="${l.id}">Ready</button>` : ''}</div>`).join('')}</div></div>`).join('')
      || '<div class="card card-body empty">No dishes waiting.</div>'}</div>`;
  on(el, '[data-ready]', 'click', async (e, b) => { if (await guarded(() => POST(`/restaurant/tickets/${b.dataset.ready}/ready`))) ctx.refresh(); });
  void $$;
}
