// Decimal input is converted to scaled integers; no floating-point FX arithmetic.
export function scaled(value, precision = 2) {
  if (value === null || value === undefined || value === '' || typeof value === 'boolean') throw new Error('请填写有效金额');
  const match = String(value).trim().match(/^(\d+)(?:\.(\d+))?(?:e([+-]?\d+))?$/i);
  if (!match) throw new Error('请填写非负金额');
  const digits = match[1] + (match[2] || '');
  const shift = precision + Number(match[3] || 0) - (match[2]?.length || 0);
  if (Math.abs(shift) > 30) throw new Error('金额超出范围');
  const result = BigInt(digits);
  if (shift >= 0) return result * 10n ** BigInt(shift);
  const divisor = 10n ** BigInt(-shift);
  if (result % divisor) throw new Error(`最多 ${precision} 位小数`);
  return result / divisor;
}
const rounded = (n, d) => (n + d / 2n) / d;
export function validRate(value) {
  try { const rate = scaled(value, 6); return rate > 0n && rate <= 9999999999990000n; } catch { return false; }
}
export function validAmount(value) {
  try { return scaled(value) <= 999999999999n; } catch { return false; }
}
export function convertAmount(value, from, to, rate) {
  let cents = scaled(value);
  if (from !== to) {
    if (!validRate(rate)) throw new Error('请填写有效本单汇率（1 USD = CNY），最多六位小数');
    const fx = scaled(rate, 6);
    cents = from === 'USD' ? rounded(cents * fx, 1000000n) : rounded(cents * 1000000n, fx);
  }
  if (cents > 999999999999n) throw new Error('换算金额超出范围，请调整报价');
  return Number(cents) / 100;
}
export function catalogQuote(usd, currency = 'USD', rate = null) {
  return { unitPrice: convertAmount(usd, 'USD', currency, rate), priceSource: 'catalog', referencePriceUsd: Number(usd), preserveQuote: false };
}
export function quoteTotal(items, shippingFee = 0) {
  return Number(items.reduce((n, row) => n + scaled(row.unitPrice) * BigInt(row.quantity || 0), scaled(shippingFee))) / 100;
}
