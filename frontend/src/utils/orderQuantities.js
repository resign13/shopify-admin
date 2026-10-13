// Each matrix row represents one color SKU; sum its quantities across all sizes.
export function orderProductQuantity(items, productId) {
  return items.reduce(
    (total, item) => total + (item.productId === productId ? Number(item.quantity || 0) : 0),
    0,
  );
}

// Existing orders have already affected stock: apply only the quantity delta.
// Reorders and new drafts pass before=0, never the source order's quantity.
export function orderVariantInventory(stock, before = 0, next = 0, oldStatus = '', nextStatus = '') {
  const change = (oldStatus === 'cancelled' ? 0 : Number(before || 0)) -
    (nextStatus === 'cancelled' ? 0 : Number(next || 0));
  return { current: stock ?? '待刷新', change: change > 0 ? `+${change}` : change,
    after: stock == null ? '待刷新' : Number(stock) + change };
}
