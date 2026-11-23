// Each matrix row represents one color SKU; sum its quantities across all sizes.
export function orderProductQuantity(items, productId) {
  return items.reduce(
    (total, item) => total + (item.productId === productId ? Number(item.quantity || 0) : 0),
    0,
  );
}

// Reorders and drafts pass before=0, never the source order's quantity.
// Missing policy information retains the server's legacy pre-cutover behavior.
export function orderVariantInventory(stock, before = 0, next = 0, oldStatus = '', nextStatus = '', stockOnPaymentEnabled = false) {
  const deducted = status => status !== 'cancelled' && (!stockOnPaymentEnabled || ['paid','partially_allocated','allocated','shipped','completed'].includes(status));
  const change = (deducted(oldStatus) ? Number(before || 0) : 0) -
    (deducted(nextStatus) ? Number(next || 0) : 0);
  return { current: stock ?? '待刷新', change: change > 0 ? `+${change}` : change,
    after: stock == null ? '待刷新' : Number(stock) + change };
}

// Presentation only: callers decide whether this is a current or preview balance.
export function variantStockHint(stock, unavailableText = '库存不可用') {
  const known = typeof stock === 'number' && Number.isInteger(stock);
  const shortage = known && stock < 0;
  return { shortage, text: known ? `库存 ${stock}${shortage ? ' · 欠货' : ''}` : unavailableText };
}
