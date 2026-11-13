// Portal shell: session check, role gate, forced security steps, sidebar navigation and hash routing.
import { GET, POST, loadSession, logout } from './api.js';
import { $, $$, configure, esc, field, fmtDate, fmtDateTime, formValues, icon, todayISO, toast } from './ui.js';
import { isArabic, startTranslator, toggleLang } from './i18n.js';

const PORTALS = [
  ['/admin', 'Admin', (u) => u.role === 'admin'],
  ['/manager', 'Management', (u) => u.role === 'admin' || u.role === 'manager'],
  ['/staff', 'Front desk', (u) => u.permissions.includes('dashboard.view')],
  ['/kitchen', 'Kitchen', (u) => u.permissions.includes('kitchen.view')],
  ['/housekeeping', 'Housekeeping', (u) => u.permissions.includes('housekeeping.work') || u.permissions.includes('housekeeping.manage')],
  ['/finance', 'Accounting', (u) => u.permissions.includes('billing.view') && u.permissions.includes('reports.view')],
  ['/maintenance', 'Maintenance', (u) => u.permissions.includes('maintenance.manage')],
  ['/store', 'Store', (u) => u.permissions.includes('inventory.manage')],
  ['/restaurant', 'Restaurant', (u) => u.permissions.includes('restaurant.serve')],
];

export const can = (user, perm) => !perm || user.role === 'admin' || user.permissions.includes(perm);

/**
 * Starts a staff portal.
 * @param {object} cfg
 *   title   – portal name shown in the sidebar
 *   allow   – (user) => boolean, who may open this portal
 *   nav     – [{path, label, icon, perm, view}] ; path '' is the home view; {sep:true} for separators
 *   routes  – extra [{pattern: RegExp, nav, view}] for detail pages
 */
export async function startPortal(cfg) {
  await startTranslator();
  let me;
  try {
    me = await loadSession();
  } catch (e) {
    location.href = '/login?next=' + encodeURIComponent(location.pathname + location.hash);
    return;
  }
  const user = me.user;
  configure(me.settings);
  if (user.role === 'guest') { location.href = '/account'; return; }
  if (user.must_change_password || user.must_enroll_2fa) { renderSecuritySetup(user, me.settings); return; }
  if (!cfg.allow(user)) {
    document.body.innerHTML = `<div class="center-page"><div class="card card-body" style="max-width:420px">
      <h2>No access</h2><p>Your account (${esc(user.role_label)}) cannot open the ${esc(cfg.title)} portal.</p>
      <a class="btn primary" href="${esc(user.portal)}">Go to my portal</a></div></div>`;
    return;
  }
  const ctx = { user, settings: me.settings, can: (p) => can(user, p) };
  renderLayout(cfg, ctx);
  const router = new Router(cfg, ctx);
  ctx.refresh = () => router.render();
  window.addEventListener('hashchange', () => router.render());
  window.addEventListener('auth:expired', () => {
    toast('Your session has ended. Please sign in again.', 'error');
    setTimeout(() => { location.href = '/login?next=' + encodeURIComponent(location.pathname + location.hash); }, 1200);
  });
  router.render();
}

