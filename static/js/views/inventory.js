// Inventory: items, stock ledger, suppliers, purchase orders, supply requests (store + departments).
import { DEL, GET, POST, PUT, qs } from '../core/api.js';
import {
  $, $$, PAGE_SIZE, badge, bindPager, bindRowLinks, check, confirmBox, esc, field, fmtDate, fmtDateTime, guarded, label, modal, money, on,
  options, pager, qty, selectField, table, textField, tile, toast,
} from '../core/ui.js';

const DEPTS = [['general', 'General'], ['housekeeping', 'Housekeeping'], ['kitchen', 'Kitchen'], ['minibar', 'Minibar'], ['maintenance', 'Maintenance'], ['front_office', 'Front office']];

export async function inventoryView(el, { params, ctx, alive }) {
  const tab = params.tab || 'items';
  const tabs = [['items', 'Items', 'inventory.view'], ['movements', 'Stock ledger', 'inventory.view'], ['requests', 'Supply requests', 'inventory.view'],
    ['purchasing', 'Purchase orders', 'purchasing.manage'], ['suppliers', 'Suppliers', 'inventory.view']].filter((t) => ctx.can(t[2]));
  el.innerHTML = `<div class="page-head"><div class="grow"><h1>Inventory</h1><div class="sub">Stock levels, purchasing and department supplies.</div></div>
      <div class="btn-row" id="actions"></div></div>
    <div class="tabs">${tabs.map(([k, t]) => `<button data-tab="${k}" class="${tab === k ? 'active' : ''}">${t}</button>`).join('')}</div><div id="body"></div>`;
  on(el, '[data-tab]', 'click', (e, b) => { location.hash = '#/inventory?tab=' + b.dataset.tab; });
  const body = $('#body', el);
  const actions = $('#actions', el);
  const views = { items: itemsTab, movements: movementsTab, requests: requestsTab, purchasing: purchasingTab, suppliers: suppliersTab };
  await (views[tab] || itemsTab)(body, actions, ctx, params, alive);
}

async function itemsTab(body, actions, ctx, params, alive) {
  const all = await GET('/items?include_inactive=1');
  if (!alive()) return;
  const cats = [...new Set(all.map((i) => i.category))].sort();
  const manage = ctx.can('inventory.manage');
  actions.innerHTML = `<a class="btn" href="/api/export/items">Export CSV</a>${manage ? '<button class="btn primary" id="new">+ New item</button>' : ''}`;
  body.innerHTML = `<div class="toolbar"><input type="search" id="q" placeholder="Name or SKU…">
      <select id="dept">${options([['', 'All departments']].concat(DEPTS))}</select><select id="cat">${options([['', 'All categories']].concat(cats))}</select>
      <label class="check"><input type="checkbox" id="low" ${params.low ? 'checked' : ''}> Low stock</label><label class="check"><input type="checkbox" id="inactive"> Inactive</label>
      <span class="grow"></span><span class="small muted" id="sum"></span></div><div class="card" id="list"></div>`;
  const draw = () => {
    const q = $('#q').value.trim().toLowerCase();
    const list = all.filter((i) => ($('#inactive').checked || i.active) && (!$('#dept').value || i.department === $('#dept').value)
      && (!$('#cat').value || i.category === $('#cat').value) && (!$('#low').checked || i.low_stock)
      && (!q || i.name.toLowerCase().includes(q) || i.sku.toLowerCase().includes(q)));
    $('#sum').textContent = `${list.length} items · value ${money(list.reduce((a, i) => a + i.stock_value, 0))}`;
    $('#list').innerHTML = table(['SKU', 'Item', 'Department', ['On hand', 'num'], ['Reorder at', 'num'], ['Avg cost', 'num'], ['Sale price', 'num'], ['Value', 'num'], ''],
      list.map((i) => `<tr class="clickable" data-href="#/inventory/${i.id}"><td><b>${esc(i.sku)}</b></td>
        <td>${esc(i.name)} ${i.chargeable ? '<span class="badge b-info plain">Chargeable</span>' : ''}${i.active ? '' : ' <span class="badge plain">Inactive</span>'}<div class="small muted">${esc(i.category)} · ${esc(i.supplier_name || 'no supplier')}</div></td>
        <td>${esc(label(i.department))}</td><td class="num">${i.low_stock ? '<span class="badge b-bad">Low</span> ' : ''}<b>${qty(i.quantity)}</b> ${esc(i.unit)}</td>
        <td class="num">${qty(i.reorder_level)}</td><td class="num">${money(i.cost)}</td><td class="num">${i.chargeable ? money(i.price) : '—'}</td><td class="num">${money(i.stock_value)}</td>
        <td class="actions">${manage ? `<button class="btn sm" data-m="receive" data-id="${i.id}">Receive</button> <button class="btn sm" data-m="adjust" data-id="${i.id}">Count</button>` : ''}
          ${ctx.can('inventory.approve') ? `<button class="btn sm" data-m="issue" data-id="${i.id}">Issue</button>` : ''}</td></tr>`).join(''), 'No items match');
    bindRowLinks(body);
    on(body, '[data-m]', 'click', (e, b) => stockMove(all.find((i) => i.id === +b.dataset.id), b.dataset.m, ctx.refresh));
  };
  ['#q', '#dept', '#cat', '#low', '#inactive'].forEach((s) => $(s).addEventListener('input', draw));
  if ($('#new')) $('#new').addEventListener('click', async () => { if (await itemForm()) ctx.refresh(); });
  draw();
}

