// Guest (client) portal: bookings, bill & invoice, room service, requests, reviews, profile, privacy.
import { DEL, GET, POST, PUT, loadSession, logout } from '../core/api.js';
import { $, $$, badge, configure, esc, field, fmtDate, fmtDateTime, formValues, guarded, label, modal, money, qty, settings, toast } from '../core/ui.js';
import { getLang, otherLang, t, toggleLang } from './i18n.js';
import { startTranslator } from '../core/i18n.js';

let me;

async function init() {
  await startTranslator();   // puts server messages and status labels into Arabic too
  try { me = await loadSession(); } catch (e) { location.href = '/login?next=' + encodeURIComponent('/account' + location.hash); return; }
  if (me.user.role !== 'guest') { location.href = me.user.portal; return; }
  if (me.user.must_change_password) { location.href = '/login'; return; }
  configure(me.settings);
  const name = getLang() === 'ar' && me.settings.hotel_name_ar ? me.settings.hotel_name_ar : me.settings.hotel_name;
  document.title = `${t('account')} · ${name}`;
  $('#site').innerHTML = `<header class="site-head"><a class="logo" href="/">${esc(name)}</a><nav>
      <a href="#/">${t('myBookings')}</a><a href="#/profile">${t('profile')}</a><a href="#/privacy">${t('privacy')}</a>
      <a href="/" class="btn sm primary">${t('bookAnother')}</a><button class="link-btn" id="lang">${t('lang')}</button>
      <button class="link-btn" id="out">${t('signout')}</button></nav></header><main class="site-main account" id="view"></main>`;
  $('#lang').addEventListener('click', async () => {
    if (!me.user.must_verify_email) { try { await POST('/portal/language', { language: otherLang() }); } catch (e) { /* not essential */ } }
    toggleLang();
  });
  $('#out').addEventListener('click', async () => { await logout(); location.href = '/'; });
  if (me.user.must_verify_email) { verifyNotice(); return; }
  rememberLanguage();
  window.addEventListener('hashchange', route);
  window.addEventListener('auth:expired', () => { location.href = '/login?next=/account'; });
  route();
}

/** Shown instead of the account until the guest opens the confirmation link we e-mailed. */
function verifyNotice() {
  $('.site-head nav').querySelectorAll('a').forEach((a) => a.remove());
  $('#view').innerHTML = `<div class="card card-body stack" style="max-width:560px;margin:40px auto">
    <h1>${t('verifyTitle')}</h1><p>${t('verifyText', { email: esc(me.user.username) })}</p>
    <div class="btn-row"><button class="btn primary" id="resend">${t('verifyResend')}</button><button class="btn" id="check">${t('verifyDone')}</button></div></div>`;
  $('#resend').addEventListener('click', async (e) => {
    e.target.disabled = true;
    if (!(await guarded(() => POST('/auth/verify-email/resend'), t('verifySent')))) e.target.disabled = false;
  });
  $('#check').addEventListener('click', () => location.reload());
}

/** Tells the hotel, once per browser and language, which language this guest reads — their e-mails follow it. */
function rememberLanguage() {
  const mark = `${me.user.id}:${getLang()}`;
  try {
    if (localStorage.getItem('lang_saved') === mark) return;
    POST('/portal/language', { language: getLang() }).then(() => localStorage.setItem('lang_saved', mark)).catch(() => {});
  } catch (e) { /* storage unavailable */ }
}

const planLine = (r) => [r.rate_plan_name, t(r.meal_plan || 'room_only'), r.refundable ? '' : t('nonRefundable'),
  r.extra_beds ? t('extraBed', { n: r.extra_beds }) : '', r.infants ? t('infantsFree', { n: r.infants }) : ''].filter(Boolean).map(esc).join(' · ');

