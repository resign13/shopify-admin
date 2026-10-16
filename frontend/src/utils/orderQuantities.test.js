import test from 'node:test';
import assert from 'node:assert/strict';
import { orderProductQuantity, orderVariantInventory, variantStockHint } from './orderQuantities.js';

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

test('new/reorder/draft quantities preview per-size balance including shortage', () => {
  assert.equal(orderVariantInventory(18,0,1).after,17);
  assert.equal(orderVariantInventory(-3,0,1).after,-4);
  assert.equal(orderVariantInventory(0,0,2).after,-2);
  assert.equal(orderVariantInventory(18,0,0).after,18);
});
test('editing applies differences, reductions and clearing restore only original units', () => {
  assert.equal(orderVariantInventory(18,3,3).after,18);
  assert.equal(orderVariantInventory(18,3,5).after,16);
  assert.equal(orderVariantInventory(18,3,1).after,20);
  assert.equal(orderVariantInventory(18,3,0).after,21);
});
test('cancel and restore use original inventory rules; unknown stock is not zero', () => {
  assert.equal(orderVariantInventory(18,3,3,'allocated','cancelled').after,21);
  assert.equal(orderVariantInventory(18,3,3,'cancelled','allocated').after,15);
  assert.equal(orderVariantInventory(18,3,3,'cancelled','cancelled').after,18);
  assert.equal(orderVariantInventory(undefined,0,2).after,'待刷新');
  assert.equal(orderVariantInventory(null,0,2).after,'待刷新');
});

test('shared stock hints preserve signed balances and distinguish unavailable from zero', () => {
  for (const stock of [12, 0, -5, -2147483648, 2147483647]) {
    const result = variantStockHint(stock);
    assert.equal(result.text, `库存 ${stock}${stock < 0 ? ' · 欠货' : ''}`);
    assert.equal(result.shortage, stock < 0);
  }
  for (const stock of [null, undefined, '', '12', '待刷新', false, NaN, Infinity, 1.2]) {
    assert.deepEqual(variantStockHint(stock), {text:'库存不可用', shortage:false});
  }
  assert.equal(variantStockHint(orderVariantInventory(12, 0, 17).after).text, '库存 -5 · 欠货');
  assert.equal(variantStockHint(undefined, '库存 待刷新').text, '库存 待刷新');
});
