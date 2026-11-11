// Browser tests for rate plans, guests changing their booking, paged lists, self-refreshing screens,
// Arabic server messages and the language used for e-mails. Same set-up as portals.test.js.
const test = require('node:test');
const assert = require('node:assert/strict');
const { execFileSync, spawn } = require('node:child_process');
const fs = require('node:fs');
const net = require('node:net');
const os = require('node:os');
const path = require('node:path');
const { chromium } = require('playwright');

const ROOT = path.resolve(__dirname, '..', '..');
const USERS = {
  admin: ['admin', 'AdminPass123', '/admin'],
  frontdesk: ['frontdesk', 'FrontDesk123', '/staff'],
  guest: ['amelia.hart@example.com', 'GuestPass123', '/account'],
};
let server, browser, base, tmp;

const freePort = () => new Promise((resolve, reject) => {
  const s = net.createServer();
  s.once('error', reject);
  s.listen(0, '127.0.0.1', () => { const { port } = s.address(); s.close(() => resolve(port)); });
});
const day = (n) => { const d = new Date(); d.setDate(d.getDate() + n); return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`; };
const number = (text) => parseFloat(text.replace(/[^0-9.]/g, ''));

/** Runs a one-line SQL query against the test database and returns the first column of the first row. */
function sql(query, ...args) {
  const code = 'import sqlite3, sys; row = sqlite3.connect(sys.argv[1]).execute(sys.argv[2], sys.argv[3:]).fetchone(); print(row[0] if row else "")';
  return execFileSync('python3', ['-c', code, path.join(tmp, 'hotel.db'), query, ...args], { encoding: 'utf8' }).trim();
}

async function open(lang = 'en') {
  const context = await browser.newContext({ viewport: { width: 1280, height: 900 } });
  await context.addInitScript((l) => { try { if (!localStorage.getItem('lang')) localStorage.setItem('lang', l); } catch (e) { /* ignore */ } }, lang);
  const page = await context.newPage();
  const problems = [];
  page.on('pageerror', (e) => problems.push(`script error: ${e.message}`));
  page.on('response', (r) => {
    if (r.status() >= 400 && !(r.url().endsWith('/api/auth/me') && r.status() === 401)) problems.push(`${r.status()} ${r.request().method()} ${r.url()}`);
  });
  return { context, page, problems };
}

async function signIn(page, who) {
  const [username, password, portal] = USERS[who] || who;
  await page.goto(base + '/login');
  await page.fill('input[name=username]', username);
  await page.fill('input[name=password]', password);
  await page.click('button.primary');
  await page.waitForURL((url) => url.pathname === portal);
  await page.waitForSelector(portal === '/account' ? '#view h1' : '#view .page-head, #view .card');
}

/** Calls the API as the signed-in user of this page. */
const api = (page, method, url, body) => page.evaluate(async ([m, u, b]) => {
  const { api: call } = await import('/js/core/api.js');
  return call(m, u, b);
}, [method, url, body]);

/** Registers a fresh guest through the sign-up form and lands on their (empty) account. */
async function register(page, email, lang = 'en') {
  await page.goto(base + '/login?register=1');
  await page.fill('input[name=first_name]', 'Test');
  await page.fill('input[name=last_name]', 'Traveller');
  await page.fill('input[name=email]', email);
  await page.fill('input[name=password]', 'Traveller-Pass-2026');
  await page.check('input[name=accept_privacy]');
  await page.click('#f button.primary');
  await page.waitForURL((url) => url.pathname === '/account');
  await page.waitForSelector('#view h1');
  assert.equal(await page.evaluate(() => document.documentElement.lang), lang);
}

/** Searches the website for a stay and waits for the offers. */
async function searchStay(page, from, to) {
  await page.goto(base + '/');
  await page.waitForSelector('#search');
  await page.fill('input[name=check_in]', day(from));
  await page.fill('input[name=check_out]', day(to));
  await page.click('#search button');
  await page.waitForSelector('.offer');
}

test.before(async () => {
  tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'hotel-browser-'));
  const port = await freePort();
  base = `http://127.0.0.1:${port}`;
  server = spawn('python3', ['run.py', '--port', String(port), '--db', path.join(tmp, 'hotel.db')], {
    cwd: ROOT, stdio: 'ignore',
    env: { ...process.env, HOTEL_BACKUP_DIR: path.join(tmp, 'backups'), HOTEL_BACKUP_HOURS: '0', HOTEL_PBKDF2_ITERATIONS: '2000', HOTEL_SEED_DEMO: '1' },
  });
  for (let i = 0; ; i++) {
    try { if ((await fetch(base + '/api/health')).ok) break; } catch (e) { /* not up yet */ }
    if (i > 100) throw new Error('The hotel server did not start');
    await new Promise((r) => setTimeout(r, 100));
  }
  browser = await chromium.launch();
});

