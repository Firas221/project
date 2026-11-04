// API client: JSON in/out, CSRF header on state-changing calls, uniform errors.
let csrfToken = null;

export class ApiError extends Error {
  constructor(message, status, field) {
    super(message);
    this.status = status;
    this.field = field;
  }
}

export function setCsrf(token) { csrfToken = token; }

export async function api(method, path, body) {
  const opts = { method, headers: {}, credentials: 'same-origin' };
  if (body !== undefined) {
    opts.headers['Content-Type'] = 'application/json';
    opts.body = JSON.stringify(body);
  }
  if (method !== 'GET' && csrfToken) opts.headers['X-CSRF-Token'] = csrfToken;
  let res;
  try {
    res = await fetch('/api' + path, opts);
  } catch (e) {
    throw new ApiError('Cannot reach the server. Check your connection.', 0);
  }
  let data = null;
  try { data = await res.json(); } catch (e) { /* no body */ }
  if (res.status === 401 && !path.startsWith('/auth/')) {
    window.dispatchEvent(new CustomEvent('auth:expired'));
  }
  if (!res.ok) throw new ApiError((data && data.error) || `Request failed (${res.status})`, res.status, data && data.field);
  return data;
}

export const GET = (p) => api('GET', p);
export const POST = (p, b) => api('POST', p, b || {});
export const PUT = (p, b) => api('PUT', p, b || {});
export const DEL = (p, b) => api('DELETE', p, b);

export function qs(obj) {
  return Object.entries(obj)
    .filter(([, v]) => v !== '' && v !== null && v !== undefined && v !== false)
    .map(([k, v]) => `${encodeURIComponent(k)}=${encodeURIComponent(v)}`).join('&');
}

/** Loads the current session (user, CSRF token, public settings). Throws ApiError(401) when signed out. */
export async function loadSession() {
  const me = await GET('/auth/me');
  setCsrf(me.csrf_token);
  return me;
}

export async function logout() {
  try { await api('POST', '/auth/logout', {}); } catch (e) { /* ignore */ }
  setCsrf(null);
}
