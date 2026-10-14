// Same-origin cookies carry credentials; only public session/CSRF metadata is visible to JS.
let sessionId = '';
let csrfToken = '';
let csrfRequest = null;
let identityRevision = 0;
let authTransition = Promise.resolve();

export function withAuthTransition(channel, action) {
  // Cookie mutations must not race across tabs: a late logout Set-Cookie could
  // otherwise erase the cookie just set by a newer login.
  if (typeof navigator !== 'undefined' && navigator.locks) return navigator.locks.request(channel, action);
  const pending = authTransition.then(action, action);
  authTransition = pending.catch(() => {});
  return pending;
}

export function setAuthSession(id = '', csrf = '') {
  identityRevision++;
  csrfRequest = null;
  sessionId = String(id || '');
  csrfToken = String(csrf || '');
}

export async function csrfHeaders(force = false) {
  if (force) csrfToken = '';
  if (!csrfToken) {
    if (!csrfRequest) {
      const revision = identityRevision;
      const pending = fetch('/api/auth/csrf', { credentials: 'same-origin', headers: { Accept: 'application/json' } })
        .then(async (response) => {
          const data = await response.json();
          if (!response.ok || !data.csrfToken) throw new Error('CSRF initialization failed');
          if (revision !== identityRevision) throw Object.assign(new Error('The signed-in account changed.'), {status:409,code:'session_changed'});
          csrfToken = data.csrfToken;
        }).finally(() => { if (csrfRequest === pending) csrfRequest = null; });
      csrfRequest = pending;
    }
    await csrfRequest;
  }
  return { 'X-CSRF-Token': csrfToken };
}

export async function authenticatedFetch(path, options = {}) {
  const method = String(options.method || 'GET').toUpperCase();
  const authPath = String(path).includes('/api/auth/');
  const captured = sessionId;
  const headers = new Headers(options.headers || {});
  headers.delete('Authorization');
  if (!['GET', 'HEAD', 'OPTIONS'].includes(method)) {
    for (const [key, value] of Object.entries(await csrfHeaders(String(path).endsWith('/login')))) headers.set(key, value);
  }
  if (captured !== sessionId && !authPath) throw Object.assign(new Error('The signed-in account changed.'), {status:409,code:'session_changed'});
  if (captured && !authPath) headers.set('X-Auth-Session', captured);
  const response = await fetch(path, { ...options, credentials: 'same-origin', headers });
  if (captured && captured !== sessionId && !authPath) {
    const error = new Error('The signed-in account changed.');
    error.status = 409;
    error.code = 'session_changed';
    throw error;
  }
  if ((response.status === 401 || response.headers.get('X-Session-Revoked') === '1') && !String(path).endsWith('/login') && !String(path).endsWith('/logout')) {
    if (typeof window !== 'undefined') window.dispatchEvent(new Event('auth-session-expired'));
  }
  return response;
}
