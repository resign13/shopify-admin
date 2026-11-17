import test from 'node:test';
import assert from 'node:assert/strict';
import { createMaintenance } from './maintenance.js';

const response = (status, body, headers = {}) => new Response(JSON.stringify(body), { status, headers });
function fixture(fetcher = async () => response(503, { code: 'maintenance' })) {
  const scheduled = new Map(); let id = 0;
  const store = createMaintenance({ fetcher, schedule: (fn, ms) => { scheduled.set(++id, { fn, ms }); return id; }, cancel: key => scheduled.delete(key) });
  return { store, scheduled };
}
test('only an explicit maintenance response opens the notice, without consuming the body', async () => {
  const { store, scheduled } = fixture();
  await store.observe(response(503, { code: 'export_busy' }));
  await store.observe(response(500, { code: 'maintenance' }));
  assert.equal(store.state.active, false);
  const original = response(503, { code: 'maintenance' });
  await store.observe(original);
  assert.equal((await original.json()).code, 'maintenance');
  assert.equal(store.state.active, true); assert.equal(scheduled.size, 1);
  await store.observe(response(503, {}, { 'X-Gingtto-Maintenance': '1' }));
  assert.equal(scheduled.size, 1);
  store.dispose();
});
test('recovery checks send only GET health requests and require explicit continue', async () => {
  const calls = [];
  const { store, scheduled } = fixture(async (...args) => { calls.push(args); return response(200, { status: 'ok' }); });
  await store.observe(response(503, { code: 'maintenance' }));
  assert.equal(store.continue(), false);
  const first = store.check(); assert.equal(first, store.check());
  await first;
  assert.equal(calls.length, 1); assert.equal(calls[0][0], '/api/health'); assert.equal(calls[0][1].method, 'GET');
  assert.equal(calls[0][1].cache, 'no-store');
  assert.equal(store.state.active, true); assert.equal(store.state.recovered, true); assert.equal(scheduled.size, 0);
  assert.equal(store.continue(), true); assert.equal(store.state.active, false);
  store.dispose();
});
test('unhealthy or unreachable health stays in maintenance and schedules one bounded poll', async () => {
  let phase = 0;
  const { store, scheduled } = fixture(async () => {
    if (phase++ === 0) throw new Error('offline');
    return phase === 2 ? response(200, { status: 'starting' }) : response(503, { code: 'maintenance' });
  });
  await store.observe(response(503, { code: 'maintenance' }));
  for (let i = 0; i < 3; i++) {
    await store.check();
    assert.equal(store.state.active, true); assert.equal(store.state.recovered, false);
    assert.equal(scheduled.size, 1); assert.equal([...scheduled.values()][0].ms, 30000);
  }
  store.dispose(); assert.equal(scheduled.size, 0);
});
test('a new maintenance response after recovery reopens the wait without a reload', async () => {
  const { store, scheduled } = fixture(async () => response(200, { status: 'ok' }));
  await store.observe(response(503, {}, { 'X-Gingtto-Maintenance': '1' })); await store.check();
  await store.observe(response(503, { code: 'maintenance' }));
  assert.equal(store.state.active, true); assert.equal(store.state.recovered, false); assert.equal(scheduled.size, 1);
  store.dispose();
});
