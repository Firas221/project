// Waiting list: people who want a room on dates that are full. When a room comes free the desk is alerted
// and books it for them from here.
import { GET, POST } from '../core/api.js';
import { $, badge, confirmBox, esc, field, fmtDate, guarded, modal, on, options, selectField, table, textField, toast, todayISO, addDays } from '../core/ui.js';
import { guestPicker, newReservation } from './frontdesk.js';

export async function waitlistView(el, { params, ctx, alive }) {
  const status = params.status ?? 'waiting';
  const [rows, types] = await Promise.all([GET('/waitlist?status=' + status), GET('/room-types')]);
  if (!alive()) return;
  const manage = ctx.can('reservations.manage');
  el.innerHTML = `<div class="page-head"><div class="grow"><h1>Waiting list</h1>
      <div class="sub">Guests waiting for a room on dates that are full. You are alerted when a room comes free for one of them.</div></div>
      <select id="st" style="width:auto">${options([['waiting', 'Waiting'], ['booked', 'Booked'], ['cancelled', 'Cancelled'], ['', 'All']], status)}</select>
      ${manage ? '<button class="btn primary" id="add">+ Add to waiting list</button>' : ''}</div>
    <div class="card">${table(['Guest', 'Contact', 'Room type', 'Dates', 'Guests', 'Status', ''], rows.map((w) => `<tr>
      <td><b>${esc(w.name)}</b>${w.source === 'online' ? ' <span class="badge b-info plain">online</span>' : ''}${w.notes ? `<div class="small muted">${esc(w.notes)}</div>` : ''}</td>
      <td class="small">${esc(w.phone)}${w.phone && w.email ? '<br>' : ''}${esc(w.email)}</td><td>${esc(w.room_type || 'Any type')}</td>
      <td class="nowrap">${fmtDate(w.check_in)} → ${fmtDate(w.check_out)}</td><td>${w.adults} + ${w.children}</td>
      <td>${w.status === 'waiting' ? (w.rooms_free ? badge('clean', 'Room available') : badge('pending', 'Still full'))
    : w.status === 'booked' ? `${badge('done', 'Booked')}${w.reservation_id ? ` <a href="#/reservations/${w.reservation_id}">${esc(w.reservation_code)}</a>` : ''}` : badge('cancelled')}</td>
      <td class="actions">${manage && w.status === 'waiting' ? `${w.rooms_free ? `<button class="btn sm good" data-book="${w.id}">Book</button> ` : ''}<button class="btn sm ghost danger" data-cancel="${w.id}" title="Remove from waiting list" aria-label="Remove from waiting list">✕</button>` : ''}</td></tr>`).join(''), 'Nobody is waiting')}</div>`;
  $('#st', el).addEventListener('change', (e) => { location.hash = '#/waitlist?status=' + e.target.value; });
  if ($('#add', el)) $('#add', el).addEventListener('click', async () => {
    const ok = await modal({ title: 'Add to waiting list', submit: 'Add',
      body: `<div class="form-grid"><div class="full"><input type="search" id="g-search" placeholder="Search guest…"><input type="hidden" name="guest_id">
          <div class="pick-list hidden" id="g-results"></div><div class="small muted" id="g-picked">No guest selected — or type the details below</div></div>
        ${field('Name', 'name')}${field('Phone', 'phone')}${field('E-mail', 'email', '', 'type="email"', 'full')}
        ${field('Check-in *', 'check_in', addDays(todayISO(), 1), 'type="date"')}${field('Check-out *', 'check_out', addDays(todayISO(), 2), 'type="date"')}
        ${field('Adults', 'adults', 2, 'type="number" min="1" max="20"')}${field('Children', 'children', 0, 'type="number" min="0" max="20"')}
        ${selectField('Room type', 'room_type_id', [['', 'Any type']].concat(types.filter((t) => t.active).map((t) => [t.id, t.name])), '', 'full')}
        ${textField('Notes', 'notes')}</div>`,
      onOpen: (m) => guestPicker($('#g-search', m), $('#g-results', m), (g) => { $('[name=guest_id]', m).value = g.id; $('#g-picked', m).textContent = 'Selected: ' + g.name; }),
      onSubmit: (v) => POST('/waitlist', { ...v, guest_id: v.guest_id || null, room_type_id: v.room_type_id || null }) });
    if (ok) { toast('Added to the waiting list', 'success'); ctx.refresh(); }
  });
  on(el, '[data-cancel]', 'click', async (e, b) => {
    if (await confirmBox('Remove from waiting list', 'Remove this guest from the waiting list?', 'Remove')
      && await guarded(() => POST(`/waitlist/${b.dataset.cancel}/close`, { status: 'cancelled' }), 'Removed')) ctx.refresh();
  });
  // "Book" opens the normal booking form with the stay filled in; once the reservation exists the entry is closed.
  on(el, '[data-book]', 'click', (e, b) => {
    const w = rows.find((x) => x.id === +b.dataset.book);
    const [first, ...rest] = w.name.split(' ');
    newReservation({
      check_in: w.check_in, check_out: w.check_out, adults: w.adults, children: w.children, type_id: w.room_type_id,
      guest_id: w.guest_id, guest_name: w.guest_id ? w.name : '', first_name: first, last_name: rest.join(' '), phone: w.phone, email: w.email,
      onCreated: (res) => POST(`/waitlist/${w.id}/close`, { status: 'booked', reservation_id: res.id }).catch(() => {}),
    });
  });
}
