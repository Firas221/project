// Guests: profiles, stay history, police guest register (Egypt), privacy export & erasure.
import { GET, POST, PUT, DEL, qs } from '../core/api.js';
import {
  $, PAGE_SIZE, badge, bindPager, bindRowLinks, check, confirmBox, esc, field, fmtDate, guarded, label, modal, money, pager,
  selectField, table, textField, toast, todayISO, vip,
} from '../core/ui.js';

const ID_TYPES = [['passport', 'Passport'], ['national_id', 'Egyptian national ID'], ['driving_license', 'Driving licence'], ['other', 'Other']];

export async function guestsView(el, { ctx, alive }) {
  el.innerHTML = `<div class="page-head"><div class="grow"><h1>Guests</h1><div class="sub">Profiles, stay history and registration details.</div></div>
      <a class="btn" href="#/guest-register">Guest register (police)</a><a class="btn" href="/api/export/guests">Export CSV</a>
      ${ctx.can('guests.manage') ? '<button class="btn primary" id="new">+ New guest</button>' : ''}</div>
    <div class="toolbar"><input type="search" id="q" placeholder="Name, e-mail, phone, ID…"></div><div class="card" id="list"></div>`;
  const load = async (page = 1) => {
    const found = await GET('/guests?' + qs({ q: $('#q').value.trim(), page, per_page: PAGE_SIZE }));
    if (!alive()) return;
    const list = found.items;
    $('#list').innerHTML = table(['Name', 'Nationality', 'E-mail', 'Phone', 'ID', ['Stays', 'num'], 'Last stay'], list.map((g) => `
      <tr class="clickable" data-href="#/guests/${g.id}"><td><b>${esc(g.last_name)}, ${esc(g.first_name)}</b>${vip(g.vip)}${g.user_id ? ' <span class="badge b-info plain">Online account</span>' : ''}</td>
      <td>${esc(g.nationality)}</td><td>${esc(g.email)}</td><td>${esc(g.phone)}</td><td class="small">${esc(g.id_number)}</td>
      <td class="num">${g.stays}</td><td>${g.last_stay ? fmtDate(g.last_stay) : '—'}</td></tr>`).join(''), 'No guests found') + pager(found);
    bindRowLinks(el);
    bindPager(el, load);
  };
  let t;
  $('#q').addEventListener('input', () => { clearTimeout(t); t = setTimeout(() => load(), 250); });
  if ($('#new')) $('#new').addEventListener('click', async () => { const g = await guestForm(); if (g) location.hash = '#/guests/' + g.id; });
  await load();
}

export async function guestForm(g = {}) {
  const res = await modal({
    title: g.id ? 'Edit guest' : 'New guest', wide: true,
    body: `<div class="form-grid">${field('First name *', 'first_name', g.first_name)}${field('Last name *', 'last_name', g.last_name)}
      ${field('E-mail', 'email', g.email, 'type="email"')}${field('Phone', 'phone', g.phone)}
      ${field('Nationality', 'nationality', g.nationality)}${selectField('Gender', 'gender', [['', '—'], ['male', 'Male'], ['female', 'Female']], g.gender)}
      ${selectField('ID type', 'id_type', ID_TYPES, g.id_type || 'passport')}${field('ID / passport number', 'id_number', g.id_number)}
      ${field('Date of birth', 'date_of_birth', g.date_of_birth, 'type="date"')}${selectField('Language for e-mails', 'language', [['', 'English'], ['ar', 'العربية']], g.language === 'ar' ? 'ar' : '')}
      ${check('VIP guest', 'vip', g.vip)}
      ${field('Address', 'address', g.address, '', 'full')}${check('Agreed to receive marketing messages', 'marketing_consent', g.marketing_consent, 'full')}
      ${textField('Notes / preferences', 'notes', g.notes)}
      <div class="full small muted">Nationality and ID number are required before check-in (guest registration for the authorities).</div></div>`,
    onSubmit: (v) => (g.id ? PUT('/guests/' + g.id, v) : POST('/guests', v)),
  });
  if (res) toast(g.id ? 'Guest updated' : 'Guest created', 'success');
  return res;
}

