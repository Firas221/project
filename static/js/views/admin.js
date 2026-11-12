// Administration: users, role permission matrix, hotel settings, audit log, e-mail outbox, sessions, backups.
import { DEL, GET, POST, PUT, qs } from '../core/api.js';
import {
  $, $$, PAGE_SIZE, badge, bindPager, check, confirmBox, esc, field, fmtDate, fmtDateTime, formValues, guarded, label, modal, on, options,
  pager, selectField, showSecret, table, toast,
} from '../core/ui.js';

const ROLE_OPTIONS = [['staff', 'Front desk staff'], ['manager', 'Manager'], ['accountant', 'Accountant'], ['chef', 'Chef / kitchen'],
  ['supervisor', 'Housekeeping supervisor'], ['housekeeper', 'Housekeeper'], ['maintenance', 'Maintenance technician'],
  ['storekeeper', 'Storekeeper'], ['admin', 'Administrator']];

export async function usersView(el, { params, ctx, alive }) {
  const role = params.role || '';
  const [users, sessions] = await Promise.all([GET('/users?' + qs({ role })), GET('/sessions')]);
  if (!alive()) return;
  const online = new Set(sessions.map((s) => s.user_id));
  el.innerHTML = `<div class="page-head"><div class="grow"><h1>Users</h1><div class="sub">Staff accounts and guest logins. ${sessions.length} active session(s).</div></div>
      <select id="role" style="width:auto">${options([['', 'All roles']].concat(ROLE_OPTIONS).concat([['guest', 'Guests (online accounts)']]), role)}</select>
      <button class="btn primary" id="new">+ New staff user</button></div>
    <div class="card">${table(['User', 'Role', 'Status', 'Security', 'Last sign-in', ''], users.map((u) => {
      const locked = u.locked_until && u.locked_until > new Date().toISOString().replace('T', ' ').slice(0, 19);
      return `<tr><td><b>${esc(u.full_name)}</b>${online.has(u.id) ? ' <span class="badge b-good plain">online</span>' : ''}<div class="small muted">${esc(u.username)}${u.email && u.email !== u.username ? ' · ' + esc(u.email) : ''}</div></td>
        <td>${esc(label(u.role))}</td><td>${u.active ? (locked ? badge('rejected', 'Locked') : badge('clean', 'Active')) : badge('closed', 'Disabled')}</td>
        <td class="small">${u.totp_enabled ? '<span class="badge b-good plain">2FA</span>' : '<span class="muted">no 2FA</span>'}${u.must_change_password ? ' <span class="badge b-warn plain">must change pw</span>' : ''}</td>
        <td class="small">${u.last_login_at ? fmtDateTime(u.last_login_at) : '—'}</td>
        <td class="actions">${u.role !== 'guest' ? `<button class="btn sm" data-edit="${u.id}">Edit</button>` : ''} <button class="btn sm" data-more="${u.id}">Security…</button></td></tr>`;
    }).join(''), 'No users')}</div>`;
  $('#role', el).addEventListener('change', (e) => { location.hash = '#/users?role=' + e.target.value; });
  $('#new', el).addEventListener('click', async () => {
    const r = await modal({ title: 'New staff user',
      body: `<div class="form-grid">${field('Username *', 'username', '', 'autocomplete="off"')}${field('Full name *', 'full_name')}${field('E-mail', 'email', '', 'type="email"')}
        ${selectField('Role', 'role', ROLE_OPTIONS, 'staff')}${field('Password (leave empty to generate one)', 'password', '', 'type="password" autocomplete="new-password"', 'full')}
        <div class="full small muted">The user must choose their own password at first sign-in.</div></div>`,
      onSubmit: (v) => POST('/users', v) });
    if (r) {
      if (r.temporary_password) await showSecret('User created', `Give <b>${esc(r.user.username)}</b> this one-time password:`, r.temporary_password);
      else toast('User created', 'success');
      ctx.refresh();
    }
  });
  on(el, '[data-edit]', 'click', async (e, b) => {
    const u = users.find((x) => x.id === +b.dataset.edit);
    const ok = await modal({ title: 'Edit ' + u.username,
      body: `<div class="form-grid">${field('Full name *', 'full_name', u.full_name)}${field('E-mail', 'email', u.email, 'type="email"')}
        ${selectField('Role', 'role', ROLE_OPTIONS, u.role)}${check('Account active', 'active', u.active)}
        <div class="full small muted">Changing the role or disabling the account signs the user out everywhere.</div></div>`,
      onSubmit: (v) => PUT('/users/' + u.id, v) });
    if (ok) { toast('User updated', 'success'); ctx.refresh(); }
  });
  on(el, '[data-more]', 'click', async (e, b) => {
    const u = users.find((x) => x.id === +b.dataset.more);
    let act = null;
    await modal({ title: 'Security — ' + u.username, cancel: 'Close',
      body: `<div class="stack"><button type="button" class="btn" data-a="reset-password">Reset password (one-time password)</button>
        <button type="button" class="btn" data-a="unlock">Unlock account</button><button type="button" class="btn" data-a="revoke-sessions">Sign out of all devices</button>
        ${u.totp_enabled ? '<button type="button" class="btn danger" data-a="reset-2fa">Reset two-factor authentication</button>' : ''}
        ${u.role !== 'guest' && u.id !== ctx.user.id ? '<button type="button" class="btn danger" data-a="delete">Delete user</button>' : ''}</div>`,
      onOpen: (m) => $$('[data-a]', m).forEach((x) => x.addEventListener('click', () => { act = x.dataset.a; $('[data-close]', m).click(); })) });
    if (!act) return;
    if (act === 'delete') {
      if (await confirmBox('Delete user', `Delete <b>${esc(u.username)}</b> for good? Work they recorded stays, without their name. To keep the account but block sign-in, edit the user and untick “Account active” instead.`, 'Delete')
        && await guarded(() => DEL('/users/' + u.id), 'User deleted')) ctx.refresh();
      return;
    }
    const r = await guarded(() => POST(`/users/${u.id}/${act}`));
    if (r && r.temporary_password) await showSecret('Password reset', `New one-time password for <b>${esc(u.username)}</b>:`, r.temporary_password);
    else if (r) toast('Done', 'success');
    ctx.refresh();
  });
}

