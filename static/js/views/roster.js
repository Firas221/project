// Staff roster (who works when), attendance, and each person's own shifts and clock.
import { DEL, GET, POST, PUT, qs } from '../core/api.js';
import { $, addDays, badge, confirmBox, esc, field, fmtDate, fmtDateTime, guarded, modal, on, selectField, table, toast, todayISO } from '../core/ui.js';

const hours = (h) => `${Number(h).toLocaleString(undefined, { maximumFractionDigits: 1 })} h`;
/** Monday of the week a date falls in. */
function monday(iso) {
  const d = new Date(iso + 'T00:00:00');
  return addDays(iso, -((d.getDay() + 6) % 7));
}

// ====================================================================== planning (managers)
export async function rosterView(el, { params, ctx, alive }) {
  const from = monday(params.from || todayISO());
  const data = await GET('/roster?' + qs({ from, days: 7 }));
  if (!alive()) return;
  const days = Array.from({ length: 7 }, (_, i) => addDays(from, i));
  const byCell = {};
  data.shifts.forEach((s) => { (byCell[`${s.user_id}:${s.work_date}`] ||= []).push(s); });
  const planned = (userId) => data.shifts.filter((s) => s.user_id === userId).reduce((a, s) => a + s.hours, 0);
  el.innerHTML = `<div class="page-head"><div class="grow"><h1>Staff roster</h1>
      <div class="sub">Week of ${fmtDate(from)}. Click a day to add a shift; click a shift to change or remove it. Staff see their own shifts under “My shifts”.</div></div>
      <div class="btn-row"><button class="btn" id="prev">‹ Week</button><button class="btn" id="this">Today</button><button class="btn" id="next">Week ›</button>
      <button class="btn" id="copy">Copy last week</button></div></div>
    <div class="card"><div class="table-wrap"><table class="roster"><thead><tr><th>Staff</th>${days.map((d) => `<th class="${d === todayISO() ? 'today' : ''}">${fmtDate(d, { weekday: 'short', day: 'numeric', month: 'short' })}</th>`).join('')}<th class="num">Planned</th></tr></thead>
      <tbody>${data.staff.map((u) => `<tr><td><b>${esc(u.full_name)}</b><div class="small muted">${esc(u.role_label)}</div></td>
        ${days.map((d) => `<td class="roster-cell" data-user="${u.id}" data-day="${d}">${(byCell[`${u.id}:${d}`] || []).map((s) =>
    `<button type="button" class="shift-chip" data-shift="${s.id}" title="${esc(s.note)}">${esc(s.start_time)}–${esc(s.end_time)}</button>`).join('')}</td>`).join('')}
        <td class="num">${planned(u.id) ? hours(planned(u.id)) : '—'}</td></tr>`).join('')}</tbody></table></div></div>
    <div class="grid g2" style="margin-top:16px">
      <div class="card"><div class="card-head"><h2>Hours this week</h2></div>${table(['Staff', ['Planned', 'num'], ['Worked', 'num'], ''],
    data.attendance.totals.map((t) => `<tr><td><b>${esc(t.full_name)}</b><div class="small muted">${esc(t.role_label)}</div></td><td class="num">${hours(t.planned_hours)}</td>
          <td class="num ${t.worked_hours + 0.01 < t.planned_hours ? 'text-warn' : ''}">${hours(t.worked_hours)}</td><td>${t.on_the_clock ? badge('in_progress', 'On the clock') : ''}</td></tr>`).join(''), 'Nothing planned or worked this week')}</div>
      <div class="card"><div class="card-head"><h2>Clock records</h2></div>${table(['Staff', 'In', 'Out', ['Hours', 'num'], ''],
    data.attendance.records.map((r) => `<tr><td>${esc(r.user_name)}</td><td class="small">${fmtDateTime(r.clock_in)}</td>
          <td class="small">${r.clock_out ? fmtDateTime(r.clock_out) : badge('in_progress', 'On the clock')}</td><td class="num">${r.clock_out ? hours(r.hours) : '—'}</td>
          <td class="actions"><button class="btn sm" data-fix="${r.id}">Correct</button></td></tr>`).join(''), 'Nobody clocked in this week')}</div></div>`;
  const go = (iso) => { location.hash = '#/roster?from=' + iso; };
  $('#prev', el).addEventListener('click', () => go(addDays(from, -7)));
  $('#next', el).addEventListener('click', () => go(addDays(from, 7)));
  $('#this', el).addEventListener('click', () => go(monday(todayISO())));
  $('#copy', el).addEventListener('click', async () => {
    if (!(await confirmBox('Copy last week', 'Repeat last week’s shifts in this week? Shifts already planned are kept.', 'Copy', false))) return;
    const r = await guarded(() => POST('/roster/copy-week', { from: addDays(from, -7), to: from }));
    if (r) { toast(`${r.copied} shift(s) copied`, 'success'); ctx.refresh(); }
  });
  const staffOptions = data.staff.map((u) => [u.id, `${u.full_name} (${u.role_label})`]);
  const shiftForm = async (s) => {
    let remove = false;
    const ok = await modal({ title: s.id ? 'Change shift' : 'New shift', submit: 'Save',
      body: `<div class="form-grid">${selectField('Staff member', 'user_id', staffOptions, s.user_id, 'full')}${field('Date', 'work_date', s.work_date, 'type="date"', 'full')}
        ${field('Starts', 'start_time', s.start_time || '08:00', 'type="time"')}${field('Ends', 'end_time', s.end_time || '16:00', 'type="time"')}
        ${field('Note', 'note', s.note || '', '', 'full')}<div class="full small muted">An end time earlier than the start means the shift runs past midnight.</div>
        ${s.id ? '<div class="full"><button type="button" class="btn danger" id="del-shift">Remove this shift</button></div>' : ''}</div>`,
      onOpen: (m) => { const b = $('#del-shift', m); if (b) b.addEventListener('click', () => { remove = true; $('[data-close]', m).click(); }); },
      onSubmit: (v) => (s.id ? PUT('/roster/' + s.id, v) : POST('/roster', v)) });
    if (remove) { if (await guarded(() => DEL('/roster/' + s.id), 'Shift removed')) ctx.refresh(); return; }
    if (ok) { toast('Shift saved', 'success'); ctx.refresh(); }
  };
  on(el, '.roster-cell', 'click', (e, cell) => {
    const chip = e.target.closest('[data-shift]');
    if (chip) shiftForm(data.shifts.find((x) => x.id === +chip.dataset.shift));
    else shiftForm({ user_id: +cell.dataset.user, work_date: cell.dataset.day });
  });
  on(el, '[data-fix]', 'click', async (e, b) => {
    const r = data.attendance.records.find((x) => x.id === +b.dataset.fix);
    const local = (stamp) => (stamp ? stamp.slice(0, 16).replace(' ', 'T') : '');
    const ok = await modal({ title: 'Correct clock record', submit: 'Save',
      body: `<p><b>${esc(r.user_name)}</b></p><div class="form-grid">${field('Clocked in', 'clock_in', local(r.clock_in), 'type="datetime-local"')}
        ${field('Clocked out (empty = still working)', 'clock_out', local(r.clock_out), 'type="datetime-local"')}</div>`,
      onSubmit: (v) => PUT('/attendance/' + r.id, v) });
    if (ok) { toast('Record corrected', 'success'); ctx.refresh(); }
  });
}

