// Kitchen: live order board, menu & recipes (ingredients linked to inventory), room-service ordering.
import { DEL, GET, POST, PUT } from '../core/api.js';
import { $, $$, badge, check, confirmBox, esc, field, fmtDateTime, guarded, modal, money, on, qty, selectField, table, toast } from '../core/ui.js';

const NEXT = { pending: ['preparing', 'Start cooking'], preparing: ['ready', 'Ready for delivery'], ready: ['delivered', 'Delivered'] };

export async function orderBoardView(el, { ctx, alive }) {
  const orders = await GET('/kitchen/orders');
  if (!alive()) return;
  const chef = ctx.can('kitchen.orders');
  const cols = [['pending', 'New'], ['preparing', 'Cooking'], ['ready', 'Ready']];
  const age = (s) => Math.max(0, Math.round((Date.now() - new Date(s.replace(' ', 'T'))) / 60000));
  el.innerHTML = `<div class="page-head"><div class="grow"><h1>${chef ? 'Kitchen orders' : 'Room service'}</h1>
      <div class="sub">Auto-refreshes every 30 seconds. Ingredients are deducted from stock when cooking starts; the bill is posted on delivery.</div></div>
      ${ctx.can('orders.create') ? '<button class="btn primary" id="new">+ New order</button>' : ''}<button class="btn" id="reload">Refresh</button></div>
    <div class="kanban">${cols.map(([s, t]) => {
      const list = orders.filter((o) => o.status === s);
      return `<div class="kan-col"><div class="kan-head">${badge(s, t)} <span class="muted">${list.length}</span></div>
        ${list.map((o) => `<div class="card kan-card ${age(o.created_at) > 30 && s !== 'ready' ? 'late' : ''}">
          <div class="kan-top"><b>Room ${esc(o.room_number)}</b><span class="grow"></span><span class="small muted">${age(o.created_at)} min</span></div>
          <div class="small muted">${esc(o.code)} · ${esc(o.guest_name)}${o.placed_via === 'guest' ? ' · <span class="badge b-violet plain">app</span>' : ''}</div>
          <ul class="order-lines">${o.lines.map((l) => `<li><b>${l.quantity}×</b> ${esc(l.name)}${l.notes ? ` <i class="muted">(${esc(l.notes)})</i>` : ''}</li>`).join('')}</ul>
          ${o.notes ? `<div class="task-notes">${esc(o.notes)}</div>` : ''}
          <div class="btn-row">${NEXT[s] && (chef || (s === 'ready' && ctx.can('orders.create'))) ? `<button class="btn sm primary" data-next="${o.id}" data-to="${NEXT[s][0]}">${NEXT[s][1]}</button>` : ''}
            ${(s === 'pending' || (s === 'preparing' && chef)) ? `<button class="btn sm ghost danger" data-next="${o.id}" data-to="cancelled">Cancel</button>` : ''}
            <span class="grow"></span><b>${money(o.total)}</b></div></div>`).join('') || '<div class="empty small">—</div>'}</div>`;
    }).join('')}</div>`;
  on(el, '[data-next]', 'click', async (e, b) => {
    if (b.dataset.to === 'cancelled' && !(await confirmBox('Cancel order', 'Cancel this order?', 'Cancel order'))) return;
    if (await guarded(() => POST(`/kitchen/orders/${b.dataset.next}/status`, { status: b.dataset.to }), 'Order updated')) ctx.refresh();
  });
  $('#reload', el).addEventListener('click', () => ctx.refresh());
  if ($('#new', el)) $('#new', el).addEventListener('click', () => placeOrder(ctx));
  const timer = setInterval(() => { if (!document.body.contains(el) || !alive()) clearInterval(timer); else if (!$('.modal-back')) ctx.refresh(); }, 30000);
}

async function placeOrder(ctx) {
  const [guests, menu] = await Promise.all([GET('/kitchen/in-house'), GET('/menu?available=1')]);
  if (!guests.length) { toast('No in-house guests', 'error'); return; }
  const ok = await modal({
    title: 'New room-service order', wide: true, submit: 'Send to kitchen',
    body: `<div class="stack">${selectField('Guest / room', 'reservation_id', guests.map((g) => [g.id, `Room ${g.room_number} — ${g.guest_name} (${g.code})`]), '')}
      <div class="menu-pick">${menu.map((m) => `<label class="menu-row"><span><b>${esc(m.name)}</b><span class="small muted"> ${esc(m.category)}</span></span>
        <span>${money(m.price)}</span><input type="number" min="0" max="20" value="0" name="m_${m.id}" class="qty-input"></label>`).join('')}</div>
      ${field('Notes for the kitchen', 'notes', '', 'placeholder="Allergies, no onions…"')}<div class="right"><b id="tot"></b></div></div>`,
    onOpen: (m) => {
      const upd = () => { $('#tot', m).textContent = 'Total ' + money(menu.reduce((a, x) => a + x.price * (+$(`[name=m_${x.id}]`, m).value || 0), 0)); };
      $$('.qty-input', m).forEach((i) => i.addEventListener('input', upd));
      upd();
    },
    onSubmit: (v) => {
      const lines = menu.filter((x) => +v['m_' + x.id] > 0).map((x) => ({ menu_item_id: x.id, quantity: +v['m_' + x.id] }));
      if (!lines.length) throw new Error('Choose at least one item');
      return POST('/kitchen/orders', { reservation_id: +v.reservation_id, notes: v.notes, lines });
    },
  });
  if (ok) { toast('Order sent to the kitchen', 'success'); ctx.refresh(); }
}