function renderLayout(cfg, ctx) {
  const { user, settings } = ctx;
  cfg.nav.forEach((n) => { if (n.labelFor) n.label = n.labelFor(user); });
  const nav = cfg.nav.filter((n) => n.sep || ctx.can(n.perm));
  // The manager's portal already holds every department's screens, so there is nothing to switch to.
  const portals = user.role === 'manager' ? [] : PORTALS.filter(([, , ok]) => ok(user));
  document.body.innerHTML = `
    <div class="app portal-${esc(cfg.key)}">
      <aside class="sidebar" id="sidebar">
        <div class="brand"><div class="brand-logo">${esc((settings.hotel_name || 'H')[0])}</div>
          <div><div class="brand-name">${esc((isArabic() && settings.hotel_name_ar) || settings.hotel_name || 'Hotel')}</div><div class="brand-sub">${esc(cfg.title)}</div></div></div>
        <nav class="nav" aria-label="Main">
          ${nav.map((n) => (n.sep ? '<div class="nav-sep"></div>'
            : `<a href="#/${n.path}" data-nav="${n.path}">${icon(n.icon)}<span>${esc(n.label)}</span></a>`)).join('')}
        </nav>
        ${portals.length > 1 ? `<div class="portal-switch"><div class="small">Switch portal</div>
          ${portals.map(([href, name]) => `<a href="${href}" class="${location.pathname === href ? 'active' : ''}">${esc(name)}</a>`).join('')}</div>` : ''}
        <div class="sidebar-foot">
          <div class="who">${esc(user.full_name)}</div>
          <div>${esc(user.role_label)}</div>
          <div class="foot-links"><a href="#/security">My security</a> · <a href="#" id="logout">Sign out</a></div>
          <div class="foot-links"><a href="#" id="lang-toggle" data-no-translate lang="${isArabic() ? 'en' : 'ar'}">${isArabic() ? 'English' : 'العربية'}</a></div>
        </div>
      </aside>
      <div class="main">
        <header class="topbar">
          <button class="btn sm menu-btn" id="menu-btn" aria-label="Menu">☰</button>
          <div class="grow"><b id="top-title"></b></div>
          <span class="muted small" id="top-date">${fmtDate(todayISO(), { weekday: 'long', day: 'numeric', month: 'long', year: 'numeric' })}</span>
          <div class="bell-wrap"><button class="btn sm ghost bell" id="bell" aria-label="Notifications" aria-expanded="false">${icon('bell')}<span class="bell-count hidden" id="bell-count"></span></button>
            <div class="bell-panel hidden" id="bell-panel"></div></div>
          ${cfg.topAction ? `<button class="btn primary sm" id="top-action">${esc(cfg.topAction.label)}</button>` : ''}
        </header>
        <main class="content" id="view" tabindex="-1"></main>
      </div>
    </div>`;
  $('#logout').addEventListener('click', async (e) => { e.preventDefault(); await logout(); location.href = '/login'; });
  startBell();
  $('#lang-toggle').addEventListener('click', (e) => { e.preventDefault(); toggleLang(); });
  $('#menu-btn').addEventListener('click', () => $('#sidebar').classList.toggle('open'));
  if (cfg.topAction && ctx.can(cfg.topAction.perm)) $('#top-action').addEventListener('click', () => cfg.topAction.run(ctx));
  else if (cfg.topAction) $('#top-action').remove();
}

/**
 * The bell: things that need this person's attention — a new guest request, an online booking, a room or
 * ticket assigned to them. The count is checked every 30 seconds; opening the list does not mark anything
 * read, following an alert does.
 */
function startBell() {
  const bell = $('#bell');
  const panel = $('#bell-panel');
  const count = $('#bell-count');
  let data = { unread: 0, items: [] };
  const show = () => {
    count.textContent = data.unread > 99 ? '99+' : String(data.unread);
    count.classList.toggle('hidden', !data.unread);
    if (panel.classList.contains('hidden')) return;
    panel.innerHTML = `<div class="bell-head"><b>Notifications</b>${data.unread ? '<button type="button" class="btn sm" id="bell-all">Mark all as read</button>' : ''}</div>
      ${data.items.map((a) => `<a class="bell-item ${a.read ? '' : 'unread'}" href="${esc(a.link || '#')}" data-alert="${a.id}"><b>${esc(a.title)}</b>
        <span>${esc(a.body)}</span><span class="small muted">${fmtDateTime(a.created_at)}</span></a>`).join('') || '<div class="empty">Nothing new</div>'}`;
    const all = $('#bell-all', panel);
    if (all) all.addEventListener('click', async () => { try { data = await POST('/alerts/read'); show(); } catch (e) { /* next check */ } });
    $$('[data-alert]', panel).forEach((a) => a.addEventListener('click', () => {
      panel.classList.add('hidden');
      bell.setAttribute('aria-expanded', 'false');
      POST('/alerts/read', { id: +a.dataset.alert }).then((d) => { data = d; show(); }).catch(() => {});
    }));
  };
  const check = async () => { if (document.hidden) return; try { data = await GET('/alerts'); show(); } catch (e) { /* signed out or offline */ } };
  bell.addEventListener('click', (e) => {
    e.stopPropagation();
    const open = panel.classList.toggle('hidden') === false;
    bell.setAttribute('aria-expanded', String(open));
    if (open) { show(); check(); }
  });
  document.addEventListener('click', (e) => { if (!panel.contains(e.target)) { panel.classList.add('hidden'); bell.setAttribute('aria-expanded', 'false'); } });
  setInterval(check, 30000);
  check();
}

