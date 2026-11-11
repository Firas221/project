// Public hotel website: room types, live availability & pricing, online booking, reviews.
import { GET, POST, loadSession } from '../core/api.js';
import { $, $$, addDays, configure, esc, fmtDate, modal, money, settings, todayISO, toast } from '../core/ui.js';
import { getLang, otherLang, t, toggleLang } from './i18n.js';
import { startTranslator } from '../core/i18n.js';

let session = null;

/** Switching language also tells the hotel which language this guest's e-mails should be in. */
async function switchLanguage() {
  if (session && session.user.role === 'guest') { try { await POST('/portal/language', { language: otherLang() }); } catch (e) { /* not essential */ } }
  toggleLang();
}

const planName = (p) => (getLang() === 'ar' && p.name_ar ? p.name_ar : p.name);

async function init() {
  await startTranslator();   // puts server messages and status labels into Arabic too
  const [info, reviews] = await Promise.all([GET('/public/info'), GET('/public/reviews').catch(() => ({ reviews: [], summary: {} }))]);
  configure(info.settings);
  try { session = await loadSession(); } catch (e) { session = null; }
  const s = info.settings;
  const name = getLang() === 'ar' && s.hotel_name_ar ? s.hotel_name_ar : s.hotel_name;
  document.title = name;
  const user = session && session.user;
  $('#site').innerHTML = `
    <header class="site-head"><a class="logo" href="/">${esc(name)}</a><nav>
      <a href="#rooms">${t('rooms')}</a><a href="#reviews">${t('reviews')}</a>
      ${user ? `<a href="${esc(user.portal)}">${user.role === 'guest' ? t('account') : esc(user.role_label)}</a>` : `<a href="/login">${t('signin')}</a>`}
      <button class="link-btn" id="lang">${t('lang')}</button></nav></header>
    <section class="hero"><div class="hero-inner"><h1>${esc(name)}</h1><p>${esc(s.tagline || '')}</p>
      <form class="search-card" id="search">
        <label>${t('arrival')}<input type="date" name="check_in" value="${todayISO()}" min="${todayISO()}" required></label>
        <label>${t('departure')}<input type="date" name="check_out" value="${addDays(todayISO(), 2)}" required></label>
        <label>${t('adults')}<input type="number" name="adults" value="2" min="1" max="10"></label>
        <label>${t('children')}<input type="number" name="children" value="0" min="0" max="10"></label>
        <label>${t('infants', { age: s.child_free_age || 6 })}<input type="number" name="infants" value="0" min="0" max="6"></label>
        <label>${t('promo')}<input name="promo_code" placeholder="—" style="text-transform:uppercase"></label>
        <button class="btn primary big">${t('search')}</button></form></div></section>
    <main class="site-main">
      <section id="results"></section>
      <section id="rooms"><h2>${t('ourRooms')}</h2><div class="room-grid">${info.room_types.map((r) => `<article class="room-card">
        ${roomImage(r)}<div class="room-body"><h3>${esc(r.name)}</h3><p>${esc(r.description)}</p>
        <div class="small muted">${esc(r.bed_type)} · ${r.size_sqm ? r.size_sqm + ' m² · ' : ''}${t('upTo')} ${r.capacity} ${t('guests')}</div>
        <div class="amen">${r.amenities.split(',').map((a) => `<span>${esc(a.trim())}</span>`).join('')}</div>
        <div class="price">${t('from')} <b>${money(r.base_rate)}</b> ${t('perNight')}</div></div></article>`).join('')}</div>
        <p class="small muted">${t('taxesNote', { sc: s.service_charge_rate, vat: s.vat_rate })} ${t('policy', { d: s.free_cancellation_days })}</p></section>
      <section id="reviews"><h2>${t('guestReviews')}${reviews.summary.average ? ` · ${reviews.summary.average} ★` : ''}</h2><div class="review-grid">
        ${reviews.reviews.map((r) => `<blockquote class="review"><div class="stars">${'★'.repeat(r.rating)}${'☆'.repeat(5 - r.rating)}</div><p>“${esc(r.comment)}”</p>
          <footer>— ${esc(r.guest)}, ${esc(r.room_type)}</footer>${r.reply ? `<div class="reply">${esc(r.reply)}</div>` : ''}</blockquote>`).join('') || '<p class="muted">—</p>'}</div></section>
    </main>
    <footer class="site-foot"><div><b>${esc(name)}</b><br>${esc(s.address)}<br>${esc(s.phone)} · ${esc(s.email)}</div>
      <div>${t('checkIn')} ${esc(s.check_in_time)} · ${t('checkOut')} ${esc(s.check_out_time)}<br><a href="/privacy">${t('privacy')}</a> · <a href="/login">${t('staffLink')}</a></div></footer>`;
  $('#lang').addEventListener('click', switchLanguage);
  $$('[data-photo]').forEach((b) => b.addEventListener('click', () => {
    const box = b.closest('.room-photo');
    $('img', box).src = '/api/public/photos/' + b.dataset.photo;
    $$('[data-photo]', box).forEach((x) => x.classList.toggle('active', x === b));
  }));
  const form = $('#search');
  form.check_in.addEventListener('change', () => { if (form.check_out.value <= form.check_in.value) form.check_out.value = addDays(form.check_in.value, 1); });
  form.addEventListener('submit', (e) => { e.preventDefault(); search(Object.fromEntries(new FormData(form))); });
  // resume a booking started before signing in
  const pending = new URLSearchParams(location.hash.slice(1));
  if (pending.get('book') && user && user.role === 'guest') {
    ['check_in', 'check_out', 'adults', 'children', 'infants', 'promo_code'].forEach((k) => { if (pending.get(k) !== null) form[k].value = pending.get(k); });
    const offers = await search(Object.fromEntries(new FormData(form)));
    const offer = offers && offers.find((o) => o.id === +pending.get('book'));
    history.replaceState(null, '', '/');
    if (offer) confirmBooking(offer, Object.fromEntries(new FormData(form)), offer.plans.find((p) => p.id === +pending.get('plan')) || null);
  }
}

