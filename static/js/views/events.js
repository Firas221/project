// Banquet, conference and event bookings: the list, one event with its bill, venues.
import { DEL, GET, POST, PUT, qs } from '../core/api.js';
import {
  $, addDays, badge, bindRowLinks, check as checkbox, confirmBox, esc, field, fmtDate, fmtDateTime, guarded, label, modal, money, on,
  options, selectField, table, textField, toast, todayISO,
} from '../core/ui.js';

const STATUS = { inquiry: ['pending', 'Inquiry'], confirmed: ['in_progress', 'Confirmed'], completed: ['done', 'Completed'], cancelled: ['cancelled', 'Cancelled'] };
const SETUPS = [['', '—'], ['theatre', 'Theatre'], ['classroom', 'Classroom'], ['banquet', 'Banquet'], ['boardroom', 'Boardroom'], ['cocktail', 'Cocktail'], ['u_shape', 'U-shape']];
const METHODS = [['card', 'Card'], ['cash', 'Cash'], ['bank_transfer', 'Bank transfer'], ['other', 'Other']];
const stateBadge = (s) => badge(STATUS[s][0], STATUS[s][1]);

// ====================================================================== list
export async function eventsView(el, { params, ctx, alive }) {
  const status = params.status ?? 'active';
  const [events, venues] = await Promise.all([GET('/events?' + qs({ status })), GET('/venues')]);
  if (!alive()) return;
  const manage = ctx.can('events.manage');
  el.innerHTML = `<div class="page-head"><div class="grow"><h1>Events</h1><div class="sub">Banquets, conferences and meetings in the hotel's venues.</div></div>
      <select id="st" style="width:auto">${options([['active', 'Inquiries and confirmed'], ['completed', 'Completed'], ['cancelled', 'Cancelled'], ['', 'All']], status)}</select>
      ${manage ? '<button class="btn" id="venues">Venues…</button><button class="btn primary" id="new">+ New event</button>' : ''}</div>
    <div class="card">${table(['Date', 'Event', 'Venue', 'Guests', 'Status', ['Total', 'num'], ['Balance', 'num']], events.map((e) => `
      <tr class="clickable" data-href="#/events/${e.id}"><td class="nowrap">${fmtDate(e.event_date)}<div class="small muted">${esc(e.start_time)} – ${esc(e.end_time)}</div></td>
      <td><b>${esc(e.title)}</b><div class="small muted">${esc(e.organizer_name)}${e.company_name ? ' · ' + esc(e.company_name) : ''} · ${esc(e.code)}</div></td>
      <td>${esc(e.venue_name)}</td><td>${e.attendees}</td><td>${stateBadge(e.status)}</td><td class="num">${money(e.total)}</td>
      <td class="num ${e.balance > 0.004 ? 'text-bad' : ''}">${money(e.balance)}</td></tr>`).join(''), 'No events')}</div>`;
  bindRowLinks(el);
  $('#st', el).addEventListener('change', (e) => { location.hash = '#/events?status=' + e.target.value; });
  if ($('#new', el)) $('#new', el).addEventListener('click', async () => { const made = await eventForm(venues); if (made) location.hash = '#/events/' + made.id; });
  if ($('#venues', el)) $('#venues', el).addEventListener('click', async () => { await venuesDialog(); ctx.refresh(); });
}

async function eventForm(venues, e = {}) {
  const companies = await GET('/companies').catch(() => []);
  const usable = venues.filter((v) => v.active || v.id === e.venue_id);
  const made = await modal({ title: e.id ? `Edit ${e.code}` : 'New event', wide: true, submit: 'Save',
    body: `<div class="form-grid">${field('Event *', 'title', e.title, 'placeholder="Annual sales meeting"', 'full')}
      ${selectField('Venue *', 'venue_id', usable.map((v) => [v.id, `${v.name} (up to ${v.capacity})`]), e.venue_id || '')}${field('Guests *', 'attendees', e.attendees || 20, 'type="number" min="1"')}
      ${field('Date *', 'event_date', e.event_date || addDays(todayISO(), 7), 'type="date"')}${selectField('Room layout', 'setup', SETUPS, e.setup || '')}
      ${field('Starts *', 'start_time', e.start_time || '09:00', 'type="time"')}${field('Ends *', 'end_time', e.end_time || '17:00', 'type="time"')}
      ${field('Organizer *', 'organizer_name', e.organizer_name)}${field('Phone', 'organizer_phone', e.organizer_phone)}
      ${field('E-mail', 'organizer_email', e.organizer_email, 'type="email"')}${selectField('Company (to invoice)', 'company_id', [['', '— None —']].concat(companies.map((c) => [c.id, c.name])), e.company_id || '')}
      ${field('Venue charge (empty = from the venue’s rates)', 'venue_charge', e.id ? e.venue_charge : '', 'type="number" step="0.01" min="0"')}
      ${field('Catering per guest', 'catering_per_person', e.catering_per_person ?? 0, 'type="number" step="0.01" min="0"')}
      ${field('Other charges', 'extras', e.extras ?? 0, 'type="number" step="0.01" min="0"')}${field('What for', 'extras_note', e.extras_note, 'placeholder="Projector, flowers…"')}
      ${textField('Notes', 'notes', e.notes)}</div>`,
    onSubmit: (v) => { v.company_id = v.company_id || null; if (v.venue_charge === '') v.venue_charge = null; return e.id ? PUT('/events/' + e.id, v) : POST('/events', v); } });
  if (made) toast('Event saved', 'success');
  return made;
}

