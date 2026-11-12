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
  await page.waitForFunction(() => !(document.querySelector('#view') || document.createElement('i')).textContent.includes('leaving.soon'));
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
  await page.waitForFunction(() => /No scans on file/.test((document.querySelector('#docs') || document.createElement('i')).textContent));
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
  await desk.page.waitForFunction((n) => +(document.querySelector('#bell-count') || document.createElement('i')).textContent === n + 1, before);
  await desk.page.click('#bell');
  await desk.page.waitForSelector('.bell-item.unread');
  const first = desk.page.locator('.bell-item').first();
  assert.match(await first.innerText(), /New guest request[\s\S]*An extra blanket please/);
  await first.click();
  await desk.page.waitForFunction(() => location.hash === '#/requests');
  await desk.page.waitForFunction(() => (document.querySelector('#view') || document.createElement('i')).textContent.includes('An extra blanket please'));
  await desk.page.waitForFunction((n) => (+(document.querySelector('#bell-count') || document.createElement('i')).textContent || 0) === n, before);
  assert.deepEqual(desk.problems, []);
  await desk.context.close();
});

test('the bell in Arabic, and "mark all as read"', async () => {
  const { context, page, problems } = await open('ar');
  await signIn(page, 'manager');
  await page.click('#bell');
  await page.waitForSelector('.bell-head');
  assert.match(await page.locator('.bell-head').innerText(), /الإشعارات/);
  await page.waitForFunction(() => /طلب نزيل جديد/.test((document.querySelector('#bell-panel') || document.createElement('i')).textContent));
  await page.click('#bell-all');
  await page.waitForFunction(() => document.querySelectorAll('.bell-item.unread').length === 0);
  assert.ok(!(await page.locator('#bell-count').isVisible()));
  assert.deepEqual(problems, []);
  await context.close();
});

test('extra beds and infants: on the website and in the booking form', async () => {
  const { day, number } = require('./support');
  const { context, page, problems } = await open();
  await signIn(page, 'guest');
  await page.goto(hotel.base + '/');
  await page.waitForSelector('#search');
  assert.match(await page.locator('#search').innerText(), /Infants \(under 6\)/);
  await page.fill('input[name=check_in]', day(250));
  await page.fill('input[name=check_out]', day(252));
  await page.fill('input[name=adults]', '2');
  await page.fill('input[name=children]', '1');
  await page.fill('input[name=infants]', '1');
  await page.click('#search button');
  await page.waitForSelector('.offer');
  const names = await page.$$eval('.offer h3', (hs) => hs.map((h) => h.textContent));
  assert.ok(!names.includes('Standard Double'), 'a room for two with no extra bed is not offered to three');
  const king = page.locator('.offer', { hasText: 'Deluxe King' });
  assert.match(await king.locator('[data-extra-beds]').innerText(), /incl\. 1 extra bed/);
  await king.locator('[data-book]').click();
  await page.waitForSelector('.modal');
  assert.match(await page.locator('.modal').innerText(), /2 \+ 1 · 1 infant\(s\), free · incl\. 1 extra bed/);
  await page.click('.modal button[type=submit]');
  await page.waitForURL((url) => url.hash.startsWith('#/stay/'));
  await page.waitForSelector('#plan');
  assert.match(await page.locator('#plan').innerText(), /incl\. 1 extra bed\(s\) · 1 infant\(s\), free/);
  assert.deepEqual(problems, []);
  await context.close();

  const desk = await open();
  await signIn(desk.page, 'frontdesk');
  await desk.page.click('#top-action');
  await desk.page.waitForSelector('.room-opt');
  await desk.page.selectOption('.modal select[name=type_id]', { label: await desk.page.locator('.modal select[name=type_id] option', { hasText: 'Deluxe King' }).innerText() });
  await desk.page.waitForFunction(() => [...document.querySelectorAll('.room-opt')].every((o) => o.textContent.includes('Deluxe King')));
  await desk.page.locator('.room-opt').first().click();
  await desk.page.waitForFunction(() => +(document.querySelector('.modal input[name=rate]') || { value: 0 }).value > 0);
  const plain = number(await desk.page.locator('.modal input[name=rate]').inputValue());
  await desk.page.fill('.modal input[name=adults]', '3');
  await desk.page.locator('.modal input[name=adults]').dispatchEvent('change');
  await desk.page.waitForFunction((before) => +(document.querySelector('.modal input[name=rate]') || { value: 0 }).value === before + 600, plain);
  assert.match(await desk.page.locator('#est').innerText(), /includes 1 extra bed\(s\)/);
  assert.deepEqual(desk.problems, []);
  await desk.context.close();
});