async function movementsTab(body, actions, ctx, params, alive) {
  actions.innerHTML = '<a class="btn" id="exp" href="/api/export/movements">Export CSV</a>';
  body.innerHTML = `<div class="toolbar"><select id="kind">${options([['', 'All movements'], ['receive', 'Received'], ['issue', 'Issued to departments'], ['consume', 'Kitchen consumption'],
    ['sale', 'Guest sales'], ['return', 'Returns'], ['adjust', 'Count adjustments']])}</select><label class="check small">From <input type="date" id="from"></label>
    <label class="check small">To <input type="date" id="to"></label></div><div class="card" id="list"></div>`;
  const load = async (page = 1) => {
    const f = { kind: $('#kind').value, from: $('#from').value, to: $('#to').value };
    $('#exp').href = '/api/export/movements?' + qs({ from: f.from, to: f.to });
    const found = await GET('/movements?' + qs({ ...f, page, per_page: PAGE_SIZE }));
    if (!alive()) return;
    $('#list').innerHTML = movementTable(found.items, true) + pager(found);
    bindPager(body, load);
  };
  ['#kind', '#from', '#to'].forEach((s) => $(s).addEventListener('change', () => load()));
  await load();
}

export function movementTable(list, withItem) {
  return table(['Date'].concat(withItem ? ['Item'] : []).concat(['Type', ['Change', 'num'], ['Balance', 'num'], 'Reason', 'Ref.', 'By']), list.map((m) => `<tr>
    <td class="nowrap small">${fmtDateTime(m.created_at)}</td>${withItem ? `<td><a href="#/inventory/${m.item_id}">${esc(m.item_name)}</a></td>` : ''}
    <td>${badge(m.kind)}</td><td class="num ${m.change < 0 ? 'text-bad' : 'text-good'}">${m.change > 0 ? '+' : ''}${qty(m.change)}</td><td class="num">${qty(m.balance_after)}</td>
    <td>${esc(m.reason)}</td><td class="small">${m.reservation_code ? `<a href="#/reservations/${m.reservation_id}">${esc(m.reservation_code)}</a>` : esc(m.reference)}</td>
    <td class="small">${esc(m.user_name || '')}</td></tr>`).join(''), 'No stock movements');
}

