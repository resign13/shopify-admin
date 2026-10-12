export const MAX_WEIGHT_GRAMS = 2147483647;

export function validWeight(value) {
  return Number.isInteger(value) && value > 0 && value <= MAX_WEIGHT_GRAMS;
}

export function realWeightSizes(variants) {
  return [...new Set(variants.flatMap((v) => v.sizePrices.map((s) => s.sizeCode)))];
}

export function weightTargets(variants, sizeCode = "") {
  return variants.flatMap((variant) => variant.sizePrices
    .filter((size) => !sizeCode || size.sizeCode === sizeCode)
    .map((size) => ({ variant, size })));
}

export function applyWeight(variants, sizeCode, grams) {
  if (!validWeight(grams)) throw new Error("请填写有效的正整数克数");
  const targets = weightTargets(variants, sizeCode);
  for (const { size } of targets) size.weightGrams = grams;
  return targets.length;
}

export function formatWeightKg(grams) {
  if (grams == null || !/^[0-9]+$/.test(String(grams))) return "未设置";
  const value = BigInt(grams);
  return `${(value / 1000n).toLocaleString("en-US")}.${String(value % 1000n).padStart(3, "0")}`;
}

export function orderWeightPreviewItems(items) {
  return items.filter((item) => Number.isInteger(item.quantity) && item.quantity > 0)
    .map(({ productId, sizeCode, quantity }) => ({ productId, sizeCode: sizeCode || "", quantity }));
}

export function orderWeightText(order) {
  if (order.totalWeightGrams != null) return `${formatWeightKg(order.totalWeightGrams)} kg`;
  if (BigInt(order.knownWeightGrams || "0") > 0n)
    return `已知净重 ${formatWeightKg(order.knownWeightGrams)} kg，另有 ${order.missingWeightQuantity} 件未设置重量`;
  return `未设置（${order.missingWeightQuantity || 0} 件未设置重量）`;
}