export async function menuView(el, { ctx, alive }) {
  const [menu, items] = await Promise.all([GET('/menu'), GET('/items/requestable').catch(() => [])]);
  if (!alive()) return;
  const manage = ctx.can('menu.manage');
  const ingredients = items.filter((i) => ['kitchen', 'minibar', 'general'].includes(i.department));
  el.innerHTML = `<div class="page-head"><div class="grow"><h1>Menu &amp; recipes</h1><div class="sub">Recipes link dishes to kitchen stock so ingredients are deducted automatically.</div></div>
      ${manage ? '<button class="btn primary" id="new">+ Dish</button>' : ''}</div>
    <div class="card">${table(['Dish', 'Category', ['Price', 'num'], 'Prep', 'Recipe', 'Available', ''], menu.map((m) => `<tr><td><b>${esc(m.name)}</b><div class="small muted">${esc(m.description)}</div></td>
      <td>${esc(m.category)}</td><td class="num">${money(m.price)}</td><td>${m.prep_minutes} min</td>
      <td class="small">${m.ingredients.map((i) => `${qty(i.quantity)} ${esc(i.unit)} ${esc(i.name)}${i.on_hand < i.quantity ? ' <span class="text-bad">(low)</span>' : ''}`).join('<br>') || '<span class="muted">—</span>'}</td>
      <td><label class="switch"><input type="checkbox" data-avail="${m.id}" ${m.available ? 'checked' : ''} ${ctx.can('kitchen.orders') ? '' : 'disabled'}><span></span></label></td>
      <td class="actions">${manage ? `<button class="btn sm" data-edit="${m.id}">Edit</button> <button class="btn sm ghost danger" data-del="${m.id}">✕</button>` : ''}</td></tr>`).join(''), 'No dishes yet')}</div>`;
  on(el, '[data-avail]', 'change', async (e, c) => { await guarded(() => POST(`/menu/${c.dataset.avail}/availability`, { available: c.checked }), c.checked ? 'Back on the menu' : 'Marked unavailable'); });
  on(el, '[data-del]', 'click', async (e, b) => { if (await confirmBox('Remove dish', 'Remove this dish from the menu?', 'Remove') && await guarded(() => DEL('/menu/' + b.dataset.del), 'Dish removed')) ctx.refresh(); });
  const form = async (m = { ingredients: [] }) => {
    const row = (ing = {}) => `<div class="ing-row">${selectField('', 'ing_item', [['', '— ingredient —']].concat(ingredients.map((i) => [i.id, `${i.name} (${i.unit})`])), ing.item_id || '')}
      <input type="number" step="any" min="0" name="ing_qty" value="${ing.quantity ?? ''}" placeholder="qty per portion"><button type="button" class="btn sm ghost danger" data-rm>✕</button></div>`;
    const ok = await modal({ title: m.id ? 'Edit dish' : 'New dish', wide: true,
      body: `<div class="form-grid">${field('Name *', 'name', m.name)}${field('Category', 'category', m.category || 'Mains', 'list="cats"')}
        ${field('Price *', 'price', m.price, 'type="number" step="0.01" min="0"')}${field('Prep time (min)', 'prep_minutes', m.prep_minutes ?? 15, 'type="number" min="0"')}
        ${field('Description', 'description', m.description, '', 'full')}${check('Available', 'available', m.id ? m.available : true)}
        <datalist id="cats">${['Breakfast', 'Starters', 'Mains', 'Desserts', 'Drinks', 'Kids'].map((c) => `<option value="${c}">`).join('')}</datalist></div>
        <div class="form-section" style="margin-top:14px">Recipe (per portion)</div><div id="ings">${m.ingredients.map(row).join('')}</div>
        <button type="button" class="btn sm" id="add-ing">+ Ingredient</button>`,
      onOpen: (box) => {
        const bindRm = () => $$('[data-rm]', box).forEach((b) => { b.onclick = () => b.closest('.ing-row').remove(); });
        $('#add-ing', box).addEventListener('click', () => { $('#ings', box).insertAdjacentHTML('beforeend', row()); bindRm(); });
        bindRm();
      },
      onSubmit: (v, box) => {
        const ings = $$('.ing-row', box).map((r) => ({ item_id: +$('[name=ing_item]', r).value, quantity: +$('[name=ing_qty]', r).value })).filter((i) => i.item_id && i.quantity > 0);
        const payload = { name: v.name, category: v.category, price: v.price, prep_minutes: v.prep_minutes, description: v.description, available: v.available, ingredients: ings };
        return m.id ? PUT('/menu/' + m.id, payload) : POST('/menu', payload);
      } });
    if (ok) { toast('Dish saved', 'success'); ctx.refresh(); }
  };
  if ($('#new', el)) $('#new', el).addEventListener('click', () => form());
  on(el, '[data-edit]', 'click', (e, b) => form(menu.find((x) => x.id === +b.dataset.edit)));
}

export async function deliveredView(el, { alive }) {
  const orders = (await GET('/kitchen/orders?all=1')).filter((o) => ['delivered', 'cancelled'].includes(o.status));
  if (!alive()) return;
  el.innerHTML = `<div class="page-head"><div class="grow"><h1>Order history</h1></div></div><div class="card">${table(['Order', 'Room', 'Items', 'Placed', 'Status', ['Total', 'num']],
    orders.map((o) => `<tr><td>${esc(o.code)}</td><td>${esc(o.room_number)}</td><td class="small">${o.lines.map((l) => `${l.quantity}× ${esc(l.name)}`).join(', ')}</td>
    <td class="small">${fmtDateTime(o.created_at)}</td><td>${badge(o.status)}</td><td class="num">${money(o.total)}</td></tr>`).join(''), 'No orders yet')}</div>`;
}