async function suppliersTab(body, actions, ctx, params, alive) {
  const list = await GET('/suppliers');
  if (!alive()) return;
  const manage = ctx.can('purchasing.manage');
  actions.innerHTML = manage ? '<button class="btn primary" id="new">+ Supplier</button>' : '';
  body.innerHTML = `<div class="card">${table(['Name', 'Contact', 'Phone', 'E-mail', ['Items', 'num'], ''], list.map((s) => `<tr><td><b>${esc(s.name)}</b>${s.active ? '' : ' <span class="badge plain">Inactive</span>'}</td>
    <td>${esc(s.contact)}</td><td>${esc(s.phone)}</td><td>${esc(s.email)}</td><td class="num">${s.item_count}</td>
    <td class="actions">${manage ? `<button class="btn sm" data-po="${s.id}">Reorder low stock</button> <button class="btn sm" data-edit="${s.id}">Edit</button>` : ''}</td></tr>`).join(''), 'No suppliers')}</div>`;
  const form = async (s = {}) => {
    const ok = await modal({ title: s.id ? 'Edit supplier' : 'New supplier',
      body: `<div class="form-grid">${field('Name *', 'name', s.name, '', 'full')}${field('Contact', 'contact', s.contact)}${field('Phone', 'phone', s.phone)}
        ${field('E-mail', 'email', s.email, 'type="email"', 'full')}${check('Active', 'active', s.id ? s.active : true)}</div>`,
      onSubmit: (v) => (s.id ? PUT('/suppliers/' + s.id, v) : POST('/suppliers', v)) });
    if (ok) { toast('Supplier saved', 'success'); ctx.refresh(); }
  };
  if ($('#new')) $('#new').addEventListener('click', () => form());
  on(body, '[data-edit]', 'click', (e, b) => form(list.find((x) => x.id === +b.dataset.edit)));
  on(body, '[data-po]', 'click', async (e, b) => {
    const po = await guarded(() => POST('/purchase-orders/from-low-stock', { supplier_id: +b.dataset.po }));
    if (po) { toast(`Draft ${po.code} created`, 'success'); location.hash = '#/inventory?tab=purchasing'; }
  });
}

async function purchasingTab(body, actions, ctx, params, alive) {
  const [pos, suppliers, items] = await Promise.all([GET('/purchase-orders'), GET('/suppliers'), GET('/items')]);
  if (!alive()) return;
  actions.innerHTML = '<button class="btn primary" id="new">+ Purchase order</button>';
  body.innerHTML = `<div class="card">${table(['PO', 'Supplier', 'Status', 'Lines', ['Total', 'num'], 'Created', 'Expected', ''], pos.map((p) => `<tr>
    <td><b>${esc(p.code)}</b></td><td>${esc(p.supplier_name)}</td><td>${badge(p.status)}</td><td>${p.line_count}</td><td class="num">${money(p.total)}</td>
    <td class="small">${fmtDate(p.created_at)}</td><td class="small">${p.expected_date ? fmtDate(p.expected_date) : '—'}</td>
    <td class="actions"><button class="btn sm" data-view="${p.id}">Open</button></td></tr>`).join(''), 'No purchase orders')}</div>`;
  const editor = async (po = { lines: [] }) => {
    const row = (l = {}) => `<div class="ing-row">${selectField('', 'item', [['', '— item —']].concat(items.map((i) => [i.id, `${i.sku} ${i.name} (${i.unit})`])), l.item_id || '')}
      <input type="number" step="any" min="0" name="q" value="${l.quantity ?? ''}" placeholder="qty"><input type="number" step="0.01" min="0" name="c" value="${l.unit_cost ?? ''}" placeholder="unit cost">
      <button type="button" class="btn sm ghost danger" data-rm>✕</button></div>`;
    return modal({ title: po.id ? `Edit ${po.code}` : 'New purchase order', wide: true,
      body: `<div class="form-grid">${selectField('Supplier', 'supplier_id', suppliers.map((s) => [s.id, s.name]), po.supplier_id)}${field('Expected delivery', 'expected_date', po.expected_date || '', 'type="date"')}
        ${field('Notes', 'notes', po.notes, '', 'full')}</div><div class="form-section" style="margin-top:12px">Lines</div><div id="lines">${(po.lines.length ? po.lines : [{}]).map(row).join('')}</div>
        <button type="button" class="btn sm" id="add">+ Line</button>`,
      onOpen: (m) => {
        const bind = () => $$('[data-rm]', m).forEach((b) => { b.onclick = () => b.closest('.ing-row').remove(); });
        $('#add', m).addEventListener('click', () => { $('#lines', m).insertAdjacentHTML('beforeend', row()); bind(); });
        bind();
      },
      onSubmit: (v, m) => {
        const lines = $$('.ing-row', m).map((r) => ({ item_id: +$('[name=item]', r).value, quantity: +$('[name=q]', r).value, unit_cost: $('[name=c]', r).value === '' ? null : +$('[name=c]', r).value }))
          .filter((l) => l.item_id && l.quantity > 0);
        const payload = { supplier_id: +v.supplier_id, expected_date: v.expected_date || null, notes: v.notes, lines };
        return po.id ? PUT('/purchase-orders/' + po.id, payload) : POST('/purchase-orders', payload);
      } });
  };
  $('#new').addEventListener('click', async () => { if (await editor()) { toast('Purchase order saved', 'success'); ctx.refresh(); } });
  on(body, '[data-view]', 'click', async (e, b) => {
    const po = await GET('/purchase-orders/' + b.dataset.view);
    const next = { draft: [['ordered', 'Mark as ordered'], ['cancelled', 'Cancel']], ordered: [['received', 'Receive into stock'], ['cancelled', 'Cancel']] }[po.status] || [];
    let choice = null;
    await modal({ title: `${po.code} — ${po.supplier_name}`, wide: true, cancel: 'Close',
      body: `<p>${badge(po.status)} ${po.notes ? esc(po.notes) : ''}</p>${table(['Item', ['Qty', 'num'], ['Unit cost', 'num'], ['Amount', 'num']], po.lines.map((l) => `<tr><td>${esc(l.sku)} ${esc(l.item_name)}</td>
        <td class="num">${qty(l.quantity)} ${esc(l.unit)}</td><td class="num">${money(l.unit_cost)}</td><td class="num">${money(l.amount)}</td></tr>`).join('')
        + `<tr class="total"><td colspan="3" class="right">Total</td><td class="num">${money(po.total)}</td></tr>`)}
        <div class="btn-row" style="margin-top:12px">${po.status === 'draft' ? '<button type="button" class="btn" data-act="edit">Edit</button>' : ''}
          ${next.map(([s, t]) => `<button type="button" class="btn ${s === 'cancelled' ? 'danger' : 'primary'}" data-act="${s}">${t}</button>`).join('')}</div>`,
      onOpen: (m) => $$('[data-act]', m).forEach((x) => x.addEventListener('click', () => { choice = x.dataset.act; $('[data-close]', m).click(); })),
    });
    if (!choice) return;
    if (choice === 'edit') {
      if (await editor(po)) { toast('Purchase order saved', 'success'); ctx.refresh(); }
    } else if (await guarded(() => POST(`/purchase-orders/${po.id}/status`, { status: choice }), choice === 'received' ? 'Stock received' : 'Order updated')) ctx.refresh();
  });
}

