export const approvalPermission = 'orders.cancel.approve';
export const orderStages = ['pending_payment','partially_allocated','allocated','paid','shipped','completed'];
export const cancellationStateNames = {pending:'取消待审核',approved:'审核通过',rejected:'已驳回',withdrawn:'已撤回'};
export function cancellationPending(order) { return order?.cancelRequest?.state === 'pending'; }
export function allowedOrderStatuses(order, names) {
  if (!order?.status) return names;
  if (cancellationPending(order)) return {[order.status]:names[order.status]};
  if (order.status === 'cancelled') return Object.fromEntries(Object.entries(names).filter(([key]) => key==='cancelled' || key===order.cancelledFromStatus));
  const current=orderStages.indexOf(order.status);
  return Object.fromEntries(Object.entries(names).filter(([key]) => current<2 || orderStages.indexOf(key)>=current));
}
