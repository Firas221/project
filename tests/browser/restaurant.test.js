// Browser tests: the restaurant point of sale.
const test = require('node:test');
const assert = require('node:assert/strict');
const { hotel, start, stop, open, signIn, settle, api, sql, number } = require('./support');

test.before(() => start());
test.after(() => stop());

test('waiter: open a table, order, the kitchen marks it ready, pay by card and print the receipt', async () => {
  const { context, page, problems } = await open();
  await signIn(page, 'waiter');
  assert.equal(await page.locator('.brand-sub').innerText(), 'Restaurant');
  await page.waitForSelector('.table-card');
  assert.equal(await page.locator('.table-card.busy').count(), 0);
  await page.locator('.table-card', { hasText: 'Table 2' }).click();
  await page.fill('.modal input[name=covers]', '2');
  await page.click('.modal button[type=submit]');
  await page.waitForURL((url) => /#\/restaurant\/check\/\d+/.test(url.hash));
  await page.waitForSelector('.dish');
  await page.locator('.dish', { hasText: 'Classic Burger & Fries' }).click();
  await page.locator('.dish', { hasText: 'Classic Burger & Fries' }).click();
  await page.locator('.dish', { hasText: 'Espresso' }).click();
  assert.match(await page.locator('#pending-box').innerText(), /2 × Classic Burger & Fries[\s\S]*1 × Espresso/);
  await page.locator('#pending-box [data-less]').nth(1).click();           // changed their mind about the coffee
  assert.ok(!(await page.locator('#pending-box').innerText()).includes('Espresso'));
  await page.fill('#kitchen-note', 'No onions');
  await page.click('#send');
  await page.waitForFunction(() => /In the kitchen/.test((document.querySelector('#bill') || document.createElement('i')).textContent));
  const total = number(await page.locator('#check-total').innerText());
  assert.ok(total > 0);
  const checkUrl = page.url();

  const chef = await open();
  await signIn(chef.page, 'chef');
  await chef.page.goto(hotel.base + '/kitchen#/tickets');
  await chef.page.waitForSelector('.ticket');
  assert.match(await chef.page.locator('.ticket').innerText(), /Table 2[\s\S]*2 ×[\s\S]*Classic Burger & Fries[\s\S]*No onions/);
  await chef.page.click('[data-ready]');
  await chef.page.waitForFunction(() => /No dishes waiting/.test(document.querySelector('#view').textContent));
  assert.deepEqual(chef.problems, []);
  await chef.context.close();

  await page.reload();
  await page.waitForSelector('#bill .badge');
  assert.match(await page.locator('#bill').innerText(), /Ready/);
  await page.click('#bell');
  await page.waitForSelector('.bell-item');
  assert.match(await page.locator('.bell-item').first().innerText(), /A dish is ready[\s\S]*Table 2/);
  await page.keyboard.press('Escape');
  await page.goto(checkUrl);
  await page.waitForSelector('#pay');
  await page.click('#pay');
  await page.selectOption('.modal select[name=method]', 'card');
  await page.click('.modal button[type=submit]');
  await page.waitForURL((url) => /#\/restaurant\/receipt\/\d+/.test(url.hash));
  await page.waitForSelector('.receipt');
  const receipt = await page.locator('.receipt').innerText();
  assert.match(receipt, /RCP-\d{4}-000001/);
  assert.match(receipt, /Service charge 12%[\s\S]*VAT 14%/);
  assert.equal(number(receipt.split('Total').pop()), total);
  await page.goto(hotel.base + '/restaurant');
  await page.waitForSelector('.table-card');
  assert.equal(await page.locator('.table-card.busy').count(), 0, 'the table is free again');
  assert.deepEqual(problems, []);
  await context.close();
});

test('a check is charged to the room of a guest who is staying; the manager sets up tables', async () => {
  const mgr = await open();
  await signIn(mgr.page, 'manager');
  await mgr.page.goto(hotel.base + '/manager#/restaurant');
  await mgr.page.waitForSelector('#setup');
  await mgr.page.click('#setup');
  await mgr.page.fill('.modal input[name=name]', 'Pool bar 1');
  await mgr.page.fill('.modal input[name=area]', 'Pool');
  await mgr.page.click('#add-table');
  await mgr.page.waitForSelector('#tables-list tr:has-text("Pool bar 1")');
  await mgr.page.keyboard.press('Escape');
  await mgr.page.waitForSelector('.table-card:has-text("Pool bar 1")');
  assert.deepEqual(mgr.problems, []);
  await mgr.context.close();

  const { context, page, problems } = await open();
  await signIn(page, 'waiter');
  await page.locator('.table-card', { hasText: 'Pool bar 1' }).click();
  await page.click('.modal button[type=submit]');
  await page.waitForSelector('.dish');
  await page.locator('.dish', { hasText: 'Fresh Orange Juice' }).click();
  await page.click('#send');
  await page.waitForSelector('#to-room');
  await page.click('#to-room');
  await page.waitForSelector('.modal select[name=reservation_id] option', { state: 'attached' });
  const room = await page.locator('.modal select[name=reservation_id] option').first().innerText();
  await page.click('.modal button[type=submit]');
  await page.waitForFunction(() => location.hash === '#/restaurant');
  const charged = sql("SELECT description FROM charges WHERE description LIKE 'Restaurant %' ORDER BY id DESC LIMIT 1");
  assert.match(charged, /^Restaurant CK\w+ \(Pool bar 1\)$/);
  assert.ok(room.length > 3);
  assert.deepEqual(problems, []);
  await context.close();
});

test('the restaurant in Arabic', async () => {
  const { context, page } = await open('ar');
  await signIn(page, 'waiter');
  await settle(page);
  await page.waitForFunction(() => (document.querySelector('#view h1') || document.createElement('i')).textContent.trim() === 'المطعم');
  const nav = await page.$$eval('.nav a', (as) => as.map((a) => a.textContent.trim()));
  assert.ok(nav.every((l) => !/[A-Za-z]/.test(l)), `sidebar still has English: ${nav}`);
  assert.match(await page.locator('.table-card').first().innerText(), /طاولة 1[\s\S]*مقاعد[\s\S]*فارغة/);
  await context.close();
});
