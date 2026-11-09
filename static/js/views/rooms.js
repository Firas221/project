// Rooms, room types & rates, seasonal pricing and promo codes.
import { DEL, GET, POST, PUT } from '../core/api.js';
import { $, badge, check, confirmBox, esc, field, fmtDate, guarded, modal, money, on, selectField, table, toast } from '../core/ui.js';

export async function roomsView(el, { params, ctx, alive }) {
  const tab = params.tab || 'rooms';
  const admin = ctx.can('rooms.manage');
  const tabs = [['rooms', 'Rooms'], ['types', 'Room types & rates'], ['pricing', 'Seasons & promotions']];
  el.innerHTML = `<div class="page-head"><div class="grow"><h1>Rooms &amp; rates</h1></div><div class="btn-row" id="actions"></div></div>
    <div class="tabs">${tabs.map(([k, t]) => `<button data-tab="${k}" class="${tab === k ? 'active' : ''}">${t}</button>`).join('')}</div><div id="body"></div>`;
  on(el, '[data-tab]', 'click', (e, b) => { location.hash = '#/rooms?tab=' + b.dataset.tab; });
  const body = $('#body', el);
  const actions = $('#actions', el);
  const types = await GET('/room-types');
  if (!alive()) return;
  if (tab === 'rooms') {
    const rooms = await GET('/rooms');
    if (admin) actions.innerHTML = '<button class="btn primary" id="add">+ New room</button>';
    body.innerHTML = `<div class="card">${table(['Room', 'Floor', 'Type', ['From', 'num'], 'Status', 'Occupancy', 'Notes', ''], rooms.map((r) => `
      <tr><td><b>${esc(r.number)}</b></td><td>${r.floor}</td><td>${esc(r.type_name)}</td><td class="num">${money(r.base_rate)}</td><td>${badge(r.status)}</td>
      <td>${r.occupied ? `<a href="#/reservations/${r.current_reservation_id}">${esc(r.current_guest)}</a><div class="small muted">until ${fmtDate(r.current_check_out)}</div>` : '<span class="muted">Vacant</span>'}</td>
      <td class="small muted">${esc(r.notes)}</td><td class="actions">${admin ? `<button class="btn sm" data-edit="${r.id}">Edit</button> <button class="btn sm ghost danger" data-del="${r.id}">✕</button>` : ''}</td></tr>`).join(''))}</div>`;
    const form = async (r = {}) => {
      const ok = await modal({ title: r.id ? 'Edit room ' + r.number : 'New room',
        body: `<div class="form-grid">${field('Room number *', 'number', r.number)}${field('Floor', 'floor', r.floor ?? 1, 'type="number"')}
          ${selectField('Room type *', 'type_id', types.map((t) => [t.id, t.name]), r.type_id)}
          ${selectField('Status', 'status', [['clean', 'Clean'], ['inspected', 'Inspected'], ['dirty', 'Dirty'], ['maintenance', 'Out of order']], r.status || 'clean')}
          ${field('Notes', 'notes', r.notes, '', 'full')}</div>`,
        onSubmit: (v) => (r.id ? PUT('/rooms/' + r.id, v) : POST('/rooms', v)) });
      if (ok) { toast('Room saved', 'success'); ctx.refresh(); }
    };
    if ($('#add')) $('#add').addEventListener('click', () => form());
    on(body, '[data-edit]', 'click', (e, b) => form(rooms.find((x) => x.id === +b.dataset.edit)));
    on(body, '[data-del]', 'click', async (e, b) => {
      if (await confirmBox('Delete room', 'Delete this room?', 'Delete') && await guarded(() => DEL('/rooms/' + b.dataset.del), 'Room deleted')) ctx.refresh();
    });
  } else if (tab === 'types') {
    if (admin) actions.innerHTML = '<button class="btn primary" id="add">+ New room type</button>';
    body.innerHTML = `<div class="card">${table(['Name', 'Bed', ['Size', 'num'], ['Guests', 'num'], ['Base rate / night', 'num'], ['Rooms', 'num'], 'Status', ''], types.map((t) => `
      <tr><td><b>${esc(t.name)}</b><div class="small muted">${esc(t.amenities)}</div></td><td>${esc(t.bed_type)}</td><td class="num">${t.size_sqm || '—'} m²</td>
      <td class="num">${t.capacity}</td><td class="num">${money(t.base_rate)}</td><td class="num">${t.room_count}</td><td>${t.active ? badge('clean', 'Selling') : badge('closed', 'Hidden')}</td>
      <td class="actions">${admin ? `<button class="btn sm" data-photos="${t.id}">Photos (${t.photos.length})</button> <button class="btn sm" data-edit="${t.id}">Edit</button>
        <button class="btn sm ghost danger" data-del-type="${t.id}" title="Delete room type" aria-label="Delete room type">✕</button>` : ''}</td></tr>`).join(''))}</div>
      <p class="small muted">Rates exclude ${esc(ctx.settings.service_charge_rate)}% service charge and ${esc(ctx.settings.vat_rate)}% VAT. Seasonal and weekend adjustments are applied automatically.</p>`;
    const form = async (t = {}) => {
      const ok = await modal({ title: t.id ? 'Edit room type' : 'New room type',
        body: `<div class="form-grid">${field('Name *', 'name', t.name, '', 'full')}${field('Base rate / night *', 'base_rate', t.base_rate, 'type="number" step="0.01" min="0"')}
          ${field('Max guests *', 'capacity', t.capacity || 2, 'type="number" min="1"')}${field('Bed type', 'bed_type', t.bed_type)}${field('Size (m²)', 'size_sqm', t.size_sqm || '', 'type="number" min="0"')}
          ${field('Description', 'description', t.description, '', 'full')}${field('Amenities', 'amenities', t.amenities, '', 'full')}${check('Available for sale', 'active', t.id ? t.active : true)}</div>`,
        onSubmit: (v) => (t.id ? PUT('/room-types/' + t.id, v) : POST('/room-types', v)) });
      if (ok) { toast('Room type saved', 'success'); ctx.refresh(); }
    };
    if ($('#add')) $('#add').addEventListener('click', () => form());
    on(body, '[data-edit]', 'click', (e, b) => form(types.find((x) => x.id === +b.dataset.edit)));
    on(body, '[data-photos]', 'click', async (e, b) => { await photosDialog(types.find((x) => x.id === +b.dataset.photos)); ctx.refresh(); });
    on(body, '[data-del-type]', 'click', async (e, b) => {
      if (await confirmBox('Delete room type', 'Delete this room type and its photos? Room types that still have rooms cannot be deleted.', 'Delete')
        && await guarded(() => DEL('/room-types/' + b.dataset.delType), 'Room type deleted')) ctx.refresh();
    });
  } else {
    const [seasons, promos] = await Promise.all([GET('/seasons'), admin ? GET('/promos') : []]);
    if (admin) actions.innerHTML = '<button class="btn" id="add-promo">+ Promo code</button><button class="btn primary" id="add-season">+ Season</button>';
    body.innerHTML = `<div class="grid g2"><div class="card"><div class="card-head"><h2>Seasons</h2></div>${table(['Season', 'Dates', 'Applies to', ['Adjust', 'num'], 'Min stay', ''],
      seasons.map((s) => `<tr><td><b>${esc(s.name)}</b> ${s.active ? '' : badge('closed', 'Off')}</td><td class="nowrap">${fmtDate(s.start_date)} – ${fmtDate(s.end_date)}</td>
        <td>${esc(s.room_type_name || 'All room types')}</td><td class="num ${s.adjust_pct < 0 ? 'text-good' : ''}">${s.adjust_pct > 0 ? '+' : ''}${s.adjust_pct}%</td>
        <td>${s.min_nights} night(s)</td><td class="actions">${admin ? `<button class="btn sm" data-season="${s.id}">Edit</button>
          <button class="btn sm ghost danger" data-del-season="${s.id}" title="Delete season" aria-label="Delete season">✕</button>` : ''}</td></tr>`).join(''), 'No seasons defined')}
      <div class="card-body small muted">Weekend (${esc(ctx.settings.weekend_days || 'Fri, Sat')}) uplift is set in Settings.</div></div>
      ${admin ? `<div class="card"><div class="card-head"><h2>Promo codes</h2></div>${table(['Code', 'Discount', 'Valid', 'Uses', ''], promos.map((p) => `
        <tr><td><b>${esc(p.code)}</b><div class="small muted">${esc(p.description)}</div></td><td>${p.discount_pct}%${p.online_only ? ' <span class="badge plain">online</span>' : ''}</td>
        <td class="nowrap small">${fmtDate(p.valid_from)} – ${fmtDate(p.valid_to)}</td><td>${p.used_count}${p.max_uses ? '/' + p.max_uses : ''}</td>
        <td class="actions"><button class="btn sm" data-promo="${p.id}">Edit</button>
          <button class="btn sm ghost danger" data-del-promo="${p.id}" title="Delete promo code" aria-label="Delete promo code">✕</button></td></tr>`).join(''), 'No promo codes')}</div>` : ''}</div>`;
    const seasonForm = async (s = {}) => {
      const ok = await modal({ title: s.id ? 'Edit season' : 'New season',
        body: `<div class="form-grid">${field('Name *', 'name', s.name, '', 'full')}${field('Start *', 'start_date', s.start_date, 'type="date"')}${field('End *', 'end_date', s.end_date, 'type="date"')}
          ${field('Rate adjustment % (e.g. 25 or -15)', 'adjust_pct', s.adjust_pct ?? 0, 'type="number" step="0.5"')}${field('Minimum stay (nights)', 'min_nights', s.min_nights || 1, 'type="number" min="1"')}
          ${selectField('Room type', 'room_type_id', [['', 'All room types']].concat(types.map((t) => [t.id, t.name])), s.room_type_id || '')}${check('Active', 'active', s.id ? s.active : true)}</div>`,
        onSubmit: (v) => { v.room_type_id = v.room_type_id || null; return s.id ? PUT('/seasons/' + s.id, v) : POST('/seasons', v); } });
      if (ok) { toast('Season saved', 'success'); ctx.refresh(); }
    };
    const promoForm = async (p = {}) => {
      const ok = await modal({ title: p.id ? 'Edit promo code' : 'New promo code',
        body: `<div class="form-grid">${field('Code *', 'code', p.code, 'style="text-transform:uppercase"')}${field('Discount % *', 'discount_pct', p.discount_pct, 'type="number" step="0.5" min="0.5" max="100"')}
          ${field('Valid from *', 'valid_from', p.valid_from, 'type="date"')}${field('Valid to *', 'valid_to', p.valid_to, 'type="date"')}
          ${field('Max uses (0 = unlimited)', 'max_uses', p.max_uses ?? 0, 'type="number" min="0"')}${field('Description', 'description', p.description)}
          ${check('Online bookings only', 'online_only', p.online_only)}${check('Active', 'active', p.id ? p.active : true)}</div>`,
        onSubmit: (v) => (p.id ? PUT('/promos/' + p.id, v) : POST('/promos', v)) });
      if (ok) { toast('Promo code saved', 'success'); ctx.refresh(); }
    };
    if ($('#add-season')) $('#add-season').addEventListener('click', () => seasonForm());
    if ($('#add-promo')) $('#add-promo').addEventListener('click', () => promoForm());
    on(body, '[data-season]', 'click', (e, b) => seasonForm(seasons.find((x) => x.id === +b.dataset.season)));
    on(body, '[data-promo]', 'click', (e, b) => promoForm(promos.find((x) => x.id === +b.dataset.promo)));
    on(body, '[data-del-season]', 'click', async (e, b) => {
      if (await confirmBox('Delete season', 'Delete this season? Rates on those dates go back to the base rate.', 'Delete')
        && await guarded(() => DEL('/seasons/' + b.dataset.delSeason), 'Season deleted')) ctx.refresh();
    });
    on(body, '[data-del-promo]', 'click', async (e, b) => {
      if (await confirmBox('Delete promo code', 'Delete this promo code? Bookings already made with it keep their price.', 'Delete')
        && await guarded(() => DEL('/promos/' + b.dataset.delPromo), 'Promo code deleted')) ctx.refresh();
    });
  }
}

