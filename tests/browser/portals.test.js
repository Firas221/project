// Browser tests: drive the real portals in headless Chromium against a throw-away server and database.
//
//   npm install && npx playwright install chromium      (once)
//   npm run test:browser
//
// The Python tests in tests/*.py cover the API; these cover what only a browser can show:
// that every screen renders, buttons do what they say, and the Arabic / right-to-left mode works.
const test = require('node:test');
const assert = require('node:assert/strict');
const { execFileSync, spawn } = require('node:child_process');
const fs = require('node:fs');
const net = require('node:net');
const os = require('node:os');
const path = require('node:path');
const zlib = require('node:zlib');
const { chromium } = require('playwright');

const ROOT = path.resolve(__dirname, '..', '..');
const USERS = {
  admin: ['admin', 'AdminPass123', '/admin'],
  frontdesk: ['frontdesk', 'FrontDesk123', '/staff'],
  chef: ['chef', 'ChefPass123', '/kitchen'],
  maid: ['maid', 'MaidPass123', '/housekeeping'],
  guest: ['amelia.hart@example.com', 'GuestPass123', '/account'],
};

let server, browser, base, tmp;

function freePort() {
  return new Promise((resolve, reject) => {
    const s = net.createServer();
    s.once('error', reject);
    s.listen(0, '127.0.0.1', () => { const { port } = s.address(); s.close(() => resolve(port)); });
  });
}

/** A real PNG (a colour gradient) made without any imaging library. */
function pngFile(name, width = 640, height = 420) {
  const crc = (buf) => zlib.crc32(buf) >>> 0;
  const chunk = (type, data) => {
    const body = Buffer.concat([Buffer.from(type), data]);
    const len = Buffer.alloc(4); len.writeUInt32BE(data.length);
    const sum = Buffer.alloc(4); sum.writeUInt32BE(crc(body));
    return Buffer.concat([len, body, sum]);
  };
  const header = Buffer.alloc(13);
  header.writeUInt32BE(width, 0); header.writeUInt32BE(height, 4); header.set([8, 2, 0, 0, 0], 8);
  const rows = Buffer.alloc((width * 3 + 1) * height);
  for (let y = 0; y < height; y++) {
    for (let x = 0; x < width; x++) {
      const o = y * (width * 3 + 1) + 1 + x * 3;
      rows[o] = 30 + Math.round(200 * x / width); rows[o + 1] = 90 + Math.round(120 * y / height); rows[o + 2] = 170;
    }
  }
  const file = path.join(tmp, name);
  fs.writeFileSync(file, Buffer.concat([Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]),
    chunk('IHDR', header), chunk('IDAT', zlib.deflateSync(rows)), chunk('IEND', Buffer.alloc(0))]));
  return file;
}

/** Opens a fresh browser profile, optionally in Arabic, and records anything that goes wrong on the page. */
async function open(lang = 'en', viewport = { width: 1280, height: 850 }) {
  const context = await browser.newContext({ viewport });
  await context.addInitScript((l) => { try { if (!localStorage.getItem('lang')) localStorage.setItem('lang', l); } catch (e) { /* ignore */ } }, lang);
  const page = await context.newPage();
  const problems = [];
  page.on('pageerror', (e) => problems.push(`script error: ${e.message}`));
  page.on('response', (r) => {
    const expected = r.url().endsWith('/api/auth/me') && r.status() === 401;   // "am I signed in?" on public pages
    if (r.status() >= 400 && !expected) problems.push(`${r.status()} ${r.request().method()} ${r.url()}`);
  });
  return { context, page, problems };
}

async function signIn(page, who) {
  const [username, password, portal] = USERS[who];
  await page.goto(base + '/login');
  await page.fill('input[name=username]', username);
  await page.fill('input[name=password]', password);
  await page.click('button.primary');
  await page.waitForURL((url) => url.pathname === portal);
  await page.waitForSelector(who === 'guest' ? '#view h1' : '#view .page-head, #view .card, #view .empty');
}

/** Reads the newest confirmation link from the outbox, as the guest would from their inbox. */
function confirmationToken(email) {
  const code = "import sqlite3, sys, re; db = sqlite3.connect(sys.argv[1]); "
    + "body = db.execute(\"SELECT body FROM email_outbox WHERE to_address=? AND subject LIKE 'Confirm%' ORDER BY id DESC LIMIT 1\", (sys.argv[2],)).fetchone()[0]; "
    + "print(re.search(r'#verify=([A-Za-z0-9_-]+)', body).group(1))";
  return execFileSync('python3', ['-c', code, path.join(tmp, 'hotel.db'), email], { encoding: 'utf8' }).trim();
}

