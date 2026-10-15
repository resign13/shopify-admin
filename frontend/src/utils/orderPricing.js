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
export function previewQuoteChange(quote, currency, exchangeRate, existingOrder = false) {
  if (!validAmount(quote.shippingFee) || quote.items.some(row => !validAmount(row.unitPrice))) throw new Error('请先补全有效商品单价和运费');
  if (!['USD', 'CNY'].includes(currency)) throw new Error('请选择 USD 或 CNY');
  if ((currency === 'CNY' || exchangeRate !== null && exchangeRate !== '') && !validRate(exchangeRate)) throw new Error('请填写有效本单汇率（1 USD = CNY）');
  const switching = currency !== quote.currency;
  const rateChanged = validRate(quote.exchangeRate) && validRate(exchangeRate)
    ? scaled(quote.exchangeRate,6) !== scaled(exchangeRate,6)
    : (quote.exchangeRate ?? null) !== (exchangeRate ?? null);
  const items = quote.items.map(row => {
    const catalog = row.priceSource === 'catalog' && !row.preserveQuote && !existingOrder;
    if (catalog && row.referencePriceUsd != null) return { ...row, ...catalogQuote(row.referencePriceUsd, currency, exchangeRate), conversionBase: undefined };
    if (!switching) return { ...row, priceSource: existingOrder ? 'manual' : row.priceSource, conversionBase:rateChanged?undefined:row.conversionBase };
    const base = (!rateChanged && row.conversionBase) || { currency: quote.currency, unitPrice: row.unitPrice };
    return { ...row, unitPrice: convertAmount(base.unitPrice, base.currency, currency, exchangeRate),
      priceSource: row.priceSource === 'legacy' || existingOrder ? 'manual' : row.priceSource, conversionBase: base };
  });
  const base = (!rateChanged && quote.shippingConversionBase) || { currency: quote.currency, amount: quote.shippingFee };
  const shippingFee = switching ? convertAmount(base.amount, base.currency, currency, exchangeRate) : quote.shippingFee;
  return { currency, exchangeRate: exchangeRate === '' || exchangeRate == null ? null : Number(exchangeRate), items,
    shippingFee, shippingConversionBase: switching ? base : rateChanged ? null : quote.shippingConversionBase };
}
