import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { errorMessage, localizeError, responseError, retryAfterSeconds } from './adminErrors.js';
import { request } from '../api.js';
import { setAuthSession, csrfHeaders } from '../authTransport.js';
import { createNotificationStorage } from '../notifications/storage.js';

const hasChinese = value => /[\u3400-\u9fff]/u.test(value);

test('HTTP and code fallbacks are Chinese and retain metadata', () => {
  for (const [status, code] of [[401, 'auth_error'], [403, 'forbidden'], [409, 'conflict'],
    [429, 'rate_limited'], [429, 'export_capacity'], [429, 'export_in_progress'],
    [504, 'export_timeout'], [500, 'unknown']]) {
    const data = { code, message: 'Server returned an error', detail: 7 };
    const error = responseError(status, data, '6');
    assert.ok(hasChinese(error.message), `${status} ${code}: ${error.message}`);
    assert.equal(error.status, status); assert.equal(error.code, code);
    assert.equal(error.retryAfter, 6); assert.equal(error.data, data);
  }
  const data = { code: 'conflict', message: '商品 SKU ABC 库存不足，请先补货' };
  assert.equal(responseError(409, data, '').message, data.message);
  const original = Object.assign(new TypeError('Failed to fetch'), { status: 503, code: 'offline', retryAfter: 9, data });
  const localized = localizeError(original, '连接失败');
  assert.ok(hasChinese(localized.message)); assert.equal(localized.name, 'TypeError');
  for (const key of ['status', 'code', 'retryAfter', 'data']) assert.equal(localized[key], original[key]);
  assert.equal(errorMessage(new Error('native browser error')), '操作失败，请重试');
});

test('abort and cancellation tokens retain their identity', () => {
  const aborted = new DOMException('Aborted', 'AbortError');
  assert.equal(localizeError(aborted), aborted);
  assert.equal(localizeError('cancel'), 'cancel');
  assert.equal(localizeError('close'), 'close');
});

test('Retry-After accepts seconds and HTTP dates', () => {
  assert.equal(retryAfterSeconds('2.5'), 2.5);
  const savedNow = Date.now;
  try {
    Date.now = () => Date.parse('2026-01-01T00:00:00Z');
    assert.equal(retryAfterSeconds('Thu, 01 Jan 2026 00:00:12 GMT'), 12);
  } finally { Date.now = savedNow; }
});

test('request localizes HTTP, non-JSON, and network failures', async () => {
  const originalFetch = globalThis.fetch;
  try {
    setAuthSession('session', 'csrf');
    for (const status of [401, 403, 409, 429]) {
      const body = { code: status === 429 ? 'rate_limited' : 'fixture', message: 'English server message' };
      globalThis.fetch = async () => new Response(JSON.stringify(body), { status, headers: { 'Retry-After': '3' } });
      await assert.rejects(request('/api/admin/orders'), error => {
        assert.ok(hasChinese(error.message)); assert.equal(error.status, status);
        assert.equal(error.code, body.code); assert.equal(error.retryAfter, 3);
        assert.deepEqual(error.data, body); return true;
      });
    }
    globalThis.fetch = async () => new Response('<html>bad gateway</html>', { status: 502 });
    await assert.rejects(request('/api/admin/orders'), error => hasChinese(error.message) && error.status === 502 && Object.keys(error.data).length === 0);
    globalThis.fetch = async () => new Response('<html>not json</html>');
    await assert.rejects(request('/api/admin/orders'), error => error.message.includes('响应格式异常'));
    globalThis.fetch = async () => new Response(null, { status: 204 });
    assert.deepEqual(await request('/api/admin/orders'), {});
    globalThis.fetch = async () => { throw new TypeError('Failed to fetch'); };
    await assert.rejects(request('/api/admin/orders'), error => hasChinese(error.message));
    const aborted = new DOMException('Aborted', 'AbortError');
    globalThis.fetch = async () => { throw aborted; };
    await assert.rejects(request('/api/admin/orders'), error => error === aborted);
  } finally { globalThis.fetch = originalFetch; setAuthSession(); }
});

