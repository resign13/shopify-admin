import test from 'node:test';
import assert from 'node:assert/strict';
import { orderSelectionTotals, formatSelectionAmount } from './orderSelectionTotals.js';

test('sum selected goods and payable amounts exactly, including zero and cancelled orders', () => {
  const orders = [
    { id: 1, status: 'paid', currency: 'USD', goodsAmount: 0.1, totalAmount: 0.3 },
    { id: 2, status: 'cancelled', currency: 'USD', goodsAmount: 0.2, totalAmount: 0.2 },
    { id: 3, currency: 'USD', goodsAmount: 0, totalAmount: 0 },
  ];
  const [total] = orderSelectionTotals(orders);
  assert.equal(total.goods, 30n);
  assert.equal(total.payable, 50n);
  assert.equal(formatSelectionAmount(total.goods, total.currency), '$0.30');
  assert.equal(formatSelectionAmount(total.payable, total.currency), '$0.50');
  assert.equal(orders[0].goodsAmount, 0.1);
  assert.deepEqual(orderSelectionTotals([]), []);
});

test('keep currencies separate, including selections from another page', () => {
  const selected = [
    { id: 1, currency: 'CNY', goodsAmount: '1234.56', totalAmount: '1250.56' },
    { id: 2, currency: 'USD', goodsAmount: '12.34', totalAmount: '12.34' },
    { id: 3, currency: 'CNY', goodsAmount: '0.44', totalAmount: '0.44' },
  ];
  const [usd, cny] = orderSelectionTotals(selected);
  assert.deepEqual([usd.currency, usd.goods, usd.payable], ['USD', 1234n, 1234n]);
  assert.deepEqual([cny.currency, cny.goods, cny.payable], ['CNY', 123500n, 125100n]);
  assert.equal(formatSelectionAmount(cny.goods, cny.currency), 'CNY ¥1,235.00');
});

test('do not present partial or fabricated totals when a selected row is incomplete', () => {
  const valid = { currency: 'USD', goodsAmount: 1, totalAmount: 2 };
  for (const invalid of [
    { currency: 'USD', goodsAmount: null, totalAmount: 1 },
    { currency: 'USD', goodsAmount: 1, totalAmount: undefined },
    { currency: 'USD', goodsAmount: -1, totalAmount: 1 },
    { currency: 'USD', goodsAmount: 1.001, totalAmount: 1 },
    { currency: 'EUR', goodsAmount: 1, totalAmount: 1 },
  ]) assert.equal(orderSelectionTotals([valid, invalid]), null);
});

test('format big totals without losing cents', () => {
  const [total] = orderSelectionTotals([
    { currency: 'USD', goodsAmount: '999999999999999.99', totalAmount: '999999999999999.99' },
    { currency: 'USD', goodsAmount: '0.01', totalAmount: '0.01' },
  ]);
  assert.equal(formatSelectionAmount(total.goods, total.currency), '$1,000,000,000,000,000.00');
});