class Router {
  constructor(cfg, ctx) {
    this.cfg = cfg;
    this.ctx = ctx;
    this.token = 0;
    this.routes = [
      ...cfg.nav.filter((n) => !n.sep).map((n) => ({ pattern: new RegExp(`^${n.path}$`), nav: n.path, view: n.view, perm: n.perm, label: n.label, live: n.live })),
      ...(cfg.routes || []),
      { pattern: /^security$/, nav: 'security', view: securityView, label: 'My security' },
    ];
  }

  /**
   * Screens marked `live: <seconds>` (dashboard, housekeeping, requests …) reload their data by themselves,
   * so new arrivals, tasks and requests appear without anyone pressing refresh. A reload is skipped while a
   * dialog is open, while someone is typing or choosing in the screen, and while the tab is in the background.
   */
  keepFresh(route) {
    clearInterval(this.timer);
    if (!route.live) return;
    this.timer = setInterval(() => {
      const busy = document.querySelector('.modal-back') || document.hidden
        || (document.activeElement && document.activeElement.closest('#view') && /^(INPUT|SELECT|TEXTAREA)$/.test(document.activeElement.tagName));
      if (!busy) this.render(true);
    }, route.live * 1000);
  }

  async render(quiet = false) {
    const hash = decodeURIComponent(location.hash.replace(/^#\/?/, ''));
    const [path, query] = hash.split('?');
    const params = Object.fromEntries(new URLSearchParams(query || ''));
    const view = $('#view');
    $('#sidebar').classList.remove('open');
    const route = this.routes.find((r) => r.pattern.test(path));
    if (!route || !this.ctx.can(route.perm)) { clearInterval(this.timer); view.innerHTML = '<div class="empty">Page not found</div>'; return; }
    if (!quiet) this.keepFresh(route);
    $$('.nav a').forEach((a) => a.classList.toggle('active', a.dataset.nav === route.nav));
    const navItem = this.routes.find((r) => r.nav === route.nav && r.label);
    $('#top-title').textContent = navItem ? navItem.label : '';
    const token = ++this.token;
    if (!quiet) view.innerHTML = '<div class="empty">Loading…</div>';
    try {
      await route.view(view, { args: path.match(route.pattern).slice(1), params, ctx: this.ctx, alive: () => token === this.token });
    } catch (e) {
      if (token === this.token && !quiet) view.innerHTML = `<div class="card card-body"><div class="form-error">${esc(e.message)}</div></div>`;
    }
  }
}

// ------------------------------------------------------------------ security (password + 2FA)
async function securityView(el, { ctx }) {
  el.innerHTML = `
    <div class="page-head"><div class="grow"><h1>My security</h1><div class="sub">Signed in as ${esc(ctx.user.username)}</div></div></div>
    <div class="grid g2">
      <form class="card" id="pw"><div class="card-head"><h2 class="grow">Change password</h2></div><div class="card-body stack">
        ${field('Current password', 'current_password', '', 'type="password" autocomplete="current-password"')}
        ${field('New password', 'new_password', '', 'type="password" autocomplete="new-password"')}
        ${field('Confirm new password', 'confirm', '', 'type="password" autocomplete="new-password"')}
        <p class="small muted">At least 10 characters with upper- and lower-case letters and a digit.</p>
        <button class="btn primary">Change password</button></div></form>
      <div class="card"><div class="card-head"><h2 class="grow">Two-factor authentication</h2></div><div class="card-body" id="tfa"></div></div>
    </div>`;
  $('#pw').addEventListener('submit', async (e) => {
    e.preventDefault();
    const v = formValues(e.target);
    if (v.new_password !== v.confirm) { toast('New passwords do not match', 'error'); return; }
    try { await POST('/auth/password', v); toast('Password changed. Other sessions were signed out.', 'success'); e.target.reset(); } catch (ex) { toast(ex.message, 'error'); }
  });
  twoFactorPanel($('#tfa'), ctx.user);
}

async function twoFactorPanel(box, user, onDone) {
  const enabled = await GET('/auth/me').then((m) => !!m.user.totp_enabled).catch(() => false);
  if (enabled) {
    box.innerHTML = `<p><span class="badge b-good">Enabled</span> Your account asks for a 6-digit code from your authenticator app at sign-in.</p>
      <form id="tfa-off" class="stack">${field('Password (to turn it off)', 'password', '', 'type="password"')}<button class="btn danger">Turn off 2FA</button></form>`;
    $('#tfa-off', box).addEventListener('submit', async (e) => {
      e.preventDefault();
      try { await POST('/auth/2fa/disable', formValues(e.target)); toast('Two-factor authentication turned off', 'success'); twoFactorPanel(box, user); } catch (ex) { toast(ex.message, 'error'); }
    });
    return;
  }
  box.innerHTML = `<p>Protect your account with a second step: a 6-digit code from an authenticator app
    (Google Authenticator, Microsoft Authenticator, Authy…).</p><button class="btn primary" id="tfa-start">Set up 2FA</button>`;
  $('#tfa-start', box).addEventListener('click', async () => {
    let setup;
    try { setup = await POST('/auth/2fa/setup'); } catch (ex) { toast(ex.message, 'error'); return; }
    box.innerHTML = `<ol class="steps"><li>Open your authenticator app and choose <b>Add account → Enter a setup key</b>.</li>
      <li>Account: <b>${esc(user.username)}</b>, key:<div class="secret">${esc(setup.secret.replace(/(.{4})/g, '$1 ').trim())}</div></li>
      <li>Enter the 6-digit code the app shows:</li></ol>
      <form id="tfa-confirm" class="row-form">${field('Code', 'code', '', 'inputmode="numeric" autocomplete="one-time-code" maxlength="8"')}
      <button class="btn primary">Verify &amp; enable</button></form>`;
    $('#tfa-confirm', box).addEventListener('submit', async (e) => {
      e.preventDefault();
      try {
        await POST('/auth/2fa/confirm', formValues(e.target));
        toast('Two-factor authentication enabled', 'success');
        if (onDone) onDone(); else twoFactorPanel(box, user);
      } catch (ex) { toast(ex.message, 'error'); }
    });
  });
}

function renderSecuritySetup(user, settings) {
  document.body.innerHTML = `<div class="center-page"><div class="card login-card">
    <div class="brand"><div class="brand-logo">${esc((settings.hotel_name || 'H')[0])}</div><div><div class="brand-name">${esc(settings.hotel_name)}</div>
    <div class="brand-sub">Account security</div></div></div><div id="setup"></div></div></div>`;
  const box = $('#setup');
  if (user.must_change_password) {
    box.innerHTML = `<div class="notice warn">Please choose a new password before continuing.</div>
      <form id="f" class="stack" style="margin-top:12px">
        ${field('Current (temporary) password', 'current_password', '', 'type="password" autocomplete="current-password"')}
        ${field('New password', 'new_password', '', 'type="password" autocomplete="new-password"')}
        ${field('Confirm new password', 'confirm', '', 'type="password" autocomplete="new-password"')}
        <p class="small muted">At least 10 characters, with upper- and lower-case letters and a digit.</p>
        <button class="btn primary">Save new password</button></form>`;
    $('#f').addEventListener('submit', async (e) => {
      e.preventDefault();
      const v = formValues(e.target);
      if (v.new_password !== v.confirm) { toast('Passwords do not match', 'error'); return; }
      try { await POST('/auth/password', v); location.reload(); } catch (ex) { toast(ex.message, 'error'); }
    });
  } else {
    box.innerHTML = '<div class="notice warn">Your hotel requires administrators to use two-factor authentication.</div><div id="tfa" style="margin-top:12px"></div>';
    twoFactorPanel($('#tfa'), user, () => location.reload());
  }
}
