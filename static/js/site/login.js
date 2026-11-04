// Sign-in page for everyone (staff and guests): password, 2FA, guest registration, password reset.
import { GET, POST, setCsrf } from '../core/api.js';
import { $, esc, formValues } from '../core/ui.js';
import { t, toggleLang } from './i18n.js';

const params = new URLSearchParams(location.search);
let hotel = { hotel_name: 'Hotel' };

/** Only allow redirects to paths on this site (prevents open-redirect attacks). */
function safeNext(fallback) {
  const n = params.get('next') || '';
  return n.startsWith('/') && !n.startsWith('//') && !n.startsWith('/\\') ? n : fallback;
}

function shell(inner) {
  $('#app').innerHTML = `<div class="login-wrap"><div class="card login-card">
    <div class="brand"><div class="brand-logo">${esc((hotel.hotel_name || 'H')[0])}</div><div><div class="brand-name">${esc(hotel.hotel_name)}</div>
      <div class="brand-sub">${esc(hotel.tagline || '')}</div></div><button class="link-btn" id="lang" style="margin-inline-start:auto">${t('lang')}</button></div>
    <div class="form-error hidden" id="err" role="alert"></div><div class="notice hidden" id="msg"></div>${inner}</div></div>`;
  $('#lang').addEventListener('click', toggleLang);
}
const showError = (m) => { const e = $('#err'); e.textContent = m; e.classList.remove('hidden'); };
const showMsg = (m) => { const e = $('#msg'); e.textContent = m; e.classList.remove('hidden'); };

function done(result) {
  setCsrf(result.csrf_token);
  location.href = safeNext(result.user.portal);
}

function signIn() {
  shell(`<form id="f" class="stack"><label class="field"><span>${t('email')} / username</span><input name="username" autocomplete="username" required></label>
      <label class="field"><span>${t('password')}</span><input name="password" type="password" autocomplete="current-password" required></label>
      <button class="btn primary block">${t('signin')}</button></form>
    <div class="login-links"><a href="#" id="forgot">${t('forgot')}</a><span>${t('noAccount')} <a href="#" id="reg">${t('register')}</a></span></div>
    <p class="small muted center"><a href="/">← ${esc(hotel.hotel_name)}</a></p>`);
  $('#forgot').addEventListener('click', (e) => { e.preventDefault(); forgot(); });
  $('#reg').addEventListener('click', (e) => { e.preventDefault(); register(); });
  $('input[name=username]').focus();
  $('#f').addEventListener('submit', async (e) => {
    e.preventDefault();
    const btn = $('button', e.target);
    btn.disabled = true;
    try {
      const r = await POST('/auth/login', formValues(e.target));
      if (r.two_factor_required) twoFactor(r.challenge); else done(r);
    } catch (ex) { showError(ex.message); btn.disabled = false; }
  });
}

function twoFactor(challenge) {
  shell(`<p>Enter the 6-digit code from your authenticator app.</p><form id="f" class="stack">
    <label class="field"><span>${t('code')}</span><input name="code" inputmode="numeric" autocomplete="one-time-code" maxlength="8" required></label>
    <button class="btn primary block">${t('verify')}</button></form>`);
  $('input[name=code]').focus();
  $('#f').addEventListener('submit', async (e) => {
    e.preventDefault();
    try { done(await POST('/auth/2fa', { challenge, code: formValues(e.target).code })); } catch (ex) {
      showError(ex.message);
      if (/again/.test(ex.message)) setTimeout(signIn, 1500);
    }
  });
}

function register() {
  shell(`<h2 style="margin-bottom:12px">${t('register')}</h2><form id="f" class="form-grid">
    <label class="field"><span>${t('firstName')}</span><input name="first_name" required autocomplete="given-name"></label>
    <label class="field"><span>${t('lastName')}</span><input name="last_name" required autocomplete="family-name"></label>
    <label class="field full"><span>${t('email')}</span><input name="email" type="email" required autocomplete="email"></label>
    <label class="field"><span>${t('phone')}</span><input name="phone" autocomplete="tel"></label>
    <label class="field"><span>${t('nationality')}</span><input name="nationality"></label>
    <label class="field full"><span>${t('password')}</span><input name="password" type="password" autocomplete="new-password" required></label>
    <p class="full small muted">10+ characters, upper- and lower-case letters and a digit.</p>
    <label class="check full"><input type="checkbox" name="accept_privacy"> <span>${t('acceptPrivacy')} (<a href="/privacy" target="_blank" rel="noopener">${t('privacy')}</a>)</span></label>
    <label class="check full"><input type="checkbox" name="marketing_consent"> ${t('marketing')}</label>
    <button class="btn primary block full">${t('register')}</button></form>
    <p class="small center">${t('haveAccount')} <a href="#" id="back">${t('signin')}</a></p>`);
  $('#back').addEventListener('click', (e) => { e.preventDefault(); signIn(); });
  $('#f').addEventListener('submit', async (e) => {
    e.preventDefault();
    try { done(await POST('/auth/register', formValues(e.target))); } catch (ex) { showError(ex.message); }
  });
}

function forgot() {
  shell(`<h2 style="margin-bottom:12px">${t('resetTitle')}</h2><form id="f" class="stack">
    <label class="field"><span>${t('email')} / username</span><input name="identifier" required></label><button class="btn primary block">${t('sendLink')}</button></form>
    <p class="small center"><a href="#" id="back">${t('back')}</a></p>`);
  $('#back').addEventListener('click', (e) => { e.preventDefault(); signIn(); });
  $('#f').addEventListener('submit', async (e) => {
    e.preventDefault();
    try { const r = await POST('/auth/forgot', formValues(e.target)); showMsg(r.message); e.target.reset(); } catch (ex) { showError(ex.message); }
  });
}

function resetPassword(token) {
  history.replaceState(null, '', '/login');
  shell(`<h2 style="margin-bottom:12px">${t('resetTitle')}</h2><form id="f" class="stack">
    <label class="field"><span>${t('newPassword')}</span><input name="new_password" type="password" autocomplete="new-password" required></label>
    <label class="field"><span>${t('newPassword')} (2)</span><input name="confirm" type="password" autocomplete="new-password" required></label>
    <button class="btn primary block">${t('save')}</button></form>`);
  $('#f').addEventListener('submit', async (e) => {
    e.preventDefault();
    const v = formValues(e.target);
    if (v.new_password !== v.confirm) { showError('Passwords do not match'); return; }
    try { await POST('/auth/reset', { token, new_password: v.new_password }); signIn(); showMsg('Password changed. You can sign in now.'); } catch (ex) { showError(ex.message); }
  });
}

(async () => {
  try { hotel = (await GET('/public/info')).settings; } catch (e) { /* offline */ }
  document.title = `${t('signin')} · ${hotel.hotel_name}`;
  const reset = new URLSearchParams(location.hash.slice(1)).get('reset');
  if (reset) resetPassword(reset);
  else if (params.get('register')) register();
  else signIn();
})();
