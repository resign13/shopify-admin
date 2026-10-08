export const MAX_QUANTITY = 2147483647;

export function registrationError(rows) {
  for (const row of rows) {
    if (!Number.isInteger(row.stock) || row.stock < -2147483648 || row.stock > MAX_QUANTITY)
      return "现货余额须为范围内的整数";
    if (["contractPending", "pendingInspection", "pendingInbound", "temporaryInbound", "defectivePending"].some(
      (key) => !Number.isInteger(row[key]) || row[key] < 0 || row[key] > MAX_QUANTITY,
    )) return "其他阶段须为范围内的非负整数";
    if (row.defectivePending > row.pendingInspection)
      return `${row.sizeCode} 次品不能超过待验货；已登记次品须预留，不能转为合格`;
  }
  return "";
}

// The candidate row contains the proposed target value. Restore it
// on failure, and never mutate the upstream stage on a rejected transfer.
export function moveProcurementStage(row, stage, value, old) {
  if (!Number.isInteger(value) || !Number.isInteger(old)) return "";
  const target = stage === "inspection" ? "pendingInspection" : "pendingInbound";
  const source = stage === "inspection" ? "contractPending" : "pendingInspection";
  const nextSource = row[source] - (value - old);
  const nextInspection = stage === "inspection" ? value : nextSource;
  let error = "";
  if (nextSource < 0 || nextSource > MAX_QUANTITY) error = "本次转移超过上一阶段可用数量或整数范围";
  else if (nextInspection < row.defectivePending) error = "已登记次品预留待验货，请先减少次品或一键打回";
  if (error) row[target] = old;
  else row[source] = nextSource;
  return error;
}

export function defectiveReturnPreview(size) {
  return {
    quantity: size.defectivePending || 0,
    contractAfter: size.contractPending + (size.defectivePending || 0),
    inspectionAfter: size.pendingInspection - (size.defectivePending || 0),
    defectiveAfter: 0,
  };
}