test('CSRF initialization handles non-JSON and changed identity in Chinese', async () => {
  const originalFetch = globalThis.fetch;
  try {
    setAuthSession('session');
    globalThis.fetch = async () => new Response('<html>invalid</html>');
    await assert.rejects(csrfHeaders(), error => hasChinese(error.message));
    setAuthSession('session');
    globalThis.fetch = async () => new Response('not json', { status: 403 });
    await assert.rejects(csrfHeaders(), error => error.status === 403 && hasChinese(error.message));
    setAuthSession('old');
    let resolve;
    globalThis.fetch = () => new Promise(done => { resolve = done; });
    const pending = csrfHeaders(); setAuthSession('new', 'new-token');
    resolve(new Response(JSON.stringify({ csrfToken: 'old-token' })));
    await assert.rejects(pending, error => error.code === 'session_changed' && hasChinese(error.message));
  } finally { globalThis.fetch = originalFetch; setAuthSession(); }
});

test('real upload handler localizes server and non-JSON errors and keeps metadata', async () => {
  const source = readFileSync(new URL('../composables/workbench.js', import.meta.url), 'utf8');
  const handler = source.slice(source.indexOf('export async function uploadImage(')).replace('export async function', 'return async function');
  let fixture, sent;
  class FakeXHR {
    upload = {};
    open(method, url) { sent = { method, url, headers: {} }; }
    setRequestHeader(key, value) { sent.headers[key] = value; }
    getResponseHeader(key) { return key === 'Retry-After' ? fixture.retryAfter || '' : ''; }
    send(body) { sent.body = body; this.status = fixture.status; this.responseText = fixture.body; queueMicrotask(() => this.onload()); }
  }
  const events = [];
  const makeHandler = new Function('csrfHeaders', 'useAdminAuthStore', 'XMLHttpRequest', 'window', 'responseError', 'API_BASE', handler);
  const uploadImage = makeHandler(async () => ({ 'X-CSRF-Token': 'csrf' }), () => ({ sessionId: 'session' }), FakeXHR,
    { dispatchEvent: event => events.push(event.type) }, responseError, '');
  fixture = { status: 429, retryAfter: '8', body: JSON.stringify({ code: 'rate_limited', message: 'Too many uploads', detail: 3 }) };
  await assert.rejects(uploadImage(new Blob(['x'])), error => {
    assert.ok(hasChinese(error.message)); assert.equal(error.status, 429); assert.equal(error.code, 'rate_limited');
    assert.equal(error.retryAfter, 8); assert.equal(error.data.detail, 3); return true;
  });
  assert.equal(sent.method, 'POST'); assert.equal(sent.headers['X-Auth-Session'], 'session');
  fixture = { status: 401, body: '<html>expired</html>' };
  await assert.rejects(uploadImage(new Blob(['x'])), error => error.status === 401 && hasChinese(error.message));
  assert.deepEqual(events, ['auth-session-expired']);
  fixture = { status: 400, body: JSON.stringify({ message: '图片尺寸不符合要求' }) };
  await assert.rejects(uploadImage(new Blob(['x'])), error => error.message === '图片尺寸不符合要求');
  fixture = { status: 200, body: 'null' };
  await assert.rejects(uploadImage(new Blob(['x'])), error => error.message === '附件上传失败，请重试');
});

test('native IndexedDB errors keep storage classification and show Chinese', async () => {
  const indexedDB = { open() {
    const request = {};
    queueMicrotask(() => { request.error = new DOMException('Storage access failed', 'UnknownError'); request.onerror(); });
    return request;
  } };
  const storage = createNotificationStorage(indexedDB);
  await assert.rejects(storage.read('key'), error => error.code === 'notification_storage' && hasChinese(error.message));
});
