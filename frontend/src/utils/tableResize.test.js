import assert from 'node:assert/strict';
import { test } from 'node:test';
import { readFileSync } from 'node:fs';

// Execute DataTable's actual observer lifecycle with a deterministic RAF queue.
function fixture(initialWidth = 0) {
  const source = readFileSync(new URL('../components/DataTable.vue', import.meta.url), 'utf8');
  const block = source.slice(source.indexOf('let observer'), source.indexOf('function columnWidth'));
  const available = { value: 1200 }, target = { getBoundingClientRect: () => ({ width: initialWidth }) }, frames = new Map();
  let mount, unmount, notify, nextId = 0, disconnected = false;
  class Observer {
    constructor(callback) { notify = width => callback([{ contentRect: { width } }]); }
    observe(element) { assert.equal(element, target); }
    disconnect() { disconnected = true; }
  }
  Function('available', 'container', 'persistSettings', 'onMounted', 'onBeforeUnmount',
    'ResizeObserver', 'requestAnimationFrame', 'cancelAnimationFrame', block)(
    available, { value: target }, () => {}, callback => { mount = callback; }, callback => { unmount = callback; },
    Observer, callback => { frames.set(++nextId, callback); return nextId; }, id => frames.delete(id),
  );
  mount();
  return {
    available, frames, notify, unmount,
    get disconnected() { return disconnected; },
    flush() { const callbacks = [...frames.values()]; frames.clear(); callbacks.forEach(callback => callback()); },
  };
}

test('mount uses the real positive width before RO, so its first equal notification needs no RAF', () => {
  const f = fixture(1126);
  assert.equal(f.available.value, 1126);
  assert.equal(f.frames.size, 0);
  f.notify(1126);
  assert.equal(f.available.value, 1126);
  assert.equal(f.frames.size, 0);
});

test('hidden/zero toolbar widths preserve the last real width without scheduling layout', () => {
  const f = fixture();
  f.notify(0);
  assert.equal(f.available.value, 1200);
  assert.equal(f.frames.size, 0);
  f.notify(1286); f.flush(); f.notify(0);
  assert.equal(f.available.value, 1286);
  assert.equal(f.frames.size, 0);
});

test('positive measurements coalesce into one deferred write of the latest width', () => {
  const f = fixture();
  f.notify(1286); f.notify(1100); f.notify(0);
  assert.equal(f.available.value, 1200);
  assert.equal(f.frames.size, 1);
  f.flush();
  assert.equal(f.available.value, 1100);
  assert.equal(f.frames.size, 0);
  f.notify(1100);
  assert.equal(f.frames.size, 0);
});

test('returning to the current width before RAF avoids an unnecessary value change', () => {
  const f = fixture();
  f.notify(1286); f.notify(1200); f.flush();
  assert.equal(f.available.value, 1200);
  assert.equal(f.frames.size, 0);
});

test('unmount disconnects the observer and cancels its pending RAF write', () => {
  const f = fixture();
  f.notify(1286); f.unmount();
  assert.equal(f.disconnected, true);
  assert.equal(f.frames.size, 0);
  f.flush();
  assert.equal(f.available.value, 1200);
});
