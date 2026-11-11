// Language switch for the staff portals, and the Arabic overlay.
//
// Screens are written once, in English. When the user chooses Arabic, every piece of interface text
// (labels, buttons, table headings, messages, placeholders) is looked up in core/ar.js and replaced as it
// appears on screen, and the page switches to right-to-left. Hotel data — guest names, room numbers,
// item names, notes — is never in the dictionary, so it is shown exactly as entered.
let lang = 'en';
try { lang = localStorage.getItem('lang') === 'ar' ? 'ar' : 'en'; } catch (e) { /* storage unavailable */ }

export const getLang = () => lang;
export const isArabic = () => lang === 'ar';

export function applyDirection() {
  document.documentElement.lang = lang;
  document.documentElement.dir = lang === 'ar' ? 'rtl' : 'ltr';
}

export function toggleLang() {
  try { localStorage.setItem('lang', lang === 'ar' ? 'en' : 'ar'); } catch (e) { /* ignore */ }
  location.reload();
}

let dict = {};
let rules = [];
const cache = new Map();
const ATTRS = ['placeholder', 'title', 'aria-label'];
const SKIP = 'script, style, textarea, .secret, [data-no-translate]';

function lookup(key, depth = 0) {
  if (Object.prototype.hasOwnProperty.call(dict, key)) return dict[key];
  for (const [re, template] of rules) {
    const m = key.match(re);
    if (!m) continue;
    return template.replace(/\{\$(\d)\}|\$(\d)/g, (_, nested, plain) => {
      const part = m[nested || plain] || '';
      return nested ? (lookup(part, depth + 1) ?? part) : part;
    });
  }
  if (depth > 2) return null;
  // "Deluxe King · Clean", "Issue stock — Bath Towel": translate the parts we know, keep the rest.
  for (const sep of [' · ', ' — ']) {
    if (!key.includes(sep)) continue;
    const parts = key.split(sep);
    const done = parts.map((p) => lookup(p, depth + 1));
    if (done.some((d) => d !== null)) return done.map((d, i) => d ?? parts[i]).join(sep);
  }
  // "Breakfast included, non-refundable": only when every part is interface text, so data with commas is left alone.
  if (key.includes(', ')) {
    const done = key.split(', ').map((p) => lookup(p, depth + 1));
    if (done.every((d) => d !== null)) return done.join('، ');
  }
  const m = key.match(/^(.+) \(([^()]+)\)$/);   // "101 (Clean)", "Cleaning (1 low)"
  if (m) {
    const a = lookup(m[1], depth + 1);
    const b = lookup(m[2], depth + 1);
    if (a !== null || b !== null) return `${a ?? m[1]} (${b ?? m[2]})`;
  }
  return null;
}

/**
 * Arabic for a piece of interface text, or null when it is not interface text (hotel data, numbers).
 * A few English words mean different things in different places ("Open" the status vs. "Open" the button);
 * the dictionary can hold a second entry for those, marked "[button]" or "[th]" (table heading).
 */
export function translate(text, context = '') {
  if (lang !== 'ar' || !text) return null;
  const key = text.replace(/\s+/g, ' ').trim();
  if (!key || !/[A-Za-z]/.test(key)) return null;
  const marked = context && Object.prototype.hasOwnProperty.call(dict, `${key} [${context}]`) ? `${key} [${context}]` : key;
  if (!cache.has(marked)) cache.set(marked, lookup(marked));
  const out = cache.get(marked);
  if (out === null) return null;
  return text.match(/^\s*/)[0] + out + text.match(/\s*$/)[0];
}

function translateText(node) {
  const parent = node.parentElement;
  if (!parent || parent.closest(SKIP)) return;
  const context = parent.closest('button, a.btn') ? 'button' : parent.tagName === 'TH' ? 'th' : '';
  const out = translate(node.nodeValue, context);
  if (out !== null && out !== node.nodeValue) node.nodeValue = out;
}

function translateAttrs(el) {
  if (el.closest(SKIP)) return;
  for (const a of ATTRS) {
    if (!el.hasAttribute(a)) continue;
    const out = translate(el.getAttribute(a));
    if (out !== null && out !== el.getAttribute(a)) el.setAttribute(a, out);
  }
}

function translateTree(root) {
  if (root.nodeType === Node.TEXT_NODE) { translateText(root); return; }
  if (root.nodeType !== Node.ELEMENT_NODE) return;
  translateAttrs(root);
  root.querySelectorAll('[placeholder], [title], [aria-label]').forEach(translateAttrs);
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
  for (let n = walker.nextNode(); n; n = walker.nextNode()) translateText(n);
}

/** Call once at start-up. Does nothing in English; in Arabic it loads the dictionary and keeps the page translated. */
export async function startTranslator() {
  applyDirection();
  if (lang !== 'ar') return;
  const ar = await import('./ar.js');
  dict = ar.DICT;
  rules = ar.PATTERNS.map(([pattern, template]) => [new RegExp(pattern), template]);
  translateTree(document.body);
  new MutationObserver((changes) => {
    for (const c of changes) {
      if (c.type === 'childList') c.addedNodes.forEach(translateTree);
      else if (c.type === 'characterData') translateText(c.target);
      else translateAttrs(c.target);
    }
  }).observe(document.body, { childList: true, subtree: true, characterData: true, attributes: true, attributeFilter: ATTRS });
}