const settle = (page) => page.waitForFunction(() => {
  const v = document.querySelector('#view');
  return v && !/^(Loading…|جارٍ التحميل…|…)$/.test(v.textContent.trim());
});

test.before(async () => {
  tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'hotel-browser-'));
  const port = await freePort();
  base = `http://127.0.0.1:${port}`;
  server = spawn('python3', ['run.py', '--port', String(port), '--db', path.join(tmp, 'hotel.db')], {
    cwd: ROOT, stdio: 'ignore',
    // An SMTP host makes the server enforce e-mail confirmation; ".invalid" never resolves, so nothing is sent.
    env: { ...process.env, HOTEL_BACKUP_DIR: path.join(tmp, 'backups'), HOTEL_BACKUP_HOURS: '0', HOTEL_PBKDF2_ITERATIONS: '2000',
      HOTEL_SEED_DEMO: '1', HOTEL_SMTP_HOST: 'smtp.invalid' },
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

for (const who of ['admin', 'frontdesk', 'chef', 'maid']) {
  test(`${who}: every screen in the sidebar renders without errors`, async () => {
    const { context, page, problems } = await open();
    await signIn(page, who);
    const links = await page.$$eval('.nav a', (as) => as.map((a) => a.getAttribute('href')));
    assert.ok(links.length >= 5, 'the sidebar lists the portal screens');
    for (const href of links) {
      await page.goto(base + USERS[who][2] + href);
      await settle(page);
      assert.equal(await page.locator('#view .form-error').count(), 0, `${href} shows an error`);
      assert.ok((await page.locator('#view').innerText()).trim().length > 0, `${href} is empty`);
    }
    assert.deepEqual(problems, []);
    await context.close();
  });
}

test('staff are kept out of portals that are not theirs', async () => {
  const { context, page } = await open();
  await signIn(page, 'maid');
  await page.goto(base + '/admin');
  await page.waitForSelector('text=No access');
  assert.match(await page.locator('body').innerText(), /cannot open the Administration portal/);
  await context.close();
});

test('Arabic: the staff portal switches to right-to-left and translates the interface, not the data', async () => {
  const { context, page, problems } = await open();
  await signIn(page, 'admin');
  assert.equal(await page.evaluate(() => document.documentElement.dir), 'ltr');
  assert.equal(await page.locator('#lang-toggle').innerText(), 'العربية');
  await page.click('#lang-toggle');
  await page.waitForFunction(() => document.documentElement.dir === 'rtl');
  await settle(page);
  await page.waitForFunction(() => (document.querySelector('.nav a') || document.createElement('i')).textContent.trim() === 'لوحة المتابعة');
  const nav = await page.$$eval('.nav a', (as) => as.map((a) => a.textContent.trim()));
  assert.ok(nav.includes('الحجوزات') && nav.includes('الإعدادات'), 'sidebar is in Arabic');
  assert.ok(nav.every((label) => !/[A-Za-z]/.test(label)), `sidebar still has English: ${nav}`);
  assert.equal(await page.locator('.brand-name').innerText(), 'فندق نايل هاربور');

  await page.goto(base + '/admin#/reservations');
  await page.waitForSelector('#view tbody tr.clickable');
  const headings = await page.$$eval('#view th', (ths) => ths.map((th) => th.textContent.trim()).filter(Boolean));
  assert.ok(headings.length > 4 && headings.every((h) => !/[A-Za-z]/.test(h)), `table headings still have English: ${headings}`);
  assert.match(await page.locator('#view').innerText(), /Amelia Hart/, 'guest names stay as they were entered');
  assert.match(await page.locator('#view').innerText(), /محجوز|تم تسجيل الوصول/, 'statuses are translated');

  // dialogs opened later are translated too, including placeholders
  await page.click('#top-action');
  await page.waitForSelector('.modal');
  assert.equal(await page.locator('.modal h2').innerText(), 'حجز جديد');
  assert.match(await page.locator('.modal').innerText(), /الاسم الأول/);
  await page.keyboard.press('Escape');

  // the choice is remembered, and English comes back the same way
  await page.reload();
  await settle(page);
  assert.equal(await page.evaluate(() => document.documentElement.dir), 'rtl');
  await page.click('#lang-toggle');
  await page.waitForFunction(() => document.documentElement.dir === 'ltr');
  await settle(page);
  assert.equal(await page.locator('.nav a').first().innerText(), 'Dashboard');
  assert.deepEqual(problems, []);
  await context.close();
});

test('Arabic: every staff portal opens on a phone-sized screen', async () => {
  for (const who of ['frontdesk', 'chef', 'maid']) {
    const { context, page, problems } = await open('ar', { width: 390, height: 800 });
    await signIn(page, who);
    assert.equal(await page.evaluate(() => document.documentElement.dir), 'rtl');
    await page.click('#menu-btn');
    await page.waitForSelector('#sidebar.open');
    const box = await page.locator('#sidebar').boundingBox();
    assert.ok(box.x + box.width > 380, 'the menu slides in from the right in Arabic');
    assert.ok((await page.$$eval('.nav a', (as) => as.map((a) => a.textContent.trim()))).every((l) => !/[A-Za-z]/.test(l)));
    assert.deepEqual(problems, []);
    await context.close();
  }
});

test('room photos: upload in the admin portal, shown on the booking website', async () => {
  const { context, page, problems } = await open();
  await signIn(page, 'admin');
  await page.goto(base + '/admin#/rooms?tab=types');
  await settle(page);
  await page.locator('[data-photos]').first().click();
  await page.waitForSelector('.modal');
  assert.match(await page.locator('.modal').innerText(), /No photos yet/);
  await page.setInputFiles('#pick', [pngFile('one.png'), pngFile('two.png', 500, 500)]);
  await page.waitForFunction(() => document.querySelectorAll('.photo').length === 2);
  assert.equal(await page.locator('.photo .badge').count(), 1, 'exactly one cover photo');
  const coverBefore = await page.locator('.photo img').first().getAttribute('src');
  await page.locator('[data-cover]').click();
  await page.waitForFunction((src) => (document.querySelector('.photo img') || document.createElement('i')).getAttribute('src') !== src, coverBefore);
  await page.keyboard.press('Escape');
  await page.waitForFunction(() => /\(2\)/.test((document.querySelector('[data-photos]') || {}).textContent || ''));

  const site = await context.newPage();
  await site.goto(base + '/');
  await site.waitForSelector('.room-photo img');
  assert.ok(await site.locator('.room-photo img').first().evaluate((img) => img.complete && img.naturalWidth > 0), 'the photo loads');
  assert.equal(await site.locator('.room-photo .thumbs button').count(), 2);
  const shown = await site.locator('.room-photo > img').getAttribute('src');
  await site.locator('.room-photo .thumbs button').nth(1).click();
  assert.notEqual(await site.locator('.room-photo > img').getAttribute('src'), shown, 'thumbnails switch the photo');

  // deleting brings the letter tile back
  await page.locator('[data-photos]').first().click();
  await page.waitForSelector('.photo');
  await page.locator('[data-rm]').first().click();
  await page.waitForFunction(() => document.querySelectorAll('.photo').length === 1);
  await page.locator('[data-rm]').first().click();
  await page.waitForSelector('.modal .empty');
  assert.deepEqual(problems, []);
  await context.close();
});

test('delete buttons: promo code, season, room type and guest', async () => {
  const { context, page, problems } = await open();
  await signIn(page, 'admin');
  const api = (method, url, body) => page.evaluate(async ([m, u, b]) => {
    const { api: call } = await import('/js/core/api.js');
    return call(m, u, b);
  }, [method, url, body]);
  const today = new Date().toISOString().slice(0, 10);
  await api('POST', '/promos', { code: 'BROWSERTEST', discount_pct: 5, valid_from: today, valid_to: today });
  await api('POST', '/seasons', { name: 'Browser season', start_date: today, end_date: today, adjust_pct: 5 });
  await api('POST', '/room-types', { name: 'Browser type', base_rate: 100, capacity: 2 });
  const guest = await api('POST', '/guests', { first_name: 'Browser', last_name: 'Deleteme' });

  const confirmDelete = async () => { await page.click('.modal button[type=submit]'); await page.waitForSelector('.modal', { state: 'detached' }); };
  await page.goto(base + '/admin#/rooms?tab=pricing');
  await settle(page);
  await page.locator('tr', { hasText: 'BROWSERTEST' }).locator('[data-del-promo]').click();
  await confirmDelete();
  await page.waitForFunction(() => !(document.querySelector('#view') || document.createElement('i')).textContent.includes('BROWSERTEST'));
  await page.locator('tr', { hasText: 'Browser season' }).locator('[data-del-season]').click();
  await confirmDelete();
  await page.waitForFunction(() => !(document.querySelector('#view') || document.createElement('i')).textContent.includes('Browser season'));

  await page.goto(base + '/admin#/rooms?tab=types');
  await settle(page);
  await page.locator('tr', { hasText: 'Browser type' }).locator('[data-del-type]').click();
  await confirmDelete();
  await page.waitForFunction(() => !(document.querySelector('#view') || document.createElement('i')).textContent.includes('Browser type'));
  // a type that still has rooms is refused, with the reason shown
  await page.locator('tr', { hasText: 'Standard Single' }).locator('[data-del-type]').click();
  await page.click('.modal button[type=submit]');
  await page.waitForSelector('.toast.error');
  assert.match(await page.locator('.toast.error').innerText(), /Rooms still use this type/);

  await page.goto(`${base}/admin#/guests/${guest.id}`);
  await settle(page);
  await page.click('#delete');
  await confirmDelete();
  await page.waitForFunction(() => location.hash === '#/guests');
  // guests with stays get no delete button (their data is erased instead)
  await page.goto(base + '/admin#/guests');
  await settle(page);
  await page.locator('tr.clickable', { hasText: 'Hart' }).click();
  await page.waitForSelector('#erase');
  assert.equal(await page.locator('#delete').count(), 0);
  assert.deepEqual(problems.filter((p) => !p.includes('409')), []);   // the refused delete above is the only failure
  await context.close();
});

test('settings: automatic night audit, e-mail confirmation and backup restore controls', async () => {
  const { context, page, problems } = await open();
  await signIn(page, 'admin');
  await page.goto(base + '/admin#/settings');
  await settle(page);
  await page.check('input[name=auto_night_audit]');
  await page.fill('input[name=night_audit_time]', '04:30');
  await page.click('#f button.primary');
  await page.waitForSelector('.toast.success');
  await page.reload();
  await settle(page);
  assert.ok(await page.isChecked('input[name=auto_night_audit]'));
  assert.equal(await page.inputValue('input[name=night_audit_time]'), '04:30');
  assert.ok(await page.isChecked('input[name=require_email_verification]'));

  await page.click('#bk');
  await page.waitForSelector('[data-restore]');
  await page.locator('[data-restore]').first().click();
  await page.waitForSelector('.modal');
  await page.fill('.modal input[name=password]', 'not-my-password');
  await page.click('.modal button[type=submit]');
  await page.waitForSelector('.modal .form-error:not(.hidden)');
  assert.match(await page.locator('.modal .form-error').innerText(), /Password is incorrect/);
  await page.fill('.modal input[name=password]', 'AdminPass123');
  await page.click('.modal button[type=submit]');
  await page.waitForSelector('text=Backup restored');
  await page.click('.modal [data-close]');
  await page.waitForURL((url) => url.pathname === '/login');
  assert.deepEqual(problems.filter((p) => !p.includes('/backups/restore')), []);   // the wrong password above
  await context.close();
});

test('guest website: search, book and see the booking, in English and Arabic', async () => {
  const { context, page, problems } = await open();
  await signIn(page, 'guest');
  await page.goto(base + '/');
  await page.waitForSelector('#search');
  const day = (n) => { const d = new Date(); d.setDate(d.getDate() + n); return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`; };
  await page.fill('input[name=check_in]', day(200));
  await page.fill('input[name=check_out]', day(202));
  await page.click('#search button');
  await page.waitForSelector('.offer');
  await page.locator('.offer [data-book]').first().click();
  await page.waitForSelector('.modal');
  await page.click('.modal button[type=submit]');
  await page.waitForURL((url) => url.pathname === '/account' && url.hash.startsWith('#/stay/'));
  await page.waitForSelector('#cancel');
  await page.click('#lang');
  await page.waitForFunction(() => document.documentElement.dir === 'rtl');
  await page.waitForSelector('#cancel');
  assert.equal(await page.locator('#cancel').innerText(), 'إلغاء الحجز');
  assert.deepEqual(problems, []);
  await context.close();
});

test('new guests confirm their e-mail address before they can use their account', async () => {
  const { context, page } = await open();
  await page.goto(base + '/login?register=1');
  await page.fill('input[name=first_name]', 'Nadia');
  await page.fill('input[name=last_name]', 'Browser');
  await page.fill('input[name=email]', 'nadia.browser@example.com');
  await page.fill('input[name=password]', 'Nadia-Pass-2026');
  await page.check('input[name=accept_privacy]');
  await page.click('#f button.primary');
  await page.waitForURL((url) => url.pathname === '/account');
  await page.waitForSelector('#resend');
  assert.match(await page.locator('#view').innerText(), /nadia\.browser@example\.com/);
  assert.equal(await page.locator('.site-head nav a').count(), 0, 'no way into bookings or profile yet');

  await page.goto(base + '/login#verify=not-a-real-token');
  await page.waitForSelector('#err:not(.hidden)');
  assert.match(await page.locator('#err').innerText(), /invalid or has expired/);

  await page.goto(base + '/account');
  await page.click('#resend');
  await page.waitForSelector('.toast.success');
  await page.goto(`${base}/login#verify=${confirmationToken('nadia.browser@example.com')}`);
  await page.waitForSelector('a[href="/account"]');
  await page.click('a[href="/account"]');
  await page.waitForSelector('#view h1');
  assert.equal(await page.locator('#resend').count(), 0);
  assert.ok(await page.locator('.site-head nav a').count() >= 3, 'the account is open');
  await context.close();
});
