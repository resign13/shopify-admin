import { errorMessage } from './adminErrors.js';

export const MAX_QUANTITY = 2147483647;

// Send paired final targets for a transfer, even if one returns to its original
// value. Omitting it makes the server infer another transfer from a partial map.
export function procurementTargets(rows) {
  const changed = rows.filter(row => row.pendingInspection !== row.originalInspection || row.pendingInbound !== row.originalInbound);
  return {
    pendingInspectionBySize: Object.fromEntries(changed.map(row => [row.sizeCode, row.pendingInspection])),
    pendingInboundBySize: Object.fromEntries(changed.map(row => [row.sizeCode, row.pendingInbound])),
    receiptExtraBySize: Object.fromEntries(changed.filter(row => row.receiptExtra != null).map(row => [row.sizeCode, row.receiptExtra])),
  };
}

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
      const previous = procurementPreview(row.registrationBase, stage === 'inspection' ? old : row.pendingInspection, stage === 'inbound' ? old : row.pendingInbound, row.receiptExtra);
      if (previous.contractPending !== row.contractPending)
        throw new Error('请先单独保存合同未送调整，再登记阶段转移数量');
      const qualified = stage === 'inbound' ? value : row.pendingInbound;
      const arrival = receiptArrival(row.registrationBase, nextInspection, qualified);
      const receiptExtra = arrival > 0 ? row.receiptExtra : null;
      extra = { ...procurementPreview(row.registrationBase, nextInspection, qualified, receiptExtra), receiptExtra };
      nextSource = stage === 'inspection' ? extra.contractPending : nextInspection;
    } catch (e) {
      row[target] = old;
      return errorMessage(e);
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
    extraReturned: extra,
    contractAfter: size.contractPending + (size.defectivePending || 0) - extra,
    inspectionAfter: size.pendingInspection - (size.defectivePending || 0),
    defectiveAfter: 0,
  };
}

export const balanceAllowance = pending => Math.floor(pending * 15 / 100);
export const receiptArrival = (base, inspection, qualified) =>
  inspection + qualified - base.pendingInspection - base.pendingInbound;

export function procurementPreview(base, inspection, qualified, explicitExtra) {
  let p = base.contractPending, i = base.pendingInspection, b = base.pendingInbound;
  let used = base.overdeliveryUsed || 0, ei = base.overdeliveryInspection || 0, eb = base.overdeliveryQualified || 0;
  const limit = balanceAllowance(p), arrival = receiptArrival(base, inspection, qualified);
  if (qualified < b) {
    const extra = Math.min(eb, b-qualified);
    eb -= extra; ei += extra; i += b-qualified;
  }
  if (arrival > 0) {
    const extra = explicitExtra ?? Math.max(0, arrival-p);
    const normal = arrival-extra;
    if (!Number.isInteger(extra) || extra < 0 || extra > arrival) throw new Error('本次超收须在 0 与本次实际到货之间');
    if (extra > limit || normal > p)
      throw new Error(`按当前未送 ${p} 件，超收最多 ${limit} 件，本次最多登记 ${p+limit} 件；正常到货不超过当前未送`);
    p -= normal; ei += extra; used += extra;
  } else if (explicitExtra) {
    throw new Error('只有新增到货时可登记本次超收');
  } else if (arrival < 0) {
    const extra = Math.min(ei, -arrival);
    ei -= extra; p += -arrival-extra;
  }
  i += arrival;
  if (qualified > b) {
    const extra = Math.max(0, qualified-b-(i-ei));
    ei -= extra; eb += extra;
  }
  if (Math.min(p, inspection, qualified, ei, eb, i) < 0 || ei > inspection || eb > qualified)
    throw new Error('本次转移超过上一阶段可用数量');
  if (Math.max(p, inspection, qualified, used) > MAX_QUANTITY) throw new Error('数量超出允许范围');
  return { contractPending: p, overdeliveryUsed: used, overdeliveryInspection: ei, overdeliveryQualified: eb,
    overdeliveryLimit: balanceAllowance(p) };
}
