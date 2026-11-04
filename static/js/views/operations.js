// Operations: housekeeping (supervisor + housekeeper views), maintenance, guest requests, lost & found, reviews.
import { GET, POST, PUT } from '../core/api.js';
import {
  $, badge, check, esc, field, fmtDate, fmtDateTime, guarded, label, modal, on, options, selectField, table, textField,
  toast,
} from '../core/ui.js';

const KINDS = [['checkout_clean', 'Departure clean'], ['stayover', 'Stay-over service'], ['deep_clean', 'Deep clean'], ['turndown', 'Turndown'], ['guest_request', 'Guest request']];
const kindLabel = (k) => (KINDS.find((x) => x[0] === k) || [k, label(k)])[1];
const PRIORITIES = [['low', 'Low'], ['normal', 'Normal'], ['high', 'High'], ['urgent', 'Urgent']];

// ====================================================================== housekeeping supervisor board
export async function housekeepingBoardView(el, { params, ctx, alive }) {
  const status = params.status || '';
  const [tasks, rooms, staff] = await Promise.all([GET('/housekeeping/tasks' + (status ? '?status=' + status : '')), GET('/rooms'),
    ctx.can('housekeeping.manage') ? GET('/housekeeping/staff') : []]);
  if (!alive()) return;
  const manage = ctx.can('housekeeping.manage');
  const floors = [...new Set(rooms.map((r) => r.floor))];
  el.innerHTML = `<div class="page-head"><div class="grow"><h1>Housekeeping</h1><div class="sub">Room status and cleaning tasks.</div></div>
      ${manage ? '<button class="btn" id="gen">Generate stay-over tasks</button><button class="btn primary" id="new">+ Task</button>' : ''}</div>
    <div class="grid g-main-side">
      <div class="card"><div class="card-head"><h2 class="grow">Tasks</h2><select id="st" style="width:auto">${options([['', 'Open, in progress & done'], ['open', 'Open'], ['in_progress', 'In progress'], ['done', 'Awaiting inspection']], status)}</select></div>
        ${table(['Room', 'Task', 'Priority', 'Assigned', 'Status', ''], tasks.map((t) => `<tr><td><b>${esc(t.room_number)}</b> ${t.occupied ? '<span class="badge b-info plain">Occupied</span>' : ''}<div class="small muted">${esc(t.room_type)}</div></td>
          <td>${esc(kindLabel(t.kind))}${t.notes ? `<div class="small muted pre">${esc(t.notes)}</div>` : ''}</td><td>${badge(t.priority)}</td>
          <td>${manage ? `<select data-assign="${t.id}" class="compact">${options([['', '— Unassigned —']].concat(staff.map((s) => [s.id, s.full_name])), t.assigned_to || '')}</select>` : esc(t.assigned_name || '—')}</td>
          <td>${badge(t.status)}</td><td class="actions">${t.status === 'done' && manage ? `<button class="btn sm good" data-pass="${t.id}">Pass</button> <button class="btn sm" data-fail="${t.id}">Re-clean</button>` : ''}
            ${['open', 'in_progress'].includes(t.status) && manage ? `<button class="btn sm ghost" data-cancel="${t.id}" title="Cancel task">✕</button>` : ''}</td></tr>`).join(''), 'No tasks')}</div>
      <div class="card"><div class="card-head"><h2>Room status</h2></div><div class="card-body">
        ${floors.map((f) => `<div class="small muted" style="margin:6px 0 4px">Floor ${f}</div><div class="room-chips">${rooms.filter((r) => r.floor === f).map((r) => `
          <button class="room-chip ${r.status}${r.occupied ? ' occ' : ''}" data-room="${r.id}" title="${esc(r.type_name)} · ${esc(label(r.status))}${r.occupied ? ' · occupied' : ''}">${esc(r.number)}</button>`).join('')}</div>`).join('')}
        <div class="legend" style="margin-top:12px">${badge('clean')}${badge('inspected')}${badge('dirty')}${badge('maintenance', 'Out of order')}<span class="small">● = occupied</span></div></div></div></div>`;
  $('#st', el).addEventListener('change', (e) => { location.hash = '#/housekeeping' + (e.target.value ? '?status=' + e.target.value : ''); });
  on(el, '[data-assign]', 'change', async (e, s) => { if (await guarded(() => POST(`/housekeeping/tasks/${s.dataset.assign}/assign`, { user_id: s.value || null }), 'Task assigned')) ctx.refresh(); });
  on(el, '[data-pass]', 'click', async (e, b) => { if (await guarded(() => POST(`/housekeeping/tasks/${b.dataset.pass}/inspect`, { passed: true }), 'Room inspected')) ctx.refresh(); });
  on(el, '[data-fail]', 'click', async (e, b) => {
    const v = await modal({ title: 'Send back for re-clean', submit: 'Send back', body: field('What needs fixing?', 'notes'), onSubmit: async (x) => x });
    if (v && await guarded(() => POST(`/housekeeping/tasks/${b.dataset.fail}/inspect`, { passed: false, notes: v.notes }), 'Sent back')) ctx.refresh();
  });
  on(el, '[data-cancel]', 'click', async (e, b) => { if (await guarded(() => POST(`/housekeeping/tasks/${b.dataset.cancel}/cancel`), 'Task cancelled')) ctx.refresh(); });
  on(el, '[data-room]', 'click', async (e, b) => {
    if (!ctx.can('rooms.status')) return;
    const r = rooms.find((x) => x.id === +b.dataset.room);
    const ok = await modal({ title: `Room ${r.number}`, submit: 'Update status',
      body: `${selectField('Status', 'status', [['clean', 'Clean'], ['inspected', 'Inspected'], ['dirty', 'Dirty']].concat(ctx.can('maintenance.manage') ? [['maintenance', 'Out of order']] : []), r.status)}
        <p class="small muted">${r.occupied ? 'Occupied by ' + esc(r.current_guest) : 'Vacant'}${r.notes ? ' · ' + esc(r.notes) : ''}</p>`,
      onSubmit: (v) => POST(`/rooms/${r.id}/status`, v) });
    if (ok) { toast('Room updated', 'success'); ctx.refresh(); }
  });
  if ($('#gen', el)) $('#gen', el).addEventListener('click', async () => { const r = await guarded(() => POST('/housekeeping/generate')); if (r) { toast(`${r.created} task(s) created`, 'success'); ctx.refresh(); } });
  if ($('#new', el)) $('#new', el).addEventListener('click', async () => {
    const ok = await modal({ title: 'New housekeeping task',
      body: `<div class="form-grid">${selectField('Room', 'room_id', rooms.map((r) => [r.id, `${r.number} (${label(r.status)})`]), '')}${selectField('Task', 'kind', KINDS, 'deep_clean')}
        ${selectField('Priority', 'priority', PRIORITIES, 'normal')}${selectField('Assign to', 'assigned_to', [['', '— Unassigned —']].concat(staff.map((s) => [s.id, s.full_name])), '')}
        ${field('Due date', 'due_date', '', 'type="date"')}${textField('Instructions', 'notes')}</div>`,
      onSubmit: (v) => { v.assigned_to = v.assigned_to || null; v.due_date = v.due_date || null; return POST('/housekeeping/tasks', v); } });
    if (ok) { toast('Task created', 'success'); ctx.refresh(); }
  });
}

