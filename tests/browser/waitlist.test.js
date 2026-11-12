// Browser tests: the waiting list and the stop-sell dates.
const test = require('node:test');
const assert = require('node:assert/strict');
const { hotel, start, stop, open, signIn, settle, api, sql, day } = require('./support');

test.before(() => start());
test.after(() => stop());

test('waiting list: add a guest, a room frees up, book it from the list', async () => {
  const { context, page, problems } = await open();
  await signIn(page, 'frontdesk');
  const suite = (await api(page, 'GET', '/room-types')).find((t) => t.name === 'Presidential Suite');
  const free = await api(page, 'GET', `/availability?check_in=${day(300)}&check_out=${day(302)}&guests=1&type_id=${suite.id}`);
  const taken = [];
  for (const room of free) {
    taken.push(await api(page, 'POST', '/reservations', { guest: { first_name: 'Block', last_name: 'Er' }, room_id: room.id, check_in: day(300), check_out: day(302) }));
  }
  await page.goto(hotel.base + '/staff#/waitlist');
  await page.waitForSelector('#add');
  assert.match(await page.locator('#view').innerText(), /Nobody is waiting/);
  await page.click('#add');
  await page.fill('.modal input[name=name]', 'Wafaa Waiting');
  await page.fill('.modal input[name=phone]', '+20 111 222 3333');
  await page.fill('.modal input[name=check_in]', day(300));
  await page.fill('.modal input[name=check_out]', day(302));
  await page.selectOption('.modal select[name=room_type_id]', String(suite.id));
  await page.click('.modal button[type=submit]');
  await page.waitForSelector('tr:has-text("Wafaa Waiting")');
  const row = page.locator('tr', { hasText: 'Wafaa Waiting' });
  assert.match(await row.innerText(), /Still full/);
  assert.equal(await row.locator('[data-book]').count(), 0);

  await api(page, 'POST', `/reservations/${taken[0].id}/cancel`);
  await page.reload();
  await page.waitForSelector('tr:has-text("Wafaa Waiting") [data-book]');
  assert.match(await row.innerText(), /Room available/);
  await row.locator('[data-book]').click();
  await page.waitForSelector('.modal .room-opt');
  assert.equal(await page.inputValue('.modal input[name=check_in]'), day(300));
  assert.equal(await page.inputValue('.modal input[name=first_name]'), 'Wafaa');
  assert.equal(await page.inputValue('.modal input[name=phone]'), '+20 111 222 3333');
  await page.locator('.modal .room-opt').first().click();
  await page.waitForFunction(() => +document.querySelector('.modal input[name=rate]').value > 0);
  await page.click('.modal button[type=submit]');
  await page.waitForURL((url) => /#\/reservations\/\d+/.test(url.hash));
  assert.equal(sql("SELECT status FROM waitlist WHERE name='Wafaa Waiting'"), 'booked');
  await page.goto(hotel.base + '/staff#/waitlist?status=booked');
  await page.waitForSelector('tr:has-text("Wafaa Waiting") a');
  assert.deepEqual(problems, []);
  await context.close();
});

test('stop-sell: the admin closes dates, the website stops offering them and invites the guest to wait', async () => {
  const { context, page, problems } = await open();
  await signIn(page, 'admin');
  await page.goto(hotel.base + '/admin#/rooms?tab=pricing');
  await page.waitForSelector('#add-stop');
  assert.match(await page.locator('#view').innerText(), /The website sells every date/);
  await page.click('#add-stop');
  await page.fill('.modal input[name=start_date]', day(320));
  await page.fill('.modal input[name=end_date]', day(322));
  await page.fill('.modal input[name=reason]', 'Private event');
  await page.click('.modal button[type=submit]');
  await page.waitForSelector('tr:has-text("Private event")');
  assert.match(await page.locator('tr', { hasText: 'Private event' }).innerText(), /All room types/);
  assert.deepEqual(problems, []);
  await context.close();

  const guest = await open();
  await signIn(guest.page, 'guest');
  await guest.page.goto(hotel.base + '/');
  await guest.page.waitForSelector('#search');
  await guest.page.fill('input[name=check_in]', day(321));
  await guest.page.fill('input[name=check_out]', day(323));
  await guest.page.click('#search button');
  await guest.page.waitForSelector('#join-wl');
  assert.equal(await guest.page.locator('.offer').count(), 0);
  await guest.page.click('#join-wl');
  await guest.page.waitForFunction(() => /waiting list for these dates/.test(document.querySelector('#wl').textContent));
  await guest.page.goto(hotel.base + '/account');
  await guest.page.waitForSelector('#my-waitlist [data-leave]');
  await guest.page.click('#my-waitlist [data-leave]');
  await guest.page.waitForFunction(() => !document.querySelector('#my-waitlist'));
  assert.deepEqual(guest.problems, []);
  await guest.context.close();
});

test('the waiting list in Arabic', async () => {
  const { context, page } = await open('ar');
  await signIn(page, 'manager');
  await page.goto(hotel.base + '/manager#/waitlist');
  await settle(page);
  await page.waitForFunction(() => document.querySelector('#view h1').textContent.trim() === 'قائمة الانتظار');
  const headings = await page.$$eval('#view th', (ths) => ths.map((th) => th.textContent.trim()).filter(Boolean));
  assert.ok(headings.every((h) => !/[A-Za-z]/.test(h)), `still English: ${headings}`);
  await context.close();
});
