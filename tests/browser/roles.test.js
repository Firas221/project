// Browser tests for the manager, accountant, housekeeping supervisor, maintenance technician and storekeeper
// portals. Same set-up as portals.test.js (own server and database).
const test = require('node:test');
const assert = require('node:assert/strict');
const { spawn } = require('node:child_process');
const fs = require('node:fs');
const net = require('node:net');
const os = require('node:os');
const path = require('node:path');
const { chromium } = require('playwright');

const ROOT = path.resolve(__dirname, '..', '..');
// username, password, portal, role shown in the sidebar, screens the sidebar must list, screens it must not
const STAFF = {
  manager: ['manager', 'ManagerPass123', '/manager', 'Manager', ['Dashboard', 'Reservations', 'Rooms & rates', 'Reports', 'Night audit', 'Audit log'], ['Users', 'Settings', 'Roles & permissions']],
  accountant: ['accountant', 'AccountPass123', '/finance', 'Accountant', ['Reports', 'Tax invoices', 'Corporate accounts', 'Cashier', 'Reservations'], ['Dashboard', 'Housekeeping', 'Rooms & rates', 'Users']],
  supervisor: ['supervisor', 'SuperPass123', '/housekeeping', 'Housekeeping supervisor', ['Housekeeping board', 'Rooms', 'Lost & found', 'Supplies'], ['My rooms', 'Completed work', 'Reservations']],
  tech: ['tech', 'TechPass123', '/maintenance', 'Maintenance technician', ['Repair tickets', 'Rooms', 'Lost & found', 'Supplies'], ['Reservations', 'Guests', 'Inventory']],
  store: ['store', 'StorePass123', '/store', 'Storekeeper', ['Stock & purchasing', 'Report an issue'], ['Reservations', 'Guests', 'Reports']],
  frontdesk: ['frontdesk', 'FrontDesk123', '/staff'],
  admin: ['admin', 'AdminPass123', '/admin'],
};
let server, browser, base, tmp;

const freePort = () => new Promise((resolve, reject) => {
  const s = net.createServer();
  s.once('error', reject);
  s.listen(0, '127.0.0.1', () => { const { port } = s.address(); s.close(() => resolve(port)); });
});

async function open(lang = 'en') {
  const context = await browser.newContext({ viewport: { width: 1280, height: 900 } });
  await context.addInitScript((l) => { try { if (!localStorage.getItem('lang')) localStorage.setItem('lang', l); } catch (e) { /* ignore */ } }, lang);
  const page = await context.newPage();
  const problems = [];
  page.on('pageerror', (e) => problems.push(`script error: ${e.message}`));
  page.on('response', (r) => { if (r.status() >= 400) problems.push(`${r.status()} ${r.request().method()} ${r.url()}`); });
  return { context, page, problems };
}

async function signIn(page, who) {
  const [username, password, portal] = STAFF[who];
  await page.goto(base + '/login');
  await page.fill('input[name=username]', username);
  await page.fill('input[name=password]', password);
  await page.click('button.primary');
  await page.waitForURL((url) => url.pathname === portal);
  await page.waitForSelector('#view .page-head, #view .card');
}

const settle = (page) => page.waitForFunction(() => {
  const v = document.querySelector('#view');
  return v && !/^(Loading…|جارٍ التحميل…)$/.test(v.textContent.trim());
});
const api = (page, method, url, body) => page.evaluate(async ([m, u, b]) => {
  const { api: call } = await import('/js/core/api.js');
  return call(m, u, b);
}, [method, url, body]);

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

for (const who of ['manager', 'accountant', 'supervisor', 'tech', 'store']) {
  test(`${who}: lands on their own portal, sees only their screens, and every one of them renders`, async () => {
    const [, , portal, roleLabel, mustHave, mustNotHave] = STAFF[who];
    const { context, page, problems } = await open();
    await signIn(page, who);
    assert.match(await page.locator('.sidebar-foot').innerText(), new RegExp(roleLabel));
    const labels = await page.$$eval('.nav a', (as) => as.map((a) => a.textContent.trim()));
    for (const label of mustHave) assert.ok(labels.includes(label), `${who} should see "${label}" (has: ${labels})`);
    for (const label of mustNotHave) assert.ok(!labels.includes(label), `${who} should not see "${label}"`);
    for (const href of await page.$$eval('.nav a', (as) => as.map((a) => a.getAttribute('href')))) {
      await page.goto(base + portal + href);
      await settle(page);
      assert.equal(await page.locator('#view .form-error').count(), 0, `${href} shows an error`);
      assert.ok((await page.locator('#view').innerText()).trim().length > 0, `${href} is empty`);
    }
    assert.deepEqual(problems, []);
    // the administration portal stays closed to all of them
    await page.goto(base + '/admin');
    await page.waitForSelector('text=No access');
    await context.close();
  });
}