// ====================================================================== housekeeper's own work list (maid portal)
export async function myTasksView(el, { ctx, alive }) {
  const tasks = await GET('/housekeeping/tasks?mine=1');
  if (!alive()) return;
  const mine = tasks.filter((t) => t.assigned_to === ctx.user.id);
  const pool = tasks.filter((t) => !t.assigned_to);
  const card = (t) => `<div class="card task-card prio-${t.priority}">
      <div class="task-top"><span class="room-no">${esc(t.room_number)}</span>${badge(t.priority)}<span class="grow"></span>${badge(t.status)}</div>
      <div class="task-kind">${esc(kindLabel(t.kind))}</div>
      <div class="small muted">${esc(t.room_type)} · Floor ${t.floor}${t.occupied ? ' · <b>guest in room</b>' : ''}</div>
      ${t.notes ? `<div class="task-notes pre">${esc(t.notes)}</div>` : ''}
      <div class="btn-row" style="margin-top:10px">
        ${t.status === 'open' ? `<button class="btn primary" data-start="${t.id}">${t.assigned_to ? 'Start' : 'Take & start'}</button>` : ''}
        ${t.status === 'in_progress' ? `<button class="btn good" data-done="${t.id}">Mark clean ✓</button>` : ''}
        <button class="btn sm" data-issue="${t.room_id}" data-room="${esc(t.room_number)}">Report issue</button>
        <button class="btn sm" data-lost="${t.room_id}" data-room="${esc(t.room_number)}">Found item</button></div></div>`;
  el.innerHTML = `<div class="page-head"><div class="grow"><h1>My rooms today</h1><div class="sub">${mine.length} assigned · ${pool.length} unassigned</div></div>
      <button class="btn" id="reload">Refresh</button></div>
    <h3 class="section-title">Assigned to me</h3><div class="task-grid">${mine.map(card).join('') || '<div class="card empty">No rooms assigned to you right now.</div>'}</div>
    ${pool.length ? `<h3 class="section-title">Unassigned — take one</h3><div class="task-grid">${pool.map(card).join('')}</div>` : ''}`;
  $('#reload', el).addEventListener('click', () => ctx.refresh());
  on(el, '[data-start]', 'click', async (e, b) => { if (await guarded(() => POST(`/housekeeping/tasks/${b.dataset.start}/start`), 'Task started')) ctx.refresh(); });
  on(el, '[data-done]', 'click', async (e, b) => {
    const v = await modal({ title: 'Finish cleaning', submit: 'Mark clean', body: textField('Notes for the supervisor (optional)', 'notes'), onSubmit: async (x) => x });
    if (v && await guarded(() => POST(`/housekeeping/tasks/${b.dataset.done}/complete`, v), 'Room marked clean')) ctx.refresh();
  });
  on(el, '[data-issue]', 'click', (e, b) => reportIssue(+b.dataset.issue, b.dataset.room));
  on(el, '[data-lost]', 'click', (e, b) => logLostItem(+b.dataset.lost, b.dataset.room, ctx));
}