async function venuesDialog() {
  await modal({ title: 'Venues', wide: true, cancel: 'Done',
    body: `<div id="venue-list"></div><div class="form-grid" style="margin-top:12px">${field('Name', 'name', '', 'placeholder="Garden terrace"')}${field('Holds (people)', 'capacity', 50, 'type="number" min="1"')}
      ${field('Rate per hour', 'hourly_rate', 0, 'type="number" step="0.01" min="0"')}${field('Rate per day (cap)', 'day_rate', 0, 'type="number" step="0.01" min="0"')}
      <div class="full"><button type="button" class="btn primary" id="add-venue">Add venue</button></div></div>`,
    onOpen: (m) => {
      const list = $('#venue-list', m);
      const draw = async () => {
        const venues = await GET('/venues');
        list.innerHTML = table(['Venue', 'Holds', ['Per hour', 'num'], ['Per day', 'num'], 'In use', ''], venues.map((v) => `<tr><td><b>${esc(v.name)}</b><div class="small muted">${esc(v.description)}</div></td>
          <td>${v.capacity}</td><td class="num">${money(v.hourly_rate)}</td><td class="num">${v.day_rate ? money(v.day_rate) : '—'}</td>
          <td>${checkbox('', 'active', v.active).replace('<input', `<input data-toggle="${v.id}"`)}</td>
          <td class="actions"><button type="button" class="btn sm ghost danger" data-del-venue="${v.id}" title="Delete venue" aria-label="Delete venue">✕</button></td></tr>`).join(''), 'No venues yet');
        on(list, '[data-del-venue]', 'click', async (ev, b) => { if (await guarded(() => DEL('/venues/' + b.dataset.delVenue), 'Venue deleted')) draw(); });
        on(list, '[data-toggle]', 'change', async (ev, box) => {
          const v = venues.find((x) => x.id === +box.dataset.toggle);
          await guarded(() => PUT('/venues/' + v.id, { ...v, active: box.checked }));
          draw();
        });
      };
      $('#add-venue', m).addEventListener('click', async () => {
        const f = $('form', m);
        const body = { name: f.name.value, capacity: f.capacity.value, hourly_rate: f.hourly_rate.value, day_rate: f.day_rate.value };
        if (await guarded(() => POST('/venues', body), 'Venue added')) { f.name.value = ''; draw(); }
      });
      draw();
    } });
}