export async function rolesView(el, { ctx, alive }) {
  const m = await GET('/roles');
  if (!alive()) return;
  const groups = [...new Set(m.catalog.map((c) => c.group))];
  const roles = m.roles.filter((r) => r.name !== 'guest');
  el.innerHTML = `<div class="page-head"><div class="grow"><h1>Roles &amp; permissions</h1>
      <div class="sub">Control what each role can do. Administrators always have every permission. Changes apply at the user's next request.</div></div></div>
    <div class="card"><div class="table-wrap"><table class="matrix"><thead><tr><th>Permission</th>${roles.map((r) => `<th class="center">${esc(r.label)}<div class="small muted">${r.users} user(s)</div></th>`).join('')}</tr></thead>
      <tbody>${groups.map((g) => `<tr class="group-row"><td colspan="${roles.length + 1}">${esc(g)}</td></tr>${m.catalog.filter((c) => c.group === g).map((c) => `<tr>
        <td>${esc(c.description)}<div class="small muted">${esc(c.permission)}</div></td>
        ${roles.map((r) => `<td class="center"><input type="checkbox" data-role="${r.name}" value="${esc(c.permission)}" ${r.permissions.includes(c.permission) ? 'checked' : ''} ${r.editable ? '' : 'disabled'}></td>`).join('')}</tr>`).join('')}`).join('')}
      </tbody></table></div><div class="card-body btn-row">${roles.filter((r) => r.editable).map((r) => `<button class="btn primary" data-save="${r.name}">Save ${esc(r.label)}</button>`).join('')}</div></div>`;
  on(el, '[data-save]', 'click', async (e, b) => {
    const role = b.dataset.save;
    const perms = $$(`input[data-role="${role}"]:checked`, el).map((i) => i.value);
    if (await guarded(() => PUT('/roles/' + role, { permissions: perms }), 'Permissions saved')) ctx.refresh();
  });
}