export async function myHistoryView(el, { alive }) {
  const tasks = await GET('/housekeeping/history');
  if (!alive()) return;
  el.innerHTML = `<div class="page-head"><div class="grow"><h1>Completed work</h1></div></div><div class="card">${table(['Room', 'Task', 'Started', 'Finished', 'Status'],
    tasks.map((t) => `<tr><td>${esc(t.room_number)}</td><td>${esc(kindLabel(t.kind))}</td><td>${fmtDateTime(t.started_at)}</td><td>${fmtDateTime(t.completed_at)}</td><td>${badge(t.status)}</td></tr>`).join(''), 'Nothing completed yet')}</div>`;
}

export async function reportIssue(roomId, roomNumber) {
  const ok = await modal({ title: roomNumber ? `Report an issue — room ${roomNumber}` : 'Report a maintenance issue',
    body: `<div class="form-grid">${roomId ? `<input type="hidden" name="room_id" value="${roomId}">` : field('Location', 'location', '', 'placeholder="e.g. Lobby, kitchen, pool"', 'full')}
      ${field('What is wrong? *', 'title', '', 'placeholder="e.g. Leaking tap"', 'full')}${selectField('Priority', 'priority', PRIORITIES, 'normal')}${textField('Details', 'description')}</div>`,
    submit: 'Report', onSubmit: (v) => POST('/maintenance', v) });
  if (ok) toast('Issue reported to maintenance', 'success');
}

async function logLostItem(roomId, roomNumber, ctx) {
  const ok = await modal({ title: `Found item — room ${roomNumber}`, submit: 'Log item',
    body: `<input type="hidden" name="room_id" value="${roomId}">${field('Description *', 'description', '', 'placeholder="e.g. Black phone charger"')}${field('Where exactly?', 'location')}`,
    onSubmit: (v) => POST('/lost-found', v) });
  if (ok) { toast('Item logged in lost & found', 'success'); if (ctx) ctx.refresh(); }
}