async function route() {
  const h = location.hash.replace(/^#\/?/, '');
  const view = $('#view');
  view.innerHTML = '<div class="empty">…</div>';
  try {
    if (h.startsWith('stay/')) await stayView(view, +h.split('/')[1]);
    else if (h.startsWith('invoice/')) await invoiceView(view, +h.split('/')[1]);
    else if (h === 'profile') await profileView(view);
    else if (h === 'privacy') privacyView(view);
    else await bookingsView(view);
  } catch (e) { view.innerHTML = `<div class="form-error">${esc(e.message)}</div>`; }
}

async function bookingsView(el) {
  const [list, waiting] = await Promise.all([GET('/portal/reservations'), GET('/portal/waitlist').catch(() => [])]);
  el.innerHTML = `<h1>${t('myBookings')}</h1><p class="muted">${esc(me.user.full_name)}</p>
    ${list.length ? `<div class="booking-list">${list.map((r) => `<a class="booking card" href="#/stay/${r.id}">
      <div><b>${esc(r.room_type)}</b>${r.room_number ? ` · ${t('roomNo')} ${esc(r.room_number)}` : ''}<div class="small muted">${esc(r.code)} · ${planLine(r)}</div></div>
      <div>${fmtDate(r.check_in)} → ${fmtDate(r.check_out)}<div class="small muted">${r.nights} ${t('nights')}</div></div>
      <div>${badge(r.status)}</div><div class="right"><b>${money(r.total)}</b>${r.balance > 0.004 ? `<div class="small text-bad">${t('balance')} ${money(r.balance)}</div>` : ''}</div></a>`).join('')}</div>`
    : `<div class="card card-body center"><p>${t('noBookings')}</p><a class="btn primary" href="/">${t('bookAnother')}</a></div>`}
    ${waiting.length ? `<h2 style="margin-top:24px">${t('waitlistTitle')}</h2><div class="card card-body" id="my-waitlist">${waiting.map((w) => `<div class="line-item">
      <span>${fmtDate(w.check_in)} → ${fmtDate(w.check_out)} · ${esc(w.room_type || t('anyRoom'))}</span><button class="btn sm" data-leave="${w.id}">${t('leaveWaitlist')}</button></div>`).join('')}</div>` : ''}`;
  $$('[data-leave]', el).forEach((b) => b.addEventListener('click', async () => { if (await guarded(() => DEL('/portal/waitlist/' + b.dataset.leave), '✓')) route(); }));
}

async function stayView(el, id) {
  const r = await GET('/portal/reservations/' + id);
  const f = r.folio;
  const inHouse = r.status === 'checked_in';
  el.innerHTML = `<a href="#/">← ${t('myBookings')}</a><h1>${esc(r.room_type)} ${badge(r.status)}</h1>
    <p class="muted">${esc(r.code)} · ${fmtDate(r.check_in)} → ${fmtDate(r.check_out)} · ${r.nights} ${t('nights')}${r.room_number ? ` · ${t('roomNo')} <b>${esc(r.room_number)}</b>` : ''}</p>
    <p class="muted" id="plan">${planLine(r)}</p>
    <div class="btn-row" style="margin-bottom:16px">${r.can_change ? `<button class="btn" id="change">${t('changeBooking')}</button>` : ''}
      ${r.can_cancel ? `<button class="btn danger" id="cancel">${t('cancel')}</button>` : ''}
      ${r.invoice_id ? `<a class="btn" href="#/invoice/${r.id}">${t('invoice')}</a>` : ''}
      ${inHouse ? `<button class="btn primary" id="order">${t('roomService')}</button><button class="btn" id="req">${t('requests')}</button>` : ''}
      ${r.status === 'checked_out' ? `<button class="btn" id="review">${t('review')}</button>` : ''}</div>
    <div class="grid g2"><div class="card"><div class="card-head"><h2>${t('bill')}</h2></div><div class="card-body"><dl class="kv">
      <dt>${t('rooms')}</dt><dd>${money(f.room_total)}</dd>${f.charges.map((c) => `<dt>${esc(c.description)}</dt><dd>${money(c.amount)}</dd>`).join('')}
      <dt>${t('subtotal')}</dt><dd>${money(f.subtotal)}</dd><dt>${t('service')} ${f.service_charge_rate}%</dt><dd>${money(f.service_charge)}</dd>
      <dt>${t('vat')} ${f.vat_rate}%</dt><dd>${money(f.vat)}</dd><dt><b>${t('total')}</b></dt><dd><b>${money(f.total)}</b></dd>
      <dt>${t('paid')}</dt><dd>${money(f.paid)}</dd><dt>${t('balance')}</dt><dd class="${f.balance > 0.004 ? 'text-bad' : 'text-good'}">${money(f.balance)}</dd></dl></div></div>
      <div class="stack">${r.orders.length ? `<div class="card"><div class="card-head"><h2>${t('roomService')}</h2></div><div class="card-body">${r.orders.map((o) =>
        `<div class="line-item"><span>${esc(o.code)} · ${fmtDateTime(o.created_at)}</span>${badge(o.status)}<b>${money(o.total)}</b></div>`).join('')}</div></div>` : ''}
        ${r.requests.length ? `<div class="card"><div class="card-head"><h2>${t('requests')}</h2></div><div class="card-body">${r.requests.map((q) =>
          `<div class="line-item"><span>${esc(label(q.kind))}: ${esc(q.message)}${q.response ? `<br><span class="small text-good">↳ ${esc(q.response)}</span>` : ''}</span>${badge(q.status)}</div>`).join('')}</div></div>` : ''}
        ${r.special_requests ? `<div class="card card-body"><b>${t('specialRequests')}</b><p class="pre">${esc(r.special_requests)}</p></div>` : ''}</div></div>`;
  const b = (sel, fn) => { const x = $(sel, el); if (x) x.addEventListener('click', fn); };
  b('#cancel', async () => {
    if (await modal({ title: t('cancel'), body: `<p>${esc(r.code)} · ${fmtDate(r.check_in)}</p>`, submit: t('cancel'), danger: true, cancel: t('back'), onSubmit: async () => true })
      && await guarded(() => POST(`/portal/reservations/${r.id}/cancel`), '✓')) route();
  });
  b('#change', () => changeBooking(r));
  b('#order', () => orderFood(r));
  b('#req', async () => {
    const ok = await modal({ title: t('requests'), submit: t('send'),
      body: `<label class="field"><span>${t('requestTypes')}</span><select name="kind"><option value="amenity">Extra amenities (towels, pillows…)</option>
        <option value="housekeeping">Room cleaning</option><option value="maintenance">Something is broken</option><option value="wake_up">Wake-up call</option>
        <option value="other">Other</option></select></label><label class="field" style="margin-top:10px"><span>${t('message')}</span><textarea name="message" maxlength="500" required></textarea></label>`,
      onSubmit: (v) => POST(`/portal/reservations/${r.id}/requests`, v) });
    if (ok) { toast('✓', 'success'); route(); }
  });
  b('#review', async () => {
    const ok = await modal({ title: t('review'), submit: t('send'),
      body: `<div class="star-pick">${[5, 4, 3, 2, 1].map((n) => `<label><input type="radio" name="rating" value="${n}" ${n === 5 ? 'checked' : ''}> ${'★'.repeat(n)}</label>`).join('')}</div>
        <label class="field"><span>${t('comment')}</span><textarea name="comment" maxlength="2000"></textarea></label>`,
      onSubmit: (v) => POST(`/portal/reservations/${r.id}/review`, v) });
    if (ok) toast(t('thanksReview'), 'success');
  });
}

/** Two steps: pick the new stay and see its price, then confirm. Nothing is saved until the second step. */
async function changeBooking(r) {
  const types = (await GET('/public/info')).room_types;
  let wanted = { check_in: r.check_in, check_out: r.check_out, adults: r.adults, children: r.children, infants: r.infants, room_type_id: r.room_type_id };
  const url = `/portal/reservations/${r.id}/change`;
  const preview = await modal({
    title: t('changeBooking'), submit: t('seePrice'), cancel: t('back'),
    body: `<p class="small muted">${t('changeNote')}</p><div class="form-grid">
      <label class="field"><span>${t('arrival')}</span><input type="date" name="check_in" value="${wanted.check_in}" required></label>
      <label class="field"><span>${t('departure')}</span><input type="date" name="check_out" value="${wanted.check_out}" required></label>
      <label class="field"><span>${t('adults')}</span><input type="number" name="adults" value="${wanted.adults}" min="1" max="10"></label>
      <label class="field"><span>${t('children')}</span><input type="number" name="children" value="${wanted.children}" min="0" max="10"></label>
      <label class="field"><span>${t('infants', { age: settings.child_free_age || 6 })}</span><input type="number" name="infants" value="${wanted.infants}" min="0" max="6"></label>
      <label class="field full"><span>${t('roomType')}</span><select name="room_type_id">${types.map((x) =>
        `<option value="${x.id}" ${x.id === wanted.room_type_id ? 'selected' : ''}>${esc(x.name)}</option>`).join('')}</select></label></div>`,
    onSubmit: async (v) => {
      wanted = { check_in: v.check_in, check_out: v.check_out, adults: v.adults, children: v.children, infants: v.infants, room_type_id: +v.room_type_id };
      return (await POST(url, { ...wanted, preview: true })).preview;
    },
  });
  if (!preview) return;
  const ok = await modal({
    title: t('changeBooking'), submit: t('confirmChange'), cancel: t('back'),
    body: `<dl class="kv"><dt>${t('roomType')}</dt><dd>${esc(preview.room_type)}</dd>
      <dt>${t('arrival')}</dt><dd>${fmtDate(preview.check_in)}</dd><dt>${t('departure')}</dt><dd>${fmtDate(preview.check_out)} (${preview.nights} ${t('nights')})</dd>
      <dt>${t('guests')}</dt><dd>${preview.adults} + ${preview.children}${preview.infants ? ` · ${t('infantsFree', { n: preview.infants })}` : ''}${preview.extra_beds ? ` · ${t('extraBed', { n: preview.extra_beds })}` : ''}</dd>
      <dt>${t('avgRate')}</dt><dd>${money(preview.rate)}</dd>
      <dt><b>${t('newPrice')}</b></dt><dd><b id="new-total">${money(preview.total)}</b> <span class="small muted">${t('inclTaxes')}</span></dd></dl>
      ${preview.promo_dropped ? `<div class="notice warn" style="margin-top:10px">${t('promoDropped')}</div>` : ''}`,
    onSubmit: () => POST(url, wanted),
  });
  if (ok) { toast(t('changed'), 'success'); route(); }
}

async function orderFood(r) {
  const menu = await GET('/portal/menu');
  const cats = [...new Set(menu.map((m) => m.category))];
  const ok = await modal({ title: t('roomService'), wide: true, submit: t('order'),
    body: `${cats.map((c) => `<h3 class="menu-cat">${esc(c)}</h3>${menu.filter((m) => m.category === c).map((m) => `<label class="menu-row">
      <span><b>${esc(m.name)}</b><br><span class="small muted">${esc(m.description)} · ~${m.prep_minutes} min</span></span><span>${money(m.price)}</span>
      <input type="number" min="0" max="20" value="0" name="m_${m.id}" class="qty-input"></label>`).join('')}`).join('')}
      <label class="field" style="margin-top:12px"><span>Notes / allergies</span><input name="notes" maxlength="500"></label>
      <div class="right" style="margin-top:8px"><b id="tot"></b><div class="small muted">+ ${settings.service_charge_rate}% service + ${settings.vat_rate}% VAT, added to your room bill</div></div>`,
    onOpen: (m) => {
      const upd = () => { $('#tot', m).textContent = `${t('total')} ${money(menu.reduce((a, x) => a + x.price * (+$(`[name=m_${x.id}]`, m).value || 0), 0))}`; };
      $$('.qty-input', m).forEach((i) => i.addEventListener('input', upd));
      upd();
    },
    onSubmit: (v) => {
      const lines = menu.filter((x) => +v['m_' + x.id] > 0).map((x) => ({ menu_item_id: x.id, quantity: +v['m_' + x.id] }));
      if (!lines.length) throw new Error('Choose at least one dish');
      return POST(`/portal/reservations/${r.id}/orders`, { notes: v.notes, lines });
    } });
  if (ok) { toast(`✓ ${ok.code}`, 'success'); route(); }
}

async function invoiceView(el, id) {
  const inv = await GET(`/portal/reservations/${id}/invoice`);
  const d = inv.data;
  const tt = d.totals;
  el.innerHTML = `<div class="no-print btn-row" style="margin-bottom:12px"><a href="#/stay/${id}">← ${t('back')}</a><span class="grow"></span><button class="btn primary" id="p">Print / PDF</button></div>
    <div class="invoice"><div class="inv-head"><div><div class="inv-title">${esc(d.hotel.hotel_name)}</div><div class="ar">${esc(d.hotel.hotel_name_ar || '')}</div>
      <div class="muted">${esc(d.hotel.address)}<br>Tax reg. no. ${esc(d.hotel.tax_registration_number)}</div></div>
      <div class="right"><div class="inv-title">TAX INVOICE</div><div class="ar">فاتورة ضريبية</div><div class="muted">${esc(inv.number)}<br>${fmtDate(inv.issued_at)}</div></div></div>
    <p><b>${esc(inv.bill_to)}</b> · ${esc(d.stay.code)} · ${fmtDate(d.stay.check_in)} – ${fmtDate(d.stay.check_out)}</p>
    <table><thead><tr><th>Description</th><th class="num">Qty</th><th class="num">Unit</th><th class="num">Amount</th></tr></thead><tbody>
      ${d.lines.map((l) => `<tr><td>${esc(l.description)}</td><td class="num">${qty(l.quantity)}</td><td class="num">${money(l.unit_price)}</td><td class="num">${money(l.amount)}</td></tr>`).join('')}
      <tr><td colspan="3" class="right">${t('subtotal')}</td><td class="num">${money(tt.subtotal)}</td></tr>
      <tr><td colspan="3" class="right">${t('service')} ${tt.service_charge_rate}%</td><td class="num">${money(tt.service_charge)}</td></tr>
      <tr><td colspan="3" class="right">${t('vat')} ${tt.vat_rate}%</td><td class="num">${money(tt.vat)}</td></tr>
      <tr class="total"><td colspan="3" class="right">${t('total')}</td><td class="num">${money(tt.total)}</td></tr></tbody></table></div>`;
  $('#p', el).addEventListener('click', () => print());
}

async function profileView(el) {
  const p = await GET('/portal/profile');
  el.innerHTML = `<h1>${t('profile')}</h1><div class="grid g2"><form class="card card-body form-grid" id="f">
      <label class="field"><span>${t('firstName')}</span><input name="first_name" value="${esc(p.first_name)}" required></label>
      <label class="field"><span>${t('lastName')}</span><input name="last_name" value="${esc(p.last_name)}" required></label>
      <label class="field full"><span>${t('email')}</span><input value="${esc(p.email)}" disabled></label>
      <label class="field"><span>${t('phone')}</span><input name="phone" value="${esc(p.phone)}"></label>
      <label class="field"><span>${t('nationality')}</span><input name="nationality" value="${esc(p.nationality)}"></label>
      <label class="field full"><span>${t('address')}</span><input name="address" value="${esc(p.address)}"></label>
      <button class="btn primary">${t('save')}</button></form>
    <form class="card card-body stack" id="pw"><h2>${t('password')}</h2>${field('Current password', 'current_password', '', 'type="password" autocomplete="current-password"')}
      ${field(t('newPassword'), 'new_password', '', 'type="password" autocomplete="new-password"')}<button class="btn">${t('save')}</button></form></div>`;
  $('#f', el).addEventListener('submit', async (e) => { e.preventDefault(); await guarded(() => PUT('/portal/profile', formValues(e.target)), '✓'); });
  $('#pw', el).addEventListener('submit', async (e) => { e.preventDefault(); if (await guarded(() => POST('/auth/password', formValues(e.target)), '✓')) e.target.reset(); });
}

function privacyView(el) {
  el.innerHTML = `<h1>${t('privacy')}</h1><div class="card card-body stack"><p>${t('privacyText')}</p>
    <div class="btn-row"><a class="btn" href="/api/portal/privacy/export">${t('exportData')}</a><button class="btn danger" id="del">${t('deleteAccount')}</button></div></div>`;
  $('#del', el).addEventListener('click', async () => {
    const ok = await modal({ title: t('deleteAccount'), danger: true, submit: t('deleteAccount'),
      body: `<p>${t('privacyText')}</p>${field(t('password'), 'password', '', 'type="password" autocomplete="current-password"')}`,
      onSubmit: (v) => DEL('/portal/account', v) });
    if (ok) { await logout(); location.href = '/'; }
  });
}

init();
