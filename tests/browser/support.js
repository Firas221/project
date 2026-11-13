// Shared set-up for the browser tests: a throw-away server and database, sign-in, and small helpers.
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
  manager: ['manager', 'ManagerPass123', '/manager'],
  frontdesk: ['frontdesk', 'FrontDesk123', '/staff'],
  accountant: ['accountant', 'AccountPass123', '/finance'],
  chef: ['chef', 'ChefPass123', '/kitchen'],
  supervisor: ['supervisor', 'SuperPass123', '/housekeeping'],
  maid: ['maid', 'MaidPass123', '/housekeeping'],
  tech: ['tech', 'TechPass123', '/maintenance'],
  store: ['store', 'StorePass123', '/store'],
  waiter: ['waiter', 'WaiterPass123', '/restaurant'],
  guest: ['amelia.hart@example.com', 'GuestPass123', '/account'],
};

const hotel = { base: '', tmp: '', browser: null, server: null };

const freePort = () => new Promise((resolve, reject) => {
  const s = net.createServer();
  s.once('error', reject);
  s.listen(0, '127.0.0.1', () => { const { port } = s.address(); s.close(() => resolve(port)); });
});

/** Starts the hotel server on a fresh database and a browser. `env` adds or overrides HOTEL_* settings. */
async function start(env = {}) {
  hotel.tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'hotel-browser-'));
  const port = await freePort();
  hotel.base = `http://127.0.0.1:${port}`;
  hotel.server = spawn('python3', ['run.py', '--port', String(port), '--db', path.join(hotel.tmp, 'hotel.db')], {
    cwd: ROOT, stdio: 'ignore',
    env: { ...process.env, HOTEL_BACKUP_DIR: path.join(hotel.tmp, 'backups'), HOTEL_BACKUP_HOURS: '0', HOTEL_PBKDF2_ITERATIONS: '2000',
      HOTEL_SEED_DEMO: '1', ...env },
  });
  for (let i = 0; ; i++) {
    try { if ((await fetch(hotel.base + '/api/health')).ok) break; } catch (e) { /* not up yet */ }
    if (i > 100) throw new Error('The hotel server did not start');
    await new Promise((r) => setTimeout(r, 100));
  }
  hotel.browser = await chromium.launch();
}

async function stop() {
  if (hotel.browser) await hotel.browser.close();
  if (hotel.server) hotel.server.kill();
  fs.rmSync(hotel.tmp, { recursive: true, force: true });
}

/** A fresh browser profile, optionally in Arabic. `problems` collects script errors and failed requests. */
async function open(lang = 'en', viewport = { width: 1280, height: 900 }) {
  const context = await hotel.browser.newContext({ viewport });
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
  const [username, password, portal] = USERS[who] || who;
  await page.goto(hotel.base + '/login');
  await page.fill('input[name=username]', username);
  await page.fill('input[name=password]', password);
  await page.click('button.primary');
  await page.waitForURL((url) => url.pathname === portal);
  await page.waitForSelector(portal === '/account' ? '#view h1' : '#view .page-head, #view .card');
}

/** Waits until the current screen has finished loading. */
const settle = (page) => page.waitForFunction(() => {
  const v = document.querySelector('#view');
  return v && !/^(Loading…|جارٍ التحميل…|…)$/.test(v.textContent.trim());
});

/** Calls the API as the signed-in user of this page. */
const api = (page, method, url, body) => page.evaluate(async ([m, u, b]) => {
  const { api: call } = await import('/js/core/api.js');
  return call(m, u, b);
}, [method, url, body]);

/** Runs one SQL query against the test database; returns the first column of the first row. */
function sql(query, ...args) {
  const code = 'import sqlite3, sys; db = sqlite3.connect(sys.argv[1]); row = db.execute(sys.argv[2], sys.argv[3:]).fetchone(); db.commit(); print(row[0] if row else "")';
  return execFileSync('python3', ['-c', code, path.join(hotel.tmp, 'hotel.db'), query, ...args.map(String)], { encoding: 'utf8' }).trim();
}

const day = (n) => { const d = new Date(); d.setDate(d.getDate() + n); return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`; };
const number = (text) => parseFloat(String(text).replace(/[^0-9.]/g, ''));

/** A real PNG (a colour gradient) made without any imaging library; returns its path. */
function pngFile(name, width = 640, height = 420) {
  const chunk = (type, data) => {
    const body = Buffer.concat([Buffer.from(type), data]);
    const len = Buffer.alloc(4); len.writeUInt32BE(data.length);
    const sum = Buffer.alloc(4); sum.writeUInt32BE(zlib.crc32(body) >>> 0);
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
  const file = path.join(hotel.tmp, name);
  fs.writeFileSync(file, Buffer.concat([Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]),
    chunk('IHDR', header), chunk('IDAT', zlib.deflateSync(rows)), chunk('IEND', Buffer.alloc(0))]));
  return file;
}

module.exports = { USERS, hotel, start, stop, open, signIn, settle, api, sql, day, number, pngFile };