export async function guestView(el, { args, ctx, alive }) {
  const g = await GET('/guests/' + args[0]);
  if (!alive()) return;
  const erased = !!g.anonymized_at;
  el.innerHTML = `<div class="page-head"><div class="grow"><a class="small" href="#/guests">‹ Guests</a>
      <h1>${esc(g.first_name)} ${esc(g.last_name)} ${vip(g.vip)}</h1>
      <div class="sub">${g.stays} stay(s) · lifetime value ${money(g.lifetime_value)}${erased ? ' · <b>personal data erased</b>' : ''}</div></div>
      <div class="btn-row">${ctx.can('guests.manage') && !erased ? '<button class="btn" id="edit">Edit</button>' : ''}
      ${ctx.can('guests.manage') ? '<button class="btn" id="export">Export data (PDPL)</button>' : ''}
      ${ctx.can('users.manage') && !erased ? '<button class="btn danger" id="erase">Erase personal data</button>' : ''}
      ${ctx.can('guests.manage') && !g.reservations.length && !g.user_id ? '<button class="btn danger" id="delete">Delete guest</button>' : ''}
      ${ctx.can('reservations.manage') && !erased ? '<button class="btn primary" id="book">+ Book stay</button>' : ''}</div></div>
    <div class="grid g-main-side">
      <div class="card"><div class="card-head"><h2>Reservations</h2></div>${table(['Code', 'Room', 'Dates', 'Status', ['Total', 'num']],
        g.reservations.map((r) => `<tr class="clickable" data-href="#/reservations/${r.id}"><td><b>${esc(r.code)}</b></td><td>${esc(r.room_number)}</td>
        <td class="nowrap">${fmtDate(r.check_in)} → ${fmtDate(r.check_out)}</td><td>${badge(r.status)}</td><td class="num">${money(r.total)}</td></tr>`).join(''), 'No reservations')}</div>
      <div class="card"><div class="card-head"><h2>Details</h2></div><div class="card-body"><dl class="kv">
        <dt>Nationality</dt><dd>${esc(g.nationality) || '—'}</dd><dt>${esc(label(g.id_type))}</dt><dd>${esc(g.id_number) || '—'}</dd>
        <dt>Date of birth</dt><dd>${g.date_of_birth ? fmtDate(g.date_of_birth) : '—'}</dd><dt>E-mail</dt><dd>${esc(g.email) || '—'}</dd>
        <dt>Phone</dt><dd>${esc(g.phone) || '—'}</dd><dt>Address</dt><dd>${esc(g.address) || '—'}</dd>
        <dt>Language for e-mails</dt><dd>${g.language === 'ar' ? 'العربية' : 'English'}</dd>
        <dt>Privacy notice</dt><dd>${g.privacy_accepted_at ? 'Accepted ' + fmtDate(g.privacy_accepted_at) : '—'}</dd>
        <dt>Marketing</dt><dd>${g.marketing_consent ? 'Consented' : 'No consent'}</dd><dt>Notes</dt><dd class="pre">${esc(g.notes) || '—'}</dd></dl></div></div></div>`;
  bindRowLinks(el);
  const b = (id, fn) => { const x = $(id, el); if (x) x.addEventListener('click', fn); };
  b('#edit', async () => { if (await guestForm(g)) ctx.refresh(); });
  b('#book', async () => { const { newReservation } = await import('./frontdesk.js'); newReservation({ guest_id: g.id, guest_name: `${g.first_name} ${g.last_name}` }); });
  b('#export', async () => {
    const data = await guarded(() => GET(`/guests/${g.id}/export`));
    if (!data) return;
    const a = document.createElement('a');
    a.href = URL.createObjectURL(new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' }));
    a.download = `guest-${g.id}-data.json`;
    a.click();
  });
  b('#delete', async () => {
    if (!(await confirmBox('Delete guest', 'Delete this guest profile? Only profiles with no reservations and no online account can be deleted.', 'Delete'))) return;
    if (await guarded(() => DEL('/guests/' + g.id), 'Guest deleted')) location.hash = '#/guests';
  });
  b('#erase', async () => {
    if (!(await confirmBox('Erase personal data', `Permanently erase ${esc(g.first_name)} ${esc(g.last_name)}'s personal data (name, contact, ID)?
      Invoices and payments are kept anonymously as required by tax law. This cannot be undone.`, 'Erase'))) return;
    if (await guarded(() => POST(`/guests/${g.id}/erase`), 'Personal data erased')) ctx.refresh();
  });
}

export async function registerView(el, { params, alive }) {
  const day = params.date || todayISO();
  const all = params.all === '1';
  const rows = await GET('/guest-register?' + qs({ date: day, all: all ? 1 : '' }));
  if (!alive()) return;
  el.innerHTML = `<div class="page-head"><div class="grow"><h1>Guest register</h1>
      <div class="sub">Guests staying on ${fmtDate(day)} — for submission to the tourism police / authorities.</div></div>
      <div class="btn-row"><input type="date" id="d" value="${day}" style="width:auto">
      <label class="check"><input type="checkbox" id="all" ${all ? 'checked' : ''}> Include Egyptian nationals</label>
      <a class="btn" href="/api/export/guest_register?${qs({ date: day, all: all ? 1 : '' })}">Export CSV</a><button class="btn" id="p">Print</button></div></div>
    <div class="card">${table(['Room', 'Name', 'Nationality', 'ID type', 'ID / passport', 'Date of birth', 'Arrival', 'Departure', 'Pax'],
      rows.map((r) => `<tr><td>${esc(r.room_number)}</td><td>${esc(r.first_name)} ${esc(r.last_name)}</td><td>${esc(r.nationality) || '<span class="text-bad">missing</span>'}</td>
      <td>${esc(label(r.id_type))}</td><td>${esc(r.id_number) || '<span class="text-bad">missing</span>'}</td><td>${r.date_of_birth ? fmtDate(r.date_of_birth) : '—'}</td>
      <td>${fmtDate(r.check_in)}</td><td>${fmtDate(r.check_out)}</td><td>${r.adults + r.children}</td></tr>`).join(''), 'No guests to report')}</div>`;
  const go = () => { location.hash = '#/guest-register?' + qs({ date: $('#d').value, all: $('#all').checked ? 1 : '' }); };
  $('#d').addEventListener('change', go);
  $('#all').addEventListener('change', go);
  $('#p').addEventListener('click', () => print());
}