// ====================================================================== maintenance
export async function maintenanceView(el, { params, ctx, alive }) {
  const status = params.status ?? 'active';
  const [tickets, rooms] = await Promise.all([GET('/maintenance?status=' + status), GET('/rooms')]);
  if (!alive()) return;
  const manage = ctx.can('maintenance.manage');
  el.innerHTML = `<div class="page-head"><div class="grow"><h1>Maintenance</h1><div class="sub">Repair tickets and out-of-order rooms.</div></div>
      <select id="st" style="width:auto">${options([['active', 'Open & in progress'], ['resolved', 'Resolved'], ['closed', 'Closed'], ['', 'All']], status)}</select>
      ${ctx.can('maintenance.report') ? '<button class="btn primary" id="new">+ Report issue</button>' : ''}</div>
    <div class="card">${table(['Ticket', 'Where', 'Issue', 'Priority', 'Status', 'Reported', ''], tickets.map((t) => `<tr>
      <td><b>${esc(t.code)}</b></td><td>${t.room_number ? 'Room ' + esc(t.room_number) : esc(t.location)}${t.out_of_order ? ' <span class="badge b-bad plain">OOO</span>' : ''}</td>
      <td>${esc(t.title)}${t.description ? `<div class="small muted">${esc(t.description)}</div>` : ''}${t.resolution ? `<div class="small text-good">✓ ${esc(t.resolution)}</div>` : ''}</td>
      <td>${badge(t.priority)}</td><td>${badge(t.status)}</td><td class="small">${fmtDateTime(t.created_at)}<br>${esc(t.reported_by_name || '')}</td>
      <td class="actions">${manage ? `<button class="btn sm" data-edit="${t.id}">Update</button>` : ''}</td></tr>`).join(''), 'No tickets')}</div>`;
  $('#st', el).addEventListener('change', (e) => { location.hash = '#/maintenance?status=' + e.target.value; });
  if ($('#new', el)) $('#new', el).addEventListener('click', async () => {
    const ok = await modal({ title: 'Report a maintenance issue', submit: 'Report',
      body: `<div class="form-grid">${selectField('Room', 'room_id', [['', '— Not a room —']].concat(rooms.map((r) => [r.id, r.number])), '')}${field('Or location', 'location')}
        ${field('Issue *', 'title', '', '', 'full')}${selectField('Priority', 'priority', PRIORITIES, 'normal')}${manage ? check('Take room out of order', 'out_of_order') : ''}${textField('Details', 'description')}</div>`,
      onSubmit: (v) => { v.room_id = v.room_id || null; return POST('/maintenance', v); } });
    if (ok) { toast('Ticket created', 'success'); ctx.refresh(); }
  });
  on(el, '[data-edit]', 'click', async (e, b) => {
    const t = tickets.find((x) => x.id === +b.dataset.edit);
    const ok = await modal({ title: `Update ${t.code}`,
      body: `<div class="form-grid">${selectField('Status', 'status', [['open', 'Open'], ['in_progress', 'In progress'], ['resolved', 'Resolved'], ['closed', 'Closed']], t.status)}
        ${selectField('Priority', 'priority', PRIORITIES, t.priority)}${t.room_id ? check('Room out of order', 'out_of_order', t.out_of_order, 'full') : ''}
        ${textField('Resolution / work done', 'resolution', t.resolution)}<div class="full small muted">Resolving releases the room and schedules a deep clean.</div></div>`,
      onSubmit: (v) => PUT('/maintenance/' + t.id, v) });
    if (ok) { toast('Ticket updated', 'success'); ctx.refresh(); }
  });
}

// ====================================================================== guest requests
export async function requestsView(el, { params, ctx, alive }) {
  const status = params.status ?? 'active';
  const list = await GET('/requests?status=' + status);
  if (!alive()) return;
  el.innerHTML = `<div class="page-head"><div class="grow"><h1>Guest requests</h1><div class="sub">Sent by guests from their online account.</div></div>
      <select id="st" style="width:auto">${options([['active', 'Open'], ['done', 'Done'], ['', 'All']], status)}</select></div>
    <div class="card">${table(['When', 'Room', 'Guest', 'Type', 'Request', 'Status', ''], list.map((q) => `<tr><td class="nowrap small">${fmtDateTime(q.created_at)}</td>
      <td>${esc(q.room_number)}</td><td><a href="#/reservations/${q.reservation_id}">${esc(q.guest_name)}</a></td><td>${esc(label(q.kind))}</td>
      <td>${esc(q.message)}${q.response ? `<div class="small text-good">↳ ${esc(q.response)}</div>` : ''}</td><td>${badge(q.status)}</td>
      <td class="actions">${['open', 'in_progress'].includes(q.status) ? `<button class="btn sm" data-r="${q.id}">Respond</button>` : ''}</td></tr>`).join(''), 'No requests')}</div>`;
  $('#st', el).addEventListener('change', (e) => { location.hash = '#/requests?status=' + e.target.value; });
  on(el, '[data-r]', 'click', async (e, b) => {
    const ok = await modal({ title: 'Respond to request', body: `${selectField('Status', 'status', [['in_progress', 'In progress'], ['done', 'Done'], ['cancelled', 'Cannot fulfil']], 'done')}
      ${field('Message to guest', 'response', '', 'placeholder="e.g. Pillows delivered to your room"')}`, onSubmit: (v) => POST('/requests/' + b.dataset.r, v) });
    if (ok) { toast('Request updated', 'success'); ctx.refresh(); }
  });
}