test.after(async () => {
  if (browser) await browser.close();
  if (server) server.kill();
  fs.rmSync(tmp, { recursive: true, force: true });
});

test('rate plans: created by the admin, priced in the booking form, shown on the reservation', async () => {
  const { context, page, problems } = await open();
  await signIn(page, 'admin');
  await page.goto(base + '/admin#/rooms?tab=pricing');
  await page.waitForSelector('#add-plan');
  assert.match(await page.locator('#view').innerText(), /Bed & breakfast/);
  await page.click('#add-plan');
  await page.fill('.modal input[name=name]', 'Half board dinner');
  await page.selectOption('.modal select[name=meal_plan]', 'half_board');
  await page.fill('.modal input[name=per_adult]', '500');
  await page.click('.modal button[type=submit]');
  await page.waitForSelector('tr:has-text("Half board dinner")');
  assert.match(await page.locator('tr', { hasText: 'Half board dinner' }).innerText(), /Half board[\s\S]*\+500\.00/);

  // booking form: choosing the plan raises the nightly rate by the supplement
  await page.click('#top-action');
  await page.waitForSelector('.room-opt');
  await page.locator('.room-opt').first().click();
  const rate = () => page.locator('.modal input[name=rate]').inputValue().then(Number);
  await page.waitForFunction(() => +document.querySelector('.modal input[name=rate]').value > 0);
  const plain = await rate();
  const planId = await page.locator('.modal select[name=rate_plan_id] option', { hasText: 'Half board dinner' }).getAttribute('value');
  await page.selectOption('.modal select[name=rate_plan_id]', planId);
  await page.waitForFunction((before) => +document.querySelector('.modal input[name=rate]').value !== before, plain);
  assert.equal(await rate(), plain + 500);
  await page.fill('.modal input[name=first_name]', 'Plan');
  await page.fill('.modal input[name=last_name]', 'Tester');
  await page.click('.modal button[type=submit]');
  await page.waitForSelector('#plan-line');
  assert.equal(await page.locator('#plan-line').innerText(), 'Half board dinner · Half board');

  // deleting the plan leaves the booking as it was
  await page.goto(base + '/admin#/rooms?tab=pricing');
  await page.locator('tr', { hasText: 'Half board dinner' }).locator('[data-del-plan]').click();
  await page.click('.modal button[type=submit]');
  await page.waitForFunction(() => !document.querySelector('#view').textContent.includes('Half board dinner'));
  await page.goBack();
  await page.waitForSelector('#plan-line');
  assert.equal(await page.locator('#plan-line').innerText(), 'Half board dinner · Half board');
  assert.deepEqual(problems, []);
  await context.close();
});

test('website: a guest picks breakfast, then a non-refundable rate that cannot be cancelled or changed', async () => {
  const { context, page, problems } = await open();
  await register(page, 'plans.guest@example.com');
  await searchStay(page, 120, 122);
  const card = page.locator('.offer').first();
  const price = () => card.locator('[data-price]').innerText().then(number);
  const standard = await price();
  await card.locator('.rate-opt', { hasText: 'Bed & breakfast' }).locator('input').check();
  assert.ok(await price() > standard, 'breakfast costs more');
  const withBreakfast = await price();
  await card.locator('[data-book]').click();
  await page.waitForSelector('.modal');
  assert.match(await page.locator('.modal').innerText(), /Bed & breakfast · Breakfast included/);
  assert.match(await page.locator('.modal').innerText().then((t) => t.replace(/,/g, '')), new RegExp(withBreakfast.toFixed(2)));
  await page.click('.modal button[type=submit]');
  await page.waitForURL((url) => url.pathname === '/account' && url.hash.startsWith('#/stay/'));
  await page.waitForSelector('#plan');
  assert.equal(await page.locator('#plan').innerText(), 'Bed & breakfast · Breakfast included');
  assert.equal(await page.locator('#cancel').count(), 1);
  assert.equal(await page.locator('#change').count(), 1);

  await searchStay(page, 130, 132);
  const second = page.locator('.offer').first();
  await second.locator('.rate-opt', { hasText: 'Non-refundable saver' }).locator('input').check();
  assert.ok(number(await second.locator('[data-price]').innerText()) < standard, 'the saver rate is cheaper');
  await second.locator('[data-book]').click();
  await page.waitForSelector('.modal');
  await page.click('.modal button[type=submit]');
  await page.waitForURL((url) => url.pathname === '/account' && url.hash.startsWith('#/stay/'));
  await page.waitForSelector('#plan');
  assert.match(await page.locator('#plan').innerText(), /Non-refundable$/);
  assert.equal(await page.locator('#cancel').count(), 0);
  assert.equal(await page.locator('#change').count(), 0);
  assert.deepEqual(problems, []);
  await context.close();
});