/** Cover photo with small thumbnails to switch between photos, or a letter tile when the hotel has not added any. */
function roomImage(r) {
  if (!r.photos.length) return `<div class="room-img" aria-hidden="true">${esc(r.name[0])}</div>`;
  return `<div class="room-photo"><img src="/api/public/photos/${r.photos[0]}" alt="${esc(r.name)}" loading="lazy">
    ${r.photos.length > 1 ? `<div class="thumbs">${r.photos.map((id, i) => `<button type="button" data-photo="${id}" class="${i ? '' : 'active'}" aria-label="${esc(r.name)} ${i + 1}"><img src="/api/public/photos/${id}" alt="" loading="lazy"></button>`).join('')}</div>` : ''}</div>`;
}

async function search(q) {
  const box = $('#results');
  box.innerHTML = '<div class="empty">…</div>';
  let r;
  try { r = await POST('/public/search', q); } catch (e) { box.innerHTML = `<div class="form-error">${esc(e.message)}</div>`; return null; }
  const sc = +settings.service_charge_rate || 0, vat = +settings.vat_rate || 0;
  const withTax = (x) => x * (1 + sc / 100) * (1 + vat / 100);
  box.innerHTML = `<h2>${fmtDate(r.check_in)} → ${fmtDate(r.check_out)}</h2>${r.offers.length ? `<div class="offer-list">${r.offers.map((o) => `
    <article class="offer">${o.photos.length ? `<img class="offer-img" src="/api/public/photos/${o.photos[0]}" alt="${esc(o.name)}" loading="lazy">` : ''}<div class="offer-info"><h3>${esc(o.name)}</h3><div class="small muted">${t('upTo')} ${o.capacity} ${t('guests')} · ${esc(o.bed_type)}</div>
      ${o.quote.extra_beds ? `<div class="small muted" data-extra-beds>${t('extraBed', { n: o.quote.extra_beds })}</div>` : ''}
      ${o.quote.discount ? `<div class="deal">${esc(o.quote.discount_label)} −${o.quote.discount_pct}%</div>` : ''}
      ${o.quote.nightly.some((n) => n.label) ? `<div class="small muted">${[...new Set(o.quote.nightly.filter((n) => n.label).map((n) => n.label))].map(esc).join(', ')}</div>` : ''}
      ${!o.quote.meets_min_stay ? `<div class="text-bad small">${t('minStay')} ${o.quote.min_nights} ${t('nights')}</div>` : ''}
      ${o.plans.length ? `<fieldset class="rate-choice"><legend>${t('chooseRate')}</legend>
        ${[{ id: '', name: t('standardRate'), meal_plan: 'room_only', refundable: 1, quote: o.quote }].concat(o.plans).map((p, n) => `<label class="rate-opt">
          <input type="radio" name="plan-${o.id}" value="${p.id}" ${n === 0 ? 'checked' : ''} data-total="${withTax(p.quote.total)}" data-avg="${p.quote.average_rate}">
          <span><b>${esc(p.id === '' ? p.name : planName(p))}</b><br><span class="small muted">${t(p.meal_plan)} · ${p.refundable ? t('flexible') : `<span class="text-bad">${t('nonRefundable')}</span>`}</span></span>
          <span class="rate-price">${money(withTax(p.quote.total))}</span></label>`).join('')}</fieldset>` : ''}</div>
      <div class="offer-price"><div class="big-price" data-price>${money(withTax(o.quote.total))}</div><div class="small muted">${o.quote.nights} ${t('nights')} · ${t('inclTaxes')}</div>
      <div class="small muted"><span data-avg>${money(o.quote.average_rate)}</span> ${t('avgRate')}</div>${o.rooms_left <= 3 ? `<div class="small text-bad">${o.rooms_left} ${t('left')}</div>` : ''}
      <button class="btn primary" data-book="${o.id}" ${o.quote.meets_min_stay ? '' : 'disabled'}>${t('book')}</button></div></article>`).join('')}</div>`
    : `<div class="notice warn">${t('noRooms')}</div>`}`;
  $$('.rate-opt input', box).forEach((radio) => radio.addEventListener('change', () => {
    const card = radio.closest('.offer');
    $('[data-price]', card).textContent = money(+radio.dataset.total);
    $('[data-avg]', card).textContent = money(+radio.dataset.avg);
  }));
  $$('[data-book]', box).forEach((b) => b.addEventListener('click', () => {
    const offer = r.offers.find((o) => o.id === +b.dataset.book);
    const picked = $('.rate-opt input:checked', b.closest('.offer'));
    const plan = picked && picked.value ? offer.plans.find((p) => p.id === +picked.value) : null;
    if (!session || session.user.role !== 'guest') {
      const params = new URLSearchParams({ book: offer.id, plan: plan ? plan.id : '', ...q });
      location.href = '/login?next=' + encodeURIComponent('/#' + params.toString()) + '&register=1';
      return;
    }
    confirmBooking(offer, q, plan);
  }));
  box.scrollIntoView({ behavior: 'smooth' });
  return r.offers;
}

