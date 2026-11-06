import { scaled } from './orderPricing.js';

// The table supplies every selected row, including selections on other pages.
// Sum in cents and keep currencies separate; never use an exchange-rate guess.
export function orderSelectionTotals(rows) {
  const byCurrency = new Map();
  try {
    for (const row of rows) {
      if (!['USD', 'CNY'].includes(row.currency)) return null;
      const total = byCurrency.get(row.currency) || { currency: row.currency, goods: 0n, payable: 0n };
      total.goods += scaled(row.goodsAmount);
      total.payable += scaled(row.totalAmount);
      byCurrency.set(row.currency, total);
    }
  } catch {
    // Do not display a partial amount when a selected order has missing data.
    return null;
  }
  return ['USD', 'CNY'].filter(currency => byCurrency.has(currency)).map(currency => byCurrency.get(currency));
}

export function formatSelectionAmount(cents, currency) {
  const units = (cents / 100n).toLocaleString('en-US');
  const fraction = String(cents % 100n).padStart(2, '0');
  return `${currency === 'CNY' ? 'CNY ¥' : '$'}${units}.${fraction}`;
}
