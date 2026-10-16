import { catalogQuote, validAmount } from './orderPricing.js';

export const MAX_ORDER_QUANTITY = 2147483647;
const key = (id, size) => JSON.stringify([String(id), size]);
// Keep the configured array order, including numeric-looking codes. Object.keys
// would reorder codes such as ['40', '38', '42'] as integer property names.
export const selectionSizes = product => [...new Set((product.sizePrices || []).map(s => s.sizeCode).filter(Boolean))];

export function selectionQuantity(value) {
  if (value === '' || value == null) return 0;
  if ((typeof value !== 'number' && typeof value !== 'string') || !/^\d+$/.test(String(value)))
    throw new Error('数量须为非负整数');
  const quantity = Number(value);
  if (!Number.isInteger(quantity) || quantity > MAX_ORDER_QUANTITY)
    throw new Error(`单尺码数量最多 ${MAX_ORDER_QUANTITY}`);
  return quantity;
}

export function createSelectionRecord(product, items) {
  const baseline = Object.fromEntries(selectionSizes(product).map(size => [size,
    items.filter(item => String(item.productId) === String(product.id) && item.sizeCode === size)
      .reduce((sum, item) => sum + Number(item.quantity || 0), 0)]));
  return { product, baseline, quantities: { ...baseline } };
}

export function selectionChanged(record) {
  return Object.entries(record.quantities).some(([size, value]) => {
    try { return selectionQuantity(value) !== record.baseline[size]; } catch { return true; }
  });
}

// Only changed, explicitly editable real sizes are returned. Historical removed
// sizes are never guessed or cleared as a side effect of selecting a color.
export function selectionChanges(record) {
  return Object.entries(record.quantities).flatMap(([sizeCode, value]) => {
    let quantity;
    try { quantity = selectionQuantity(value); }
    catch (error) { throw new Error(`${record.product.sku} / ${sizeCode}：${error.message}`); }
    return quantity === record.baseline[sizeCode] ? [] : [{ sizeCode, quantity }];
  });
}

// Build a new array before touching the order. Retain every quote field on
// existing lines, including zero-quantity lines that may be filled again later.
export function mergeSelectionQuantities(items, updates, currency = 'USD', rate = null) {
  const next = items.map(item => ({ ...item }));
  const index = new Map();
  for (const item of next) {
    const id = key(item.productId, item.sizeCode);
    if (index.has(id)) throw new Error('同一商品尺码不能重复，请先合并数量');
    index.set(id, item);
  }
  const touched = new Set();
  for (const { product, quantities } of updates) {
    for (const entry of quantities) {
      const quantity = selectionQuantity(entry.quantity);
      const size = product.sizePrices?.find(size => size.sizeCode === entry.sizeCode);
      if (!size) throw new Error(`${product.sku} / ${entry.sizeCode}：尺码已移除，请重新选择`);
      const id = key(product.id, entry.sizeCode);
      if (touched.has(id)) throw new Error('同一商品尺码不能重复应用');
      touched.add(id);
      const existing = index.get(id);
      if (existing) existing.quantity = quantity;
      else if (quantity > 0 || entry.placeholder) {
        if (!validAmount(size.price)) throw new Error(`${product.sku} / ${entry.sizeCode}：目录价格不可用`);
        const line = { productId: product.id, sku: product.sku,
          productName: product.name?.zh || product.name?.en || product.productCode || product.sku,
          sizeCode: entry.sizeCode, quantity, ...catalogQuote(size.price, currency, rate) };
        next.push(line);
        index.set(id, line);
      }
    }
  }
  if (next.filter(item => item.quantity > 0).length > 500) throw new Error('最多 500 个有效尺码行，请减少选择');
  return next;
}

export function prepareSelectionApplication(records, freshProducts, items, currency = 'USD', rate = null, { join = false } = {}) {
  const fresh = new Map(freshProducts.map(product => [String(product.id), product]));
  const notices = [], updates = [];
  for (const record of records) {
    const quantities = selectionChanges(record);
    const isNew = !items.some(item => String(item.productId) === String(record.product.id));
    if (!quantities.length && !(join && isNew)) continue;
    // A zero-only explicit join creates one draft anchor, not a purchased line.
    // All configured sizes are rendered independently from the catalog.
    if (join && isNew && !quantities.some(entry => entry.quantity > 0)) {
      const sizeCode = selectionSizes(record.product)[0];
      if (!sizeCode) throw new Error(`${record.product.sku}：未配置尺码`);
      quantities.push({ sizeCode, quantity: 0, placeholder: true });
    }
    const product = fresh.get(String(record.product.id));
    if (!product || product.isActive === false)
      throw new Error(`${record.product.sku}：商品已下架或删除，请返回查询结果重新选择`);
    for (const entry of quantities) {
      const size = product.sizePrices?.find(size => size.sizeCode === entry.sizeCode);
      if (!size) throw new Error(`${product.sku} / ${entry.sizeCode}：尺码已移除，请返回查询结果重新选择`);
      const previous = items.find(item => key(item.productId, item.sizeCode) === key(product.id, entry.sizeCode));
      if (previous) notices.push({ sku: product.sku, sizeCode: entry.sizeCode,
        before: previous.quantity, after: entry.quantity, clear: entry.quantity === 0 });
      else if (entry.quantity > 0) {
        const oldPrice = record.product.sizePrices?.find(size => size.sizeCode === entry.sizeCode)?.price;
        if (Number(oldPrice) !== Number(size.price)) notices.push({ sku: product.sku, sizeCode: entry.sizeCode,
          oldPrice, newPrice: size.price });
      }
    }
    updates.push({ product, quantities });
  }
  const merged = mergeSelectionQuantities(items, updates, currency, rate);
  return { updates, notices, items: merged };
}

// Main editor retains historical sizes as well as configured sizes, in their
// original order; it never unions sizes belonging to different color products.
export function orderProductSizes(product, items, productId) {
  return [...new Set([...selectionSizes(product || {}), ...items
    .filter(item => String(item.productId) === String(productId)).map(item => item.sizeCode)])].filter(Boolean);
}