async function requestsTab(body, actions, ctx, params, alive) {
  const list = await GET('/stock-requests');
  if (!alive()) return;
  const approver = ctx.can('inventory.approve');
  actions.innerHTML = ctx.can('inventory.request') ? '<button class="btn primary" id="new">+ Request supplies</button>' : '';
  body.innerHTML = `<div class="card">${requestTable(list, approver)}</div>`;
  bindRequestActions(body, ctx, list);
  if ($('#new')) $('#new').addEventListener('click', () => newSupplyRequest(ctx));
}

function requestTable(list, approver) {
  return table(['Request', 'Department', 'Requested by', 'Items', 'Status', ''], list.map((r) => `<tr><td><b>${esc(r.code)}</b><div class="small muted">${fmtDateTime(r.created_at)}</div></td>
    <td>${esc(label(r.department))}</td><td>${esc(r.requested_by_name)}</td>
    <td class="small">${r.lines.map((l) => `${qty(l.quantity)} ${esc(l.unit)} ${esc(l.item_name)}${approver && l.on_hand < l.quantity ? ' <span class="text-bad">(only ' + qty(l.on_hand) + ')</span>' : ''}`).join('<br>')}
      ${r.notes ? `<div class="muted">${esc(r.notes)}</div>` : ''}${r.response ? `<div class="text-good">↳ ${esc(r.response)}</div>` : ''}</td><td>${badge(r.status)}</td>
    <td class="actions">${r.status === 'pending' && approver ? `<button class="btn sm good" data-ok="${r.id}">Issue</button> <button class="btn sm" data-no="${r.id}">Reject</button>` : ''}
      ${r.status === 'pending' && !approver ? `<button class="btn sm ghost" data-cancel="${r.id}">Cancel</button>` : ''}</td></tr>`).join(''), 'No supply requests');
}