test('a ticket given to a technician shows up in their portal, and they close it', async () => {
  const desk = await open();
  await signIn(desk.page, 'frontdesk');
  await api(desk.page, 'POST', '/maintenance', { location: 'Pool', title: 'Browser test: pump noisy' });
  await desk.page.goto(base + '/staff#/maintenance');
  await desk.page.locator('tr', { hasText: 'pump noisy' }).locator('[data-edit]').click();
  await desk.page.waitForSelector('.modal');
  await desk.page.selectOption('.modal select[name=assigned_to]', { label: 'Tarek Aziz' });
  await desk.page.click('.modal button[type=submit]');
  await desk.page.waitForFunction(() => /Tarek Aziz/.test([...document.querySelectorAll('#view tr')].find((r) => r.textContent.includes('pump noisy')).textContent));
  await desk.context.close();

  const { context, page, problems } = await open();
  await signIn(page, 'tech');
  const row = page.locator('tr', { hasText: 'pump noisy' });
  assert.match(await row.getAttribute('class'), /row-mine/, 'tickets assigned to me are marked');
  await row.locator('[data-edit]').click();
  await page.waitForSelector('.modal');
  await page.selectOption('.modal select[name=status]', 'resolved');
  await page.fill('.modal textarea[name=resolution]', 'Bearing replaced');
  await page.click('.modal button[type=submit]');
  await page.waitForFunction(() => !document.querySelector('#view').textContent.includes('pump noisy'));   // off the open list
  assert.deepEqual(problems, []);
  await context.close();
});

test('closing the day: the manager can, the accountant can only look', async () => {
  const acc = await open();
  await signIn(acc.page, 'accountant');
  await acc.page.goto(base + '/finance#/night-audit');
  await settle(acc.page);
  assert.match(await acc.page.locator('#view').innerText(), /Only a manager or administrator can close the day/);
  assert.equal(await acc.page.locator('#view button.primary').count(), 0);
  await acc.context.close();

  const { context, page } = await open();
  await signIn(page, 'manager');
  await page.goto(base + '/manager#/night-audit');
  await settle(page);
  assert.equal(await page.locator('#view button.primary').count(), 1);
  assert.equal(await page.locator('.portal-switch').count(), 0, 'the manager has everything in one portal');
  await context.close();
});

test('the administrator creates a storekeeper and sees every role in the permission matrix; Arabic role names', async () => {
  const { context, page, problems } = await open();
  await signIn(page, 'admin');
  await page.goto(base + '/admin#/users');
  await page.waitForSelector('#view button.primary');
  await page.locator('#view button.primary').first().click();
  await page.waitForSelector('.modal');
  await page.fill('.modal input[name=username]', 'new.store');
  await page.fill('.modal input[name=full_name]', 'New Storekeeper');
  await page.selectOption('.modal select[name=role]', 'storekeeper');
  await page.click('.modal button[type=submit]');
  await page.waitForSelector('.secret');                                   // the one-time password
  await page.keyboard.press('Escape');
  await page.waitForSelector('tr:has-text("new.store")');
  assert.match(await page.locator('tr', { hasText: 'new.store' }).innerText(), /Storekeeper/);

  await page.goto(base + '/admin#/roles');
  await page.waitForSelector('table.matrix');
  const head = await page.locator('table.matrix thead').innerText();
  for (const role of ['Manager', 'Accountant', 'Housekeeping supervisor', 'Maintenance technician', 'Storekeeper', 'Front desk staff']) {
    assert.ok(head.includes(role), `the matrix has a column for ${role}`);
  }
  assert.match(await page.locator('table.matrix').innerText(), /Close the business day \(night audit\)/);
  assert.equal(await page.locator('[data-save]').count(), 8, 'eight roles can be tuned');
  assert.deepEqual(problems, []);
  await context.close();

  const ar = await open('ar');
  await signIn(ar.page, 'supervisor');
  await ar.page.waitForFunction(() => document.querySelector('.nav a').textContent.trim() === 'لوحة الإشراف الداخلي');
  assert.match(await ar.page.locator('.sidebar-foot').innerText(), /مشرف الإشراف الداخلي/);
  assert.equal(await ar.page.locator('.brand-sub').innerText(), 'الإشراف الداخلي');
  await ar.context.close();
});