// ====================================================================== my shifts (everyone)
export async function myShiftsView(el, { ctx, alive }) {
  const me = await GET('/roster/mine');
  if (!alive()) return;
  el.innerHTML = `<div class="page-head"><div class="grow"><h1>My shifts</h1><div class="sub">Your planned shifts for the next two weeks, and your clock.</div></div></div>
    <div class="grid g2"><div class="card"><div class="card-head"><h2 class="grow">Clock</h2>${me.open ? badge('in_progress', 'On the clock') : badge('closed', 'Off the clock')}</div>
      <div class="card-body" id="clock">${me.open ? `<p>Clocked in ${fmtDateTime(me.open.clock_in)}.</p><button class="btn primary" id="clock-out">Clock out</button>`
    : '<p>You are not clocked in.</p><button class="btn primary" id="clock-in">Clock in</button>'}</div>
      ${table(['In', 'Out', ['Hours', 'num']], me.attendance.map((r) => `<tr><td class="small">${fmtDateTime(r.clock_in)}</td>
        <td class="small">${r.clock_out ? fmtDateTime(r.clock_out) : '—'}</td><td class="num">${r.clock_out ? hours(r.hours) : '—'}</td></tr>`).join(''), 'No clock records yet')}</div>
    <div class="card"><div class="card-head"><h2>Planned shifts</h2></div>${table(['Day', 'Time', ['Hours', 'num'], 'Note'], me.shifts.map((s) => `<tr class="${s.work_date === me.today ? 'row-mine' : ''}">
      <td>${fmtDate(s.work_date, { weekday: 'long', day: 'numeric', month: 'short' })}</td><td class="nowrap">${esc(s.start_time)} – ${esc(s.end_time)}</td>
      <td class="num">${hours(s.hours)}</td><td class="small muted">${esc(s.note)}</td></tr>`).join(''), 'No shifts planned for you yet')}</div></div>`;
  const press = (id, url, done) => { const b = $(id, el); if (b) b.addEventListener('click', async () => { if (await guarded(() => POST(url), done)) ctx.refresh(); }); };
  press('#clock-in', '/attendance/clock-in', 'Clocked in');
  press('#clock-out', '/attendance/clock-out', 'Clocked out');
}