function bindRequestActions(body, ctx) {
  on(body, '[data-ok]', 'click', async (e, b) => { if (await guarded(() => POST(`/stock-requests/${b.dataset.ok}/decide`, { approve: true }), 'Supplies issued')) ctx.refresh(); });
  on(body, '[data-no]', 'click', async (e, b) => {
    const v = await modal({ title: 'Reject request', submit: 'Reject', danger: true, body: field('Reason', 'response'), onSubmit: async (x) => x });
    if (v && await guarded(() => POST(`/stock-requests/${b.dataset.no}/decide`, { approve: false, response: v.response }), 'Request rejected')) ctx.refresh();
  });
  on(body, '[data-cancel]', 'click', async (e, b) => { if (await guarded(() => POST(`/stock-requests/${b.dataset.cancel}/cancel`), 'Request cancelled')) ctx.refresh(); });
}

export async function newSupplyRequest(ctx, department) {
  const items = await GET('/items/requestable');
  const dept = department || { chef: 'kitchen', housekeeper: 'housekeeping' }[ctx.user.role] || 'front_office';
  const relevant = items.filter((i) => i.department === dept || dept === 'front_office' || i.department === 'general');
  const row = () => `<div class="ing-row">${selectField('', 'item', [['', '— item —']].concat((relevant.length ? relevant : items).map((i) => [i.id, `${i.name} (${i.unit})`])), '')}
    <input type="number" step="any" min="0" name="q" placeholder="quantity"><button type="button" class="btn sm ghost danger" data-rm>✕</button></div>`;
  const ok = await modal({ title: 'Request supplies from the store', wide: true, submit: 'Send request',
    body: `${selectField('Department', 'department', DEPTS, dept)}<div class="form-section" style="margin-top:12px">Items</div><div id="lines">${row()}${row()}</div>
      <button type="button" class="btn sm" id="add">+ Item</button>${textField('Notes', 'notes')}`,
    onOpen: (m) => {
      const bind = () => $$('[data-rm]', m).forEach((b) => { b.onclick = () => b.closest('.ing-row').remove(); });
      $('#add', m).addEventListener('click', () => { $('#lines', m).insertAdjacentHTML('beforeend', row()); bind(); });
      bind();
    },
    onSubmit: (v, m) => {
      const lines = $$('.ing-row', m).map((r) => ({ item_id: +$('[name=item]', r).value, quantity: +$('[name=q]', r).value })).filter((l) => l.item_id && l.quantity > 0);
      if (!lines.length) throw new Error('Add at least one item with a quantity');
      return POST('/stock-requests', { department: v.department, notes: v.notes, lines });
    } });
  if (ok) { toast(`Request ${ok.code} sent to the store`, 'success'); ctx.refresh(); }
}

/** "My supply requests" for chefs, housekeepers and front-desk staff. */
export async function mySuppliesView(el, { ctx, alive }) {
  const list = await GET('/stock-requests?mine=1');
  if (!alive()) return;
  el.innerHTML = `<div class="page-head"><div class="grow"><h1>Supplies</h1><div class="sub">Request items from the store and track your requests.</div></div>
    <button class="btn primary" id="new">+ Request supplies</button></div><div class="card">${requestTable(list, false)}</div>`;
  bindRequestActions(el, ctx, list);
  $('#new', el).addEventListener('click', () => newSupplyRequest(ctx));
}