test('guest account: change a booking — see the new price first, then confirm', async () => {
  const { context, page, problems } = await open();
  await register(page, 'change.guest@example.com');
  await searchStay(page, 140, 142);
  await page.locator('.offer [data-book]').first().click();
  await page.waitForSelector('.modal');
  await page.click('.modal button[type=submit]');
  await page.waitForURL((url) => url.hash.startsWith('#/stay/'));
  await page.waitForSelector('#change');
  const before = await page.locator('#view').innerText();

  await page.click('#change');
  await page.fill('.modal input[name=check_in]', day(150));
  await page.fill('.modal input[name=check_out]', day(149));           // nonsense first: the error shows in the dialog
  await page.click('.modal button[type=submit]');
  await page.waitForSelector('.modal .form-error:not(.hidden)');
  await page.fill('.modal input[name=check_out]', day(153));
  await page.click('.modal button[type=submit]');
  await page.waitForSelector('#new-total');
  const quoted = number(await page.locator('#new-total').innerText());
  assert.ok(quoted > 0);
  assert.equal(sql('SELECT check_in FROM reservations ORDER BY id DESC LIMIT 1'), day(140), 'nothing is saved before confirming');
  await page.click('.modal button[type=submit]');
  await page.waitForSelector('.toast.success');
  await page.waitForFunction((old) => document.querySelector('#view').innerText !== old, before);
  assert.equal(sql('SELECT check_in || " " || check_out FROM reservations ORDER BY id DESC LIMIT 1'), `${day(150)} ${day(153)}`);
  assert.match((await page.locator('#view').innerText()).replace(/,/g, ''), new RegExp(quoted.toFixed(2)), 'the bill shows the quoted total');
  assert.equal(sql("SELECT COUNT(*) FROM email_outbox WHERE to_address=? AND subject LIKE '%was changed'", 'change.guest@example.com'), '1');
  assert.deepEqual(problems.filter((p) => !p.includes('/change')), []);   // the deliberate bad dates above
  await context.close();
});

test('long lists are split into pages', async () => {
  const { context, page, problems } = await open();
  await signIn(page, 'admin');
  for (let i = 0; i < 6; i++) {
    await api(page, 'POST', '/guests', { first_name: 'Zz', last_name: `Paged${String(i).padStart(2, '0')}` });
  }
  execFileSync('python3', ['-c', 'import sqlite3, sys; db = sqlite3.connect(sys.argv[1]); '
    + 'db.executemany("INSERT INTO guests(first_name, last_name) VALUES (?, ?)", [("Bulk", "Row%03d" % i) for i in range(120)]); db.commit()',
  path.join(tmp, 'hotel.db')]);
  await page.goto(base + '/admin#/guests');
  await page.waitForSelector('.pager');
  assert.equal(await page.locator('#list tbody tr').count(), 50);
  assert.match(await page.locator('.pager').innerText(), /Page 1 of 3/);
  assert.ok(await page.locator('.pager [data-page]').first().isDisabled(), 'no "previous" on the first page');
  const first = await page.locator('#list tbody tr').first().innerText();
  await page.locator('.pager [data-page]').last().click();
  await page.waitForFunction(() => /Page 2 of 3/.test(document.querySelector('.pager').textContent));
  assert.notEqual(await page.locator('#list tbody tr').first().innerText(), first);
  // searching goes back to the first page of the matches
  await page.fill('#q', 'Paged0');
  await page.waitForFunction(() => document.querySelectorAll('#list tbody tr').length === 6);
  assert.match(await page.locator('.pager').innerText(), /Page 1 of 1 · 6 in total/);

  // (the demo hotel has no invoices yet, so that list has nothing to page)
  for (const [hash, selector] of [['reservations', '#list .pager'], ['audit', '.pager'], ['inventory?tab=movements', '#list .pager'], ['invoices', '#view table']]) {
    await page.goto(`${base}/admin#/${hash}`);
    await page.waitForSelector(selector);
  }
  await page.goto(base + '/admin#/audit');
  await page.waitForSelector('.pager');
  if (!(await page.locator('.pager [data-page]').last().isDisabled())) {
    await page.locator('.pager [data-page]').last().click();
    await page.waitForFunction(() => location.hash.includes('page=2'));
    await page.waitForFunction(() => /Page 2 of/.test((document.querySelector('.pager') || {}).textContent || ''));
  }
  assert.deepEqual(problems, []);
  await context.close();
});