export async function settingsView(el, { ctx, alive }) {
  const [s, backups] = await Promise.all([GET('/settings'), GET('/backups').catch(() => [])]);
  if (!alive()) return;
  el.innerHTML = `<div class="page-head"><div class="grow"><h1>Hotel settings</h1></div></div>
    <form id="f" class="stack">
      <div class="card"><div class="card-head"><h2 class="grow">Property</h2></div><div class="card-body form-grid">
        ${field('Hotel name', 'hotel_name', s.hotel_name)}${field('Hotel name (Arabic)', 'hotel_name_ar', s.hotel_name_ar, 'dir="rtl"')}
        ${field('Tagline', 'tagline', s.tagline, '', 'full')}${field('Address', 'address', s.address, '', 'full')}${field('Phone', 'phone', s.phone)}${field('E-mail', 'email', s.email)}
        ${field('Check-in time', 'check_in_time', s.check_in_time, 'type="time"')}${field('Check-out time', 'check_out_time', s.check_out_time, 'type="time"')}</div></div>
      <div class="card"><div class="card-head"><h2 class="grow">Tax &amp; legal (Egypt)</h2></div><div class="card-body form-grid">
        ${field('Currency', 'currency', s.currency)}${field('Service charge %', 'service_charge_rate', s.service_charge_rate, 'type="number" step="0.01"')}
        ${field('VAT %', 'vat_rate', s.vat_rate, 'type="number" step="0.01"')}${field('City / municipality tax %', 'city_tax_rate', s.city_tax_rate, 'type="number" step="0.01"')}
        ${field('Tax registration number', 'tax_registration_number', s.tax_registration_number)}${field('Commercial register no.', 'commercial_register', s.commercial_register)}
        ${field('Tourism licence no.', 'tourism_license', s.tourism_license)}${check('Require nationality & ID before check-in', 'require_id_at_checkin', s.require_id_at_checkin === '1')}</div></div>
      <div class="card"><div class="card-head"><h2 class="grow">Operations &amp; pricing</h2></div><div class="card-body form-grid">
        ${field('Weekend days (0=Mon … 6=Sun)', 'weekend_days', s.weekend_days)}${field('Weekend rate uplift %', 'weekend_adjust_pct', s.weekend_adjust_pct, 'type="number" step="0.5"')}
        ${check('Cash payments require an open cashier shift', 'cash_requires_shift', s.cash_requires_shift === '1', 'full')}
        ${check('Run the night audit automatically', 'auto_night_audit', s.auto_night_audit === '1')}${field('Automatic night audit time', 'night_audit_time', s.night_audit_time || '03:00', 'type="time"')}
        <div class="full small muted">The automatic night audit marks no-shows, saves the day's figures and moves the business date forward.
          A time before noon closes the previous day; a time after noon closes the same day.</div>
        ${check('Create stay-over cleaning tasks automatically each day', 'auto_stayover_tasks', s.auto_stayover_tasks === '1')}${field('Create them at', 'stayover_time', s.stayover_time || '08:00', 'type="time"')}
        <div class="full small muted">Every occupied room that is not checking out gets a cleaning task, the same as pressing “Generate stay-over tasks”.</div></div></div>
      <div class="card"><div class="card-head"><h2 class="grow">Guest website</h2></div><div class="card-body form-grid">
        ${check('Online booking enabled', 'online_booking_enabled', s.online_booking_enabled === '1')}${field('Free cancellation until (days before arrival)', 'free_cancellation_days', s.free_cancellation_days, 'type="number" min="0"')}
        ${field('Maximum nights per online booking', 'max_online_nights', s.max_online_nights, 'type="number" min="1"')}
        ${field('Children younger than this stay free (age)', 'child_free_age', s.child_free_age ?? 6, 'type="number" min="0" max="17"')}
        ${field('Reminder e-mail before arrival (days, 0 = never)', 'arrival_reminder_days', s.arrival_reminder_days ?? 2, 'type="number" min="0" max="14"')}
        <div class="full small muted">Guests can change or cancel their own booking until the free-cancellation limit. E-mails go out in the guest's language (English or Arabic).</div></div></div>
      <div class="card"><div class="card-head"><h2 class="grow">Loyalty programme</h2></div><div class="card-body form-grid">
        ${check('Guests earn and redeem loyalty points', 'loyalty_enabled', s.loyalty_enabled !== '0', 'full')}
        ${field('Points earned per 100 spent (before taxes)', 'loyalty_points_per_100', s.loyalty_points_per_100 ?? 10, 'type="number" step="0.5" min="0"')}
        ${field('Value of one point when redeemed', 'loyalty_point_value', s.loyalty_point_value ?? 0.5, 'type="number" step="0.01" min="0"')}
        <div class="full small muted">Points are added at check-out. Tiers follow the points earned from stays: Silver from 1,000, Gold from 5,000, Platinum from 15,000.</div></div></div>
      <div class="card"><div class="card-head"><h2 class="grow">Security</h2></div><div class="card-body form-grid">
        ${check('Require two-factor authentication for administrators', 'require_2fa_for_admins', s.require_2fa_for_admins === '1', 'full')}
        <div class="full small muted">Set up your own 2FA under “My security” before enabling this.</div>
        ${check('Guests must confirm their e-mail address before using their account', 'require_email_verification', s.require_email_verification !== '0', 'full')}
        <div class="full small muted">Applies once outgoing e-mail (SMTP) is configured, so confirmation links can be delivered.</div></div></div>
      <div><button class="btn primary">Save settings</button></div></form>
    <div class="card" style="margin-top:16px"><div class="card-head"><h2 class="grow">Backups</h2><button class="btn sm" id="bk">Back up now</button></div>
      ${table(['File', 'Created', ['Size', 'num'], ''], backups.map((b) => `<tr><td>${esc(b.file)}</td><td>${fmtDateTime(b.created_at)}</td><td class="num">${(b.size / 1024).toFixed(0)} KB</td>
        <td class="actions">${ctx.user.role === 'admin' ? `<button type="button" class="btn sm danger" data-restore="${esc(b.file)}">Restore</button>` : ''}</td></tr>`).join(''), 'No backups yet')}
      <div class="card-body small muted">Automatic backups run every 24 hours by default and the newest 14 are kept. Copy the backup folder to another disk or cloud storage regularly.</div></div>`;
  $('#f', el).addEventListener('submit', async (e) => {
    e.preventDefault();
    if (await guarded(() => PUT('/settings', formValues(e.target)), 'Settings saved')) ctx.refresh();
  });
  $('#bk', el).addEventListener('click', async () => { const r = await guarded(() => POST('/backups')); if (r) { toast('Backup written: ' + r.file, 'success'); ctx.refresh(); } });
  on(el, '[data-restore]', 'click', async (e, b) => {
    const r = await modal({ title: 'Restore backup', submit: 'Restore', danger: true,
      body: `<div class="notice warn">Everything entered after this backup was made will be replaced: reservations, payments, stock and users.
          The current data is saved as a new backup first, so you can go back.</div>
        <p style="margin:12px 0"><b>${esc(b.dataset.restore)}</b></p>
        ${field('Your password (to confirm)', 'password', '', 'type="password" autocomplete="current-password"')}`,
      onSubmit: (v) => POST('/backups/restore', { file: b.dataset.restore, password: v.password }) });
    if (!r) return;
    await modal({ title: 'Backup restored', cancel: 'Sign in again',
      body: `<p>The data from <b>${esc(r.restored)}</b> is now live. The data it replaced was saved as <b>${esc(r.safety_backup || '—')}</b>.</p>
        <p>Everyone has to sign in again.</p>` });
    location.href = '/login';
  });
}

