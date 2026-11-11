// Browser tests: deleting a user, scans of guest ID documents, and the alerts bell.
const test = require('node:test');
const assert = require('node:assert/strict');
const { hotel, start, stop, open, signIn, settle, api, pngFile } = require('./support');

test.before(() => start());
test.after(() => stop());

test('the administrator deletes a user from the Security dialog', async () => {
  const { context, page, problems } = await open();
  await signIn(page, 'admin');
  await api(page, 'POST', '/users', { username: 'leaving.soon', full_name: 'Leaving Soon', role: 'chef' });
  await page.goto(hotel.base + '/admin#/users');
  const row = page.locator('tr', { hasText: 'leaving.soon' });
  await row.locator('[data-more]').click();
  await page.waitForSelector('.modal [data-a=delete]');
  await page.click('.modal [data-a=delete]');
  await page.waitForSelector('.modal button[type=submit]');
  assert.match(await page.locator('.modal').innerText(), /leaving\.soon/);
  await page.click('.modal button[type=submit]');
  await page.waitForFunction(() => !document.querySelector('#view').textContent.includes('leaving.soon'));
  // you are not offered to delete yourself
  await page.locator('tr', { hasText: 'Alex Morgan' }).locator('[data-more]').click();
  await page.waitForSelector('.modal [data-a=unlock]');
  assert.equal(await page.locator('.modal [data-a=delete]').count(), 0);
  assert.deepEqual(problems, []);
  await context.close();
});

test('front desk uploads a passport scan, opens it, and deletes it', async () => {
  const { context, page, problems } = await open();
  await signIn(page, 'frontdesk');
  const guest = await api(page, 'POST', '/guests', { first_name: 'Scan', last_name: 'Tester' });
  await page.goto(`${hotel.base}/staff#/guests/${guest.id}`);
  await page.waitForSelector('#add-doc');
  assert.match(await page.locator('#docs').innerText(), /No scans on file/);
  await page.click('#add-doc');
  await page.click('.modal button[type=submit]');                              // no file chosen yet
  await page.waitForSelector('.modal .form-error:not(.hidden)');
  await page.setInputFiles('.modal input[type=file]', pngFile('passport.png', 900, 600));
  await page.click('.modal button[type=submit]');
  await page.waitForSelector('#docs a');
  assert.match(await page.locator('#docs a').innerText(), /Passport/);
  const href = await page.locator('#docs a').getAttribute('href');
  const scan = await page.evaluate(async (url) => {
    const r = await fetch(url);
    return { status: r.status, type: r.headers.get('content-type'), cache: r.headers.get('cache-control'), size: (await r.blob()).size };
  }, href);
  assert.deepEqual([scan.status, scan.type, scan.cache], [200, 'image/jpeg', 'no-store']);   // the browser shrank it to a JPEG
  assert.ok(scan.size > 1000);
  await page.click('[data-del-doc]');
  await page.click('.modal button[type=submit]');
  await page.waitForFunction(() => /No scans on file/.test(document.querySelector('#docs').textContent));
  assert.deepEqual(problems.filter((p) => !p.includes('/documents')), []);    // the deliberate empty upload
  await context.close();

  // someone signed out cannot fetch the file by its address
  const anon = await open();
  const response = await anon.page.goto(hotel.base + href);
  assert.equal(response.status(), 401);
  await anon.context.close();
});

test('the bell: a guest request appears for the front desk, and following it marks it read', async () => {
  const desk = await open();
  await desk.page.clock.install();
  await signIn(desk.page, 'frontdesk');
  await settle(desk.page);
  const count = () => desk.page.locator('#bell-count').innerText().then((t) => +t || 0);
  const before = await desk.page.locator('#bell-count').isVisible() ? await count() : 0;

  const guest = await open();
  await signIn(guest.page, 'guest');
  const stay = (await api(guest.page, 'GET', '/portal/reservations')).find((r) => r.status === 'checked_in');
  await api(guest.page, 'POST', `/portal/reservations/${stay.id}/requests`, { kind: 'amenity', message: 'An extra blanket please' });
  await guest.context.close();

  await desk.page.clock.fastForward(31000);                                     // the bell checks every 30 seconds
  await desk.page.waitForFunction((n) => +document.querySelector('#bell-count').textContent === n + 1, before);
  await desk.page.click('#bell');
  await desk.page.waitForSelector('.bell-item.unread');
  const first = desk.page.locator('.bell-item').first();
  assert.match(await first.innerText(), /New guest request[\s\S]*An extra blanket please/);
  await first.click();
  await desk.page.waitForFunction(() => location.hash === '#/requests');
  await desk.page.waitForFunction(() => document.querySelector('#view').textContent.includes('An extra blanket please'));
  await desk.page.waitForFunction((n) => (+document.querySelector('#bell-count').textContent || 0) === n, before);
  assert.deepEqual(desk.problems, []);
  await desk.context.close();
});

test('the bell in Arabic, and "mark all as read"', async () => {
  const { context, page, problems } = await open('ar');
  await signIn(page, 'manager');
  await page.click('#bell');
  await page.waitForSelector('.bell-head');
  assert.match(await page.locator('.bell-head').innerText(), /الإشعارات/);
  await page.waitForFunction(() => /طلب نزيل جديد/.test(document.querySelector('#bell-panel').textContent));
  await page.click('#bell-all');
  await page.waitForFunction(() => document.querySelectorAll('.bell-item.unread').length === 0);
  assert.ok(!(await page.locator('#bell-count').isVisible()));
  assert.deepEqual(problems, []);
  await context.close();
});
