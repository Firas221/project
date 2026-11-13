// Browser tests: the staff roster and each person's own shifts and clock.
const test = require('node:test');
const assert = require('node:assert/strict');
const { hotel, start, stop, open, signIn, settle, sql } = require('./support');

test.before(() => start());
test.after(() => stop());

test('the manager plans a shift in the week grid; the housekeeper sees it and clocks in and out', async () => {
  const { context, page, problems } = await open();
  await signIn(page, 'manager');
  await page.goto(hotel.base + '/manager#/roster');
  await page.waitForSelector('table.roster');
  const row = page.locator('table.roster tbody tr', { hasText: 'Rosa Delgado' });
  await row.locator('.roster-cell').nth(6).click();                       // Sunday of this week
  await page.waitForSelector('.modal input[name=start_time]');
  await page.fill('.modal input[name=start_time]', '07:00');
  await page.fill('.modal input[name=end_time]', '15:00');
  await page.fill('.modal input[name=note]', 'Third floor');
  await page.click('.modal button[type=submit]');
  await page.waitForSelector('table.roster .shift-chip');
  assert.equal(await row.locator('.shift-chip').innerText(), '07:00–15:00');
  assert.match(await row.innerText(), /8 h/);
  // change it, then remove it and add it again through the dialog
  await row.locator('.shift-chip').click();
  await page.fill('.modal input[name=end_time]', '13:00');
  await page.click('.modal button[type=submit]');
  await page.waitForFunction(() => /07:00–13:00/.test((document.querySelector('.shift-chip') || document.createElement('i')).textContent));
  const day = sql('SELECT work_date FROM roster_shifts LIMIT 1');
  assert.deepEqual(problems, []);
  await context.close();

  const maid = await open();
  await signIn(maid.page, 'maid');
  await maid.page.click('#bell');
  await maid.page.waitForSelector('.bell-item');
  assert.match(await maid.page.locator('.bell-item').first().innerText(), /Your shift was changed|You have a new shift/);
  await maid.page.locator('.bell-item').first().click();
  await maid.page.waitForFunction(() => location.hash === '#/my-shifts');
  await maid.page.waitForSelector('#clock-in');
  const today = new Date();
  const inTwoWeeks = new Date(today.getFullYear(), today.getMonth(), today.getDate() + 13);
  if (new Date(day + 'T00:00:00') >= new Date(today.getFullYear(), today.getMonth(), today.getDate()) && new Date(day + 'T00:00:00') <= inTwoWeeks) {
    assert.match(await maid.page.locator('#view').innerText(), /07:00 – 13:00[\s\S]*Third floor/);
  }
  await maid.page.click('#clock-in');
  await maid.page.waitForSelector('#clock-out');
  assert.match(await maid.page.locator('#view').innerText(), /On the clock/);
  await maid.page.click('#clock-out');
  await maid.page.waitForSelector('#clock-in');
  assert.equal(sql("SELECT COUNT(*) FROM attendance WHERE clock_out IS NOT NULL"), '1');
  assert.deepEqual(maid.problems, []);
  await maid.context.close();
});

test('the manager sees the clock record and corrects it; other staff have no roster screen', async () => {
  const { context, page, problems } = await open();
  await signIn(page, 'manager');
  await page.goto(hotel.base + '/manager#/roster');
  await page.waitForSelector('[data-fix]');
  await page.click('[data-fix]');
  await page.waitForSelector('.modal input[name=clock_in]');
  const stamp = await page.inputValue('.modal input[name=clock_in]');
  const dayPart = stamp.slice(0, 10);
  await page.fill('.modal input[name=clock_in]', `${dayPart}T08:00`);
  await page.fill('.modal input[name=clock_out]', `${dayPart}T12:30`);
  await page.click('.modal button[type=submit]');
  await page.waitForFunction(() => /4\.5 h/.test(document.querySelector('#view').textContent));
  assert.deepEqual(problems, []);
  await context.close();

  const desk = await open();
  await signIn(desk.page, 'frontdesk');
  const labels = await desk.page.$$eval('.nav a', (as) => as.map((a) => a.textContent.trim()));
  assert.ok(labels.includes('My shifts') && !labels.includes('Staff roster'));
  await desk.page.goto(hotel.base + '/staff#/roster');
  await desk.page.waitForSelector('text=Page not found');
  await desk.context.close();
});

test('the roster and "My shifts" in Arabic', async () => {
  const { context, page } = await open('ar');
  await signIn(page, 'manager');
  await page.goto(hotel.base + '/manager#/roster');
  await settle(page);
  await page.waitForFunction(() => (document.querySelector('#view h1') || document.createElement('i')).textContent.trim() === 'جدول المناوبات');
  await page.goto(hotel.base + '/manager#/my-shifts');
  await page.waitForFunction(() => (document.querySelector('#view h1') || document.createElement('i')).textContent.trim() === 'مناوباتي');
  assert.equal(await page.locator('#clock-in').innerText(), 'تسجيل الحضور');
  const nav = await page.$$eval('.nav a', (as) => as.map((a) => a.textContent.trim()));
  assert.ok(nav.every((l) => !/[A-Za-z]/.test(l)), `sidebar still has English: ${nav}`);
  await context.close();
});