export async function auditView(el, { params, alive }) {
  const f = { q: params.q || '', from: params.from || '', to: params.to || '' };
  const [found, outbox] = await Promise.all([GET('/audit?' + qs({ ...f, page: params.page || 1, per_page: PAGE_SIZE })), GET('/outbox')]);
  if (!alive()) return;
  const rows = found.items;
  el.innerHTML = `<div class="page-head"><div class="grow"><h1>Audit log</h1><div class="sub">Every sign-in, change and security event, with user and IP address.</div></div>
      <a class="btn" href="/api/export/audit?${qs(f)}">Export CSV</a></div>
    <form class="toolbar" id="f"><input type="search" name="q" value="${esc(f.q)}" placeholder="Search action, user, details…">
      <label class="check small">From <input type="date" name="from" value="${esc(f.from)}"></label><label class="check small">To <input type="date" name="to" value="${esc(f.to)}"></label>
      <button class="btn">Filter</button></form>
    <div class="card">${table(['Time', 'User', 'Action', 'Details', 'IP'], rows.map((a) => `<tr class="${/fail|locked/.test(a.action) ? 'row-warn' : ''}">
      <td class="nowrap small">${fmtDateTime(a.created_at)}</td><td>${esc(a.username || '—')}</td><td><b>${esc(label(a.action))}</b></td><td class="small">${esc(a.details)}</td><td class="small muted">${esc(a.ip)}</td></tr>`).join(''), 'No entries')}${pager(found)}</div>
    <div class="card" style="margin-top:16px"><div class="card-head"><h2>E-mail outbox</h2></div>${table(['Queued', 'To', 'Subject', 'Status'], outbox.slice(0, 50).map((m) => `<tr>
      <td class="small">${fmtDateTime(m.created_at)}</td><td>${esc(m.to_address)}</td><td>${esc(m.subject)}</td><td>${badge(m.status === 'sent' ? 'done' : m.status === 'failed' ? 'rejected' : 'pending', m.status)}</td></tr>`).join(''), 'No e-mails')}
      <div class="card-body small muted">Status “logged” means SMTP is not configured yet: set HOTEL_SMTP_HOST etc. to deliver e-mails.</div></div>`;
  $('#f', el).addEventListener('submit', (e) => { e.preventDefault(); location.hash = '#/audit?' + qs(formValues(e.target)); });
  bindPager(el, (page) => { location.hash = '#/audit?' + qs({ ...f, page }); });
  void fmtDate;
}