async function confirmBooking(offer, q, plan = null) {
  const q2 = plan ? plan.quote : offer.quote;
  const sc = +settings.service_charge_rate || 0, vat = +settings.vat_rate || 0;
  const service = q2.total * sc / 100;
  const tax = (q2.total + service) * vat / 100;
  const res = await modal({
    title: t('confirmBooking'), submit: t('confirm'),
    body: `<dl class="kv"><dt>${t('rooms')}</dt><dd>${esc(offer.name)}</dd>
      <dt>${t('chooseRate')}</dt><dd>${esc(plan ? planName(plan) : t('standardRate'))} · ${t(plan ? plan.meal_plan : 'room_only')}${plan && !plan.refundable ? ` · <b class="text-bad">${t('nonRefundable')}</b>` : ''}</dd>
      <dt>${t('arrival')}</dt><dd>${fmtDate(q.check_in)}</dd>
      <dt>${t('departure')}</dt><dd>${fmtDate(q.check_out)} (${q2.nights} ${t('nights')})</dd><dt>${t('guests')}</dt><dd>${q.adults} + ${q.children}${+q.infants ? ` · ${t('infantsFree', { n: +q.infants })}` : ''}${q2.extra_beds ? ` · ${t('extraBed', { n: q2.extra_beds })}` : ''}</dd>
      <dt>${t('subtotal')}</dt><dd>${money(q2.total)}${q2.discount ? ` <span class="small muted">(−${money(q2.discount)})</span>` : ''}</dd>
      <dt>${t('service')} ${sc}%</dt><dd>${money(service)}</dd><dt>${t('vat')} ${vat}%</dt><dd>${money(tax)}</dd>
      <dt><b>${t('total')}</b></dt><dd><b>${money(q2.total + service + tax)}</b></dd></dl>
      <label class="field" style="margin-top:12px"><span>${t('specialRequests')}</span><textarea name="special_requests" maxlength="1000"></textarea></label>
      <p class="small muted">${plan && !plan.refundable ? t('nonRefundable') + '.' : t('policy', { d: settings.free_cancellation_days })} ${t('payAtHotel')}</p>`,
    onSubmit: (v) => POST('/portal/reservations', { ...q, room_type_id: offer.id, rate_plan_id: plan ? plan.id : null, special_requests: v.special_requests }),
  });
  if (res) { toast(`${t('booked')} ${res.code}`, 'success'); setTimeout(() => { location.href = '/account#/stay/' + res.id; }, 900); }
}

init().catch((e) => { $('#site').innerHTML = `<div class="center-page"><div class="form-error">${esc(e.message)}</div></div>`; });
