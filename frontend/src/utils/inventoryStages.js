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
  const nextInspection = stage === "inspection" ? value : row.pendingInspection - (value - old);
  let nextSource = row[source] - (value - old);
  let extra;
  if (row.registrationBase) {
    try {
      const previous = procurementPreview(row.registrationBase, stage === 'inspection' ? old : row.pendingInspection, stage === 'inbound' ? old : row.pendingInbound);
      if (previous.contractPending !== row.contractPending)
        throw new Error('请先单独保存合同未送调整，再登记阶段转移数量');
      extra = procurementPreview(row.registrationBase, nextInspection, stage === 'inbound' ? value : row.pendingInbound);
      nextSource = stage === 'inspection' ? extra.contractPending : nextInspection;
    } catch (e) {
      row[target] = old;
      return e.message;
    }
  }
  let error = "";
  if (nextSource < 0 || nextSource > MAX_QUANTITY) error = "本次转移超过上一阶段可用数量或整数范围";
  else if (nextInspection < row.defectivePending) error = "已登记次品预留待验货，请先减少次品或一键打回";
  if (error) row[target] = old;
  else {
    row[source] = nextSource;
    if (extra) Object.assign(row, extra);
  }
  return error;
}

export function defectiveReturnPreview(size) {
  const extra = Math.min(size.defectivePending || 0, size.overdeliveryInspection || 0);
  return {
    quantity: size.defectivePending || 0,
    contractAfter: size.contractPending + (size.defectivePending || 0) - extra,
    inspectionAfter: size.pendingInspection - (size.defectivePending || 0),
    defectiveAfter: 0,
  };
}

// Match the server's provenance rules. Always recalculate from the saved base,
// so typing/undoing an unsaved draft does not consume cumulative allowance.
export function procurementPreview(base, inspection, qualified) {
  let p = base.contractPending, i = base.pendingInspection, b = base.pendingInbound;
  let used = base.overdeliveryUsed || 0, ei = base.overdeliveryInspection || 0, eb = base.overdeliveryQualified || 0;
  let received = base.contractReceived || 0;
  const total = base.originalContractQuantity || 0;
  const limit = base.overdeliveryLimit || 0, arrival = inspection + qualified - i - b;
  if (qualified < b) {
    const extra = Math.min(eb, b-qualified);
    eb -= extra; ei += extra; i += b-qualified;
  }
  if (arrival > 0) {
    const normal = total ? Math.min(arrival, p, Math.max(0,total-received)) : Math.min(arrival,p);
    const extra = arrival-normal;
    if (used+extra > limit) throw new Error(`超出原合同数量累计15%额度：允许超量 ${limit}，已用 ${used}，本次超量 ${extra}`);
    p -= arrival-extra; ei += extra; used += extra;
    received += normal;
  } else if (arrival < 0) {
    const extra = Math.min(ei, -arrival);
    ei -= extra; p += -arrival-extra;
    received -= -arrival-extra;
  }
  i += arrival;
  if (qualified > b) {
    const extra = Math.max(0, qualified-b-(i-ei));
    ei -= extra; eb += extra;
  }
  if (Math.min(p, inspection, qualified, ei, eb, i) < 0 || ei > inspection || eb > qualified)
    throw new Error('本次转移超过上一阶段可用数量');
  if (Math.max(p, inspection, qualified, used) > MAX_QUANTITY) throw new Error('数量超出允许范围');
  return { contractPending: p, contractReceived: Math.max(0,received), overdeliveryUsed: used, overdeliveryInspection: ei, overdeliveryQualified: eb,
    overdeliveryRemaining: Math.max(0, limit-used) };
}