export async function itemView(el, { args, ctx, alive }) {
  const i = await GET('/items/' + args[0]);
  if (!alive()) return;
  const manage = ctx.can('inventory.manage');
  el.innerHTML = `<div class="page-head"><div class="grow"><a class="small" href="#/inventory">‹ Inventory</a><h1>${esc(i.name)}</h1>
      <div class="sub">${esc(i.sku)} · ${esc(i.category)} · ${esc(label(i.department))}${i.active ? '' : ' · <b>inactive</b>'}</div></div>
      <div class="btn-row">${manage ? '<button class="btn" data-m="receive">Receive</button><button class="btn" data-m="adjust">Count</button>' : ''}
      ${ctx.can('inventory.approve') ? '<button class="btn" data-m="issue">Issue</button>' : ''}
      ${manage ? '<button class="btn" id="edit">Edit</button><button class="btn danger" id="del">Delete</button>' : ''}</div></div>
    <div class="tiles">${tile('On hand', `${qty(i.quantity)} ${i.unit}`, i.low_stock ? 'Below reorder level' : `Reorder at ${qty(i.reorder_level)}`)}
      ${tile('Average cost', money(i.cost), 'weighted')}${tile('Sale price', i.chargeable ? money(i.price) : '—', i.chargeable ? 'chargeable to guests' : 'internal use')}
      ${tile('Stock value', money(i.stock_value), i.supplier_name || 'no supplier')}</div>
    <div class="card"><div class="card-head"><h2>Movement history</h2></div>${movementTable(i.movements, false)}</div>`;
  on(el, '[data-m]', 'click', (e, b) => stockMove(i, b.dataset.m, ctx.refresh));
  if ($('#edit', el)) $('#edit', el).addEventListener('click', async () => { if (await itemForm(i)) ctx.refresh(); });
  if ($('#del', el)) $('#del', el).addEventListener('click', async () => {
    if (!(await confirmBox('Delete item', `Delete ${esc(i.name)}? Items with history are deactivated instead.`, 'Delete'))) return;
    const r = await guarded(() => DEL('/items/' + i.id));
    if (r) { toast(r.deactivated ? 'Item deactivated' : 'Item deleted', 'success'); location.hash = '#/inventory'; }
  });
}

async function itemForm(i = {}) {
  const suppliers = await GET('/suppliers');
  const res = await modal({ title: i.id ? 'Edit ' + i.name : 'New item', wide: true,
    body: `<div class="form-grid">${field('SKU *', 'sku', i.sku, 'style="text-transform:uppercase"')}${field('Name *', 'name', i.name)}
      ${selectField('Department', 'department', DEPTS, i.department || 'general')}${field('Category', 'category', i.category || 'General')}
      ${field('Unit', 'unit', i.unit || 'pcs')}${i.id ? '' : field('Opening quantity', 'quantity', 0, 'type="number" step="any" min="0"')}
      ${field('Reorder level', 'reorder_level', i.reorder_level ?? 0, 'type="number" step="any" min="0"')}${field('Unit cost', 'cost', i.cost ?? 0, 'type="number" step="0.01" min="0"')}
      ${field('Sale price to guests', 'price', i.price ?? 0, 'type="number" step="0.01" min="0"')}
      ${selectField('Supplier', 'supplier_id', [['', '— None —']].concat(suppliers.map((s) => [s.id, s.name])), i.supplier_id || '')}
      ${check('Can be charged to guest folios', 'chargeable', i.chargeable)}${check('Active', 'active', i.id ? i.active : true)}</div>`,
    onSubmit: (v) => { v.supplier_id = v.supplier_id || null; return i.id ? PUT('/items/' + i.id, v) : POST('/items', v); } });
  if (res) toast('Item saved', 'success');
  return res;
}

async function stockMove(item, kind, after) {
  const titles = { receive: 'Receive stock', issue: 'Issue stock', adjust: 'Stock count' };
  const bodies = {
    receive: `${field(`Quantity received (${item.unit}) *`, 'quantity', '', 'type="number" step="any" min="0"')}${field('Unit cost', 'unit_cost', item.cost, 'type="number" step="0.01" min="0"')}
      ${field('Delivery note / reference', 'reason', '', '', 'full')}`,
    issue: `${field(`Quantity (${item.unit}) *`, 'quantity', '', 'type="number" step="any" min="0"')}${field('Issued to / reason', 'reason')}`,
    adjust: `${field(`Counted quantity (${item.unit}) *`, 'counted', item.quantity, 'type="number" step="any" min="0"')}${field('Reason *', 'reason', '', 'placeholder="Monthly count, breakage…"')}`,
  };
  const ok = await modal({ title: `${titles[kind]} — ${item.name}`, submit: titles[kind],
    body: `<div class="notice" style="margin-bottom:12px">On hand: <b>${qty(item.quantity)} ${esc(item.unit)}</b></div><div class="form-grid">${bodies[kind]}</div>`,
    onSubmit: (v) => POST(`/items/${item.id}/movements`, Object.assign({ kind }, v)) });
  if (ok) { toast('Stock updated', 'success'); after(); }
}