test('the housekeeping board shows a new task by itself, but not while someone is filling a form', async () => {
  const { context, page, problems } = await open();
  await page.clock.install();
  await signIn(page, 'frontdesk');
  await page.goto(base + '/staff#/housekeeping');
  await page.waitForSelector('#view .page-head');
  const count = () => page.evaluate(() => document.querySelector('#view').textContent.split('Auto-refresh test task').length - 1);
  assert.equal(await count(), 0);
  const rooms = await api(page, 'GET', '/rooms');
  await api(page, 'POST', '/housekeeping/tasks', { room_id: rooms[rooms.length - 1].id, kind: 'deep_clean', notes: 'Auto-refresh test task' });
  assert.equal(await count(), 0, 'not there until the screen refreshes');
  await page.clock.fastForward(31000);
  await page.waitForFunction(() => document.querySelector('#view').textContent.includes('Auto-refresh test task'));

  // an open dialog pauses refreshing, so nothing a person is typing is lost
  await api(page, 'POST', '/housekeeping/tasks', { room_id: rooms[rooms.length - 2].id, kind: 'deep_clean', notes: 'Second test task' });
  await page.locator('#view button', { hasText: '+ Task' }).click();
  await page.waitForSelector('.modal');
  await page.clock.fastForward(31000);
  await page.waitForTimeout(300);
  assert.ok(!(await page.locator('#view').innerText()).includes('Second test task'));
  await page.keyboard.press('Escape');
  await page.clock.fastForward(31000);
  await page.waitForFunction(() => document.querySelector('#view').textContent.includes('Second test task'));
  assert.deepEqual(problems, []);
  await context.close();
});

test('Arabic: messages from the server are translated, for staff and for guests', async () => {
  const { context, page } = await open('ar');
  await signIn(page, 'admin');
  await page.goto(base + '/admin#/rooms?tab=types');
  await page.waitForSelector('[data-del-type]');
  await page.locator('tr', { hasText: 'Standard Single' }).locator('[data-del-type]').click();
  await page.click('.modal button[type=submit]');
  await page.waitForSelector('.toast.error');
  assert.equal(await page.locator('.toast.error').innerText(), 'ما زالت هناك غرف من هذا النوع');
  // a validation message with a field name in it
  await page.goto(base + '/admin#/guests');
  await page.waitForSelector('#new');
  await page.click('#new');
  await page.click('.modal button[type=submit]');
  await page.waitForSelector('.modal .form-error:not(.hidden)');
  assert.equal(await page.locator('.modal .form-error').innerText(), 'الاسم الأول: مطلوب');
  await context.close();

  const guest = await open('ar');
  await guest.page.goto(base + '/login');
  await guest.page.fill('input[name=username]', 'nobody@example.com');
  await guest.page.fill('input[name=password]', 'Wrong-Pass-123');
  await guest.page.click('button.primary');
  await guest.page.waitForSelector('#err:not(.hidden)');
  assert.equal(await guest.page.locator('#err').innerText(), 'اسم المستخدم أو كلمة المرور غير صحيحة');
  await guest.context.close();
});

test('e-mails follow the language the guest uses the site in', async () => {
  const { context, page } = await open('ar');
  await register(page, 'arabic.guest@example.com', 'ar');
  assert.equal(sql('SELECT language FROM guests WHERE email=?', 'arabic.guest@example.com'), 'ar');
  assert.equal(sql('SELECT subject FROM email_outbox WHERE to_address=? ORDER BY id DESC LIMIT 1', 'arabic.guest@example.com'), 'أكّد بريدك الإلكتروني');
  // statuses on the guest's own pages are in Arabic too
  await searchStay(page, 160, 162);
  await page.locator('.offer [data-book]').first().click();
  await page.waitForSelector('.modal');
  await page.click('.modal button[type=submit]');
  await page.waitForURL((url) => url.hash.startsWith('#/stay/'));
  await page.waitForSelector('#view .badge');
  assert.equal(await page.locator('#view h1 .badge').innerText(), 'محجوز');
  assert.match(sql('SELECT subject FROM email_outbox WHERE to_address=? ORDER BY id DESC LIMIT 1', 'arabic.guest@example.com'), /^تأكيد الحجز/);
  // switching to English is remembered for the next e-mail
  await page.click('#lang');
  await page.waitForFunction(() => document.documentElement.dir === 'ltr');
  await page.waitForSelector('#cancel');
  assert.equal(sql('SELECT language FROM guests WHERE email=?', 'arabic.guest@example.com'), 'en');
  await context.close();
});
