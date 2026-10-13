import test from 'node:test';
import assert from 'node:assert/strict';
import { orderNumberParts } from './orderNumber.js';
test('legacy and short numbers remain intact', () => {
  for (const full of ['LM-000188', 'PO1013-Alex-000188']) {
    const p = orderNumberParts(full); assert.equal(p.prefix + p.name + p.suffix, full);
  }
});
test('only customer name shortens; full identifier is retained', () => {
  const full = 'PO1013-Jonathan Vargo Very Long Customer Name-000188';
  const p = orderNumberParts(full);
  assert.equal(p.full, full); assert.equal(p.prefix, 'PO1013-'); assert.equal(p.suffix, '-000188');
  assert.equal(p.prefix + p.name + p.suffix, 'PO1013-Jonathan Va...-000188');
});
test('Unicode, spaces, hyphens and growing sequence are preserved', () => {
  const full = 'PO0101-张三 Élodie-Marie  客户非常长的名字-1234567';
  const p = orderNumberParts(full); assert.equal(p.full, full); assert.equal(p.suffix, '-1234567');
  assert.ok(p.name.endsWith('...'));
  assert.equal(orderNumberParts('PO0101-A  B-000001').name, 'A  B');
});
