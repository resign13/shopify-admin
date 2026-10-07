import test from 'node:test';
import assert from 'node:assert/strict';
import { orderProductQuantity } from './orderQuantities.js';

test('sums every size in one color SKU without mixing other products', () => {
  const items = [
    ...[14, 15, 17, 11, 8].map((quantity, index) => ({ productId: 1, sizeCode: String(index), quantity })),
    ...[10, 12, 16, 8, 4].map((quantity, index) => ({ productId: 2, sizeCode: String(index), quantity })),
    { productId: 3, quantity: 0 },
  ];
  assert.equal(orderProductQuantity(items, 1), 65);
  assert.equal(orderProductQuantity(items, 2), 50);
  assert.equal(orderProductQuantity(items, 3), 0);
  assert.equal(orderProductQuantity(items, 4), 0);
  assert.equal(orderProductQuantity([], 1), 0);
});

test('reflects quantity edits, cleared inputs and removed rows without mutating prices', () => {
  const items = [
    { productId: 1, sizeCode: 'S', quantity: 2, unitPrice: 17 },
    { productId: 1, sizeCode: 'M', quantity: 3, unitPrice: 19 },
  ];
  const before = structuredClone(items);
  assert.equal(orderProductQuantity(items, 1), 5);
  assert.deepEqual(items, before);
  items[0].quantity = 7;
  assert.equal(orderProductQuantity(items, 1), 10);
  items[1].quantity = undefined;
  assert.equal(orderProductQuantity(items, 1), 7);
  items.splice(0, 1);
  assert.equal(orderProductQuantity(items, 1), 0);
  assert.equal(items[0].unitPrice, 19);
});

test('total can exceed the per-size integer limit', () => {
  const items = [
    { productId: 1, quantity: 2147483647 },
    { productId: 1, quantity: 2147483647 },
  ];
  assert.equal(orderProductQuantity(items, 1), 4294967294);
});