// ====================================================================== one event
export async function eventView(el, { args, ctx, alive }) {
  const [e, venues] = await Promise.all([GET('/events/' + args[0]), GET('/venues')]);
  if (!alive()) return;
  const manage = ctx.can('events.manage');
  const open = ['inquiry', 'confirmed'].includes(e.status);
  const h = e.hotel;
  el.innerHTML = `<div class="page-head no-print"><div class="grow"><a class="small" href="#/events">‹ Events</a><h1>${esc(e.title)} ${stateBadge(e.status)}</h1>
      <div class="sub">${esc(e.code)} · ${esc(e.venue_name)} · ${fmtDate(e.event_date, { weekday: 'long', day: 'numeric', month: 'long', year: 'numeric' })} · ${esc(e.start_time)} – ${esc(e.end_time)}${e.invoice_number ? ` · invoice ${esc(e.invoice_number)}` : ''}</div></div>
      <div class="btn-row">${manage && e.status === 'inquiry' ? '<button class="btn good" id="confirm">Confirm</button>' : ''}
        ${manage && e.status === 'confirmed' ? '<button class="btn good" id="complete">Complete &amp; invoice</button>' : ''}
        ${manage && open ? '<button class="btn" id="edit">Edit</button><button class="btn danger" id="cancel">Cancel event</button>' : ''}
        <button class="btn" id="print">${e.status === 'completed' ? 'Print invoice' : 'Print quotation'}</button></div></div>
    <div class="grid g-main-side">
      <div class="card invoice-like"><div class="card-head"><h2 class="grow">${e.status === 'completed' ? 'Tax invoice' : 'Quotation'}</h2><span class="small muted">${esc(h.hotel_name)} · Tax reg. no. ${esc(h.tax_registration_number)}</span></div>
        ${table(['Description', ['Amount', 'num']], `
          <tr><td>${esc(e.venue_name)} — ${e.hours} hour(s)</td><td class="num">${money(e.venue_charge)}</td></tr>
          ${e.catering_total ? `<tr><td>Catering — ${e.attendees} guest(s) × ${money(e.catering_per_person)}</td><td class="num">${money(e.catering_total)}</td></tr>` : ''}
          ${e.extras ? `<tr><td>${esc(e.extras_note || 'Other charges')}</td><td class="num">${money(e.extras)}</td></tr>` : ''}
          <tr><td class="right">Subtotal</td><td class="num">${money(e.subtotal)}</td></tr>
          <tr><td class="right">Service charge ${esc(e.service_charge_rate)}%</td><td class="num">${money(e.service_charge)}</td></tr>
          <tr><td class="right">VAT ${esc(e.vat_rate)}%</td><td class="num">${money(e.vat)}</td></tr>
          <tr class="total"><td class="right"><b>Total</b></td><td class="num"><b id="event-total">${money(e.total)}</b></td></tr>
          <tr><td class="right">Paid</td><td class="num">${money(e.paid)}</td></tr>
          <tr><td class="right">Balance</td><td class="num ${e.balance > 0.004 ? 'text-bad' : 'text-good'}" id="event-balance">${money(e.balance)}</td></tr>`)}</div>
      <div class="stack"><div class="card"><div class="card-head"><h2>Details</h2></div><div class="card-body"><dl class="kv">
          <dt>Organizer</dt><dd>${esc(e.organizer_name)}</dd><dt>Phone</dt><dd>${esc(e.organizer_phone) || '—'}</dd><dt>E-mail</dt><dd>${esc(e.organizer_email) || '—'}</dd>
          <dt>Company</dt><dd>${esc(e.company_name) || '—'}</dd><dt>Guests</dt><dd>${e.attendees} (venue holds ${e.venue_capacity})</dd>
          <dt>Room layout</dt><dd>${esc((SETUPS.find(([k]) => k === e.setup) || ['', '—'])[1])}</dd><dt>Notes</dt><dd class="pre">${esc(e.notes) || '—'}</dd></dl></div></div>
        <div class="card no-print"><div class="card-head"><h2 class="grow">Payments</h2>${manage && open && ctx.can('billing.payment') ? '<button class="btn sm primary" id="pay">+ Payment</button>' : ''}</div>
          ${table(['Date', 'Method', ['Amount', 'num']], e.payments.map((p) => `<tr><td class="small">${fmtDateTime(p.created_at)}<div class="muted">${esc(p.reference)}</div></td>
            <td>${esc((METHODS.find(([k]) => k === p.method) || ['', label(p.method)])[1])}</td><td class="num ${p.amount < 0 ? 'text-bad' : ''}">${money(p.amount)}</td></tr>`).join(''), 'No payments yet')}</div></div></div>`;
  const bind = (id, fn) => { const b = $(id, el); if (b) b.addEventListener('click', fn); };
  const setStatus = async (status, done) => { if (await guarded(() => POST(`/events/${e.id}/status`, { status }), done)) ctx.refresh(); };
  bind('#confirm', () => setStatus('confirmed', 'Event confirmed. The venue is held.'));
  bind('#complete', async () => {
    if (await confirmBox('Complete & invoice', e.balance > 0.004 && e.company_name
      ? `The balance of ${money(e.balance)} will go on ${esc(e.company_name)}’s account. A numbered tax invoice is issued.` : 'A numbered tax invoice is issued. The event can no longer be changed.', 'Complete', false)) setStatus('completed', 'Event completed');
  });
  bind('#cancel', async () => { if (await confirmBox('Cancel event', 'Cancel this event? The venue becomes free for that time.', 'Cancel event')) setStatus('cancelled', 'Event cancelled'); });
  bind('#edit', async () => { if (await eventForm(venues, e)) ctx.refresh(); });
  bind('#print', () => print());
  bind('#pay', async () => {
    const ok = await modal({ title: `Payment — ${e.code}`, submit: 'Record payment',
      body: `<div class="form-grid">${field('Amount', 'amount', e.balance > 0 ? e.balance.toFixed(2) : '', 'type="number" step="0.01"')}${selectField('Method', 'method', METHODS, 'card')}
        ${field('Reference', 'reference', '', 'placeholder="Deposit, receipt no.…"', 'full')}</div>`,
      onSubmit: (v) => POST(`/events/${e.id}/payments`, v) });
    if (ok) { toast('Payment recorded', 'success'); ctx.refresh(); }
  });
}