// ------------------------------------------------------------------ room-type photos
const PHOTO_MAX_EDGE = 1600;

/** Shrinks a picture in the browser (longest edge 1600 px, JPEG) so uploads stay small and fast. */
async function shrinkImage(file) {
  const img = await createImageBitmap(file);
  const scale = Math.min(1, PHOTO_MAX_EDGE / Math.max(img.width, img.height));
  const canvas = document.createElement('canvas');
  canvas.width = Math.round(img.width * scale);
  canvas.height = Math.round(img.height * scale);
  canvas.getContext('2d').drawImage(img, 0, 0, canvas.width, canvas.height);
  return canvas.toDataURL('image/jpeg', 0.85).split(',')[1];
}

async function photosDialog(type) {
  let photos = type.photos.slice();
  await modal({
    title: 'Photos', wide: true, cancel: 'Done',
    body: `<p class="small muted">Shown on the booking website. The first photo is the cover. JPEG, PNG or WebP; up to 8 photos.</p>
      <div class="photo-grid" id="ph"></div>
      <label class="btn primary" style="margin-top:12px"><span>+ Add photos</span><input type="file" id="pick" accept="image/jpeg,image/png,image/webp" multiple hidden></label>`,
    onOpen: (m) => {
      const grid = $('#ph', m);
      const reload = async () => { photos = ((await GET('/room-types')).find((x) => x.id === type.id) || { photos: [] }).photos; draw(); };
      const draw = () => {
        grid.innerHTML = photos.map((id, i) => `<figure class="photo"><img src="/api/public/photos/${id}" alt="" loading="lazy">
          <figcaption>${i === 0 ? '<span class="badge b-good">Cover</span>' : `<button type="button" class="btn sm" data-cover="${id}">Make cover</button>`}
          <button type="button" class="btn sm ghost danger" data-rm="${id}" title="Delete photo" aria-label="Delete photo">✕</button></figcaption></figure>`).join('')
          || '<div class="empty">No photos yet</div>';
        on(grid, '[data-cover]', 'click', async (e, b) => { if (await guarded(() => POST(`/room-photos/${b.dataset.cover}/cover`))) reload(); });
        on(grid, '[data-rm]', 'click', async (e, b) => { if (await guarded(() => DEL('/room-photos/' + b.dataset.rm), 'Photo deleted')) reload(); });
      };
      $('#pick', m).addEventListener('change', async (e) => {
        for (const file of Array.from(e.target.files)) {
          let data;
          try { data = await shrinkImage(file); } catch (ex) { toast('This file is not an image the browser can read', 'error'); continue; }
          if (!(await guarded(() => POST(`/room-types/${type.id}/photos`, { data }), 'Photo added'))) break;
        }
        e.target.value = '';
        reload();
      });
      draw();
    },
  });
}
