// Each matrix row represents one color SKU; sum its quantities across all sizes.
export function orderProductQuantity(items, productId) {
  return items.reduce(
    (total, item) => total + (item.productId === productId ? Number(item.quantity || 0) : 0),
    0,
  );
}