// ====================================================================== lost & found
export async function lostFoundView(el, { ctx, alive }) {
  const [items, rooms] = await Promise.all([GET('/lost-found'), GET('/rooms')]);
  if (!alive()) return;
  const manage = ctx.can('lostfound.manage');
  el.innerHTML = `<div class="page-head"><div class="grow"><h1>Lost &amp; found</h1></div>
      ${ctx.can('lostfound.report') ? '<button class="btn primary" id="new">+ Log item</button>' : ''}</div>
    <div class="card">${table(['Found', 'Item', 'Where', 'Last guest', 'Found by', 'Status', ''], items.map((i) => `<tr><td class="nowrap small">${fmtDateTime(i.found_at)}</td>
      <td><b>${esc(i.description)}</b>${i.notes ? `<div class="small muted">${esc(i.notes)}</div>` : ''}</td><td>${i.room_number ? 'Room ' + esc(i.room_number) : ''} ${esc(i.location)}</td>
      <td>${esc(i.guest_name || '—')}</td><td>${esc(i.found_by_name || '')}</td><td>${badge(i.status)}</td>
      <td class="actions">${manage && i.status === 'stored' ? `<button class="btn sm" data-close="${i.id}">Close</button>` : ''}</td></tr>`).join(''), 'Nothing logged')}</div>`;
  if ($('#new', el)) $('#new', el).addEventListener('click', async () => {
    const ok = await modal({ title: 'Log found item', submit: 'Log item',
      body: `<div class="form-grid">${field('Description *', 'description', '', '', 'full')}${selectField('Room', 'room_id', [['', '— Public area —']].concat(rooms.map((r) => [r.id, r.number])), '')}
        ${field('Location', 'location')}${field('Notes', 'notes', '', '', 'full')}</div>`, onSubmit: (v) => { v.room_id = v.room_id || null; return POST('/lost-found', v); } });
    if (ok) { toast('Item logged', 'success'); ctx.refresh(); }
  });
  on(el, '[data-close]', 'click', async (e, b) => {
    const ok = await modal({ title: 'Close item', body: `${selectField('Outcome', 'status', [['returned', 'Returned to owner'], ['disposed', 'Disposed / donated']], 'returned')}
      ${field('Notes', 'notes', '', 'placeholder="e.g. Collected by guest, ID checked"')}`, onSubmit: (v) => POST(`/lost-found/${b.dataset.close}/close`, v) });
    if (ok) { toast('Item closed', 'success'); ctx.refresh(); }
  });
}

// ====================================================================== reviews
export async function reviewsView(el, { ctx, alive }) {
  const { reviews, summary } = await GET('/reviews');
  if (!alive()) return;
  const stars = (n) => '★'.repeat(n) + '☆'.repeat(5 - n);
  el.innerHTML = `<div class="page-head"><div class="grow"><h1>Guest reviews</h1><div class="sub">Average ${summary.average || '—'} / 5 from ${summary.count} review(s). Published reviews appear on the website.</div></div></div>
    <div class="card">${table(['Date', 'Guest', 'Rating', 'Comment', 'Status', ''], reviews.map((r) => `<tr><td class="nowrap small">${fmtDate(r.created_at)}</td>
      <td>${esc(r.guest_name)}<div class="small muted">${esc(r.reservation_code)} · ${esc(r.room_type)}</div></td><td class="stars">${stars(r.rating)}</td>
      <td>${esc(r.comment)}${r.reply ? `<div class="small text-good">Reply: ${esc(r.reply)}</div>` : ''}</td><td>${r.published ? badge('clean', 'Published') : badge('pending', 'Hidden')}</td>
      <td class="actions"><button class="btn sm" data-m="${r.id}">Moderate</button></td></tr>`).join(''), 'No reviews yet')}</div>`;
  on(el, '[data-m]', 'click', async (e, b) => {
    const r = reviews.find((x) => x.id === +b.dataset.m);
    const ok = await modal({ title: 'Moderate review', body: `<p>"${esc(r.comment)}"</p>${check('Publish on the website', 'published', r.published)}${textField('Public reply', 'reply', r.reply)}`,
      onSubmit: (v) => PUT('/reviews/' + r.id, v) });
    if (ok) { toast('Review updated', 'success'); ctx.refresh(); }
  });
}
