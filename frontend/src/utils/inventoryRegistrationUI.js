// Presentation only. Procurement validation remains in inventoryStages.js.
export function quantityChange(value, original) {
  if (!Number.isInteger(value) || !Number.isInteger(original)) {
    return { text: '待填写', tone: 'incomplete', changed: true };
  }
  const difference = value - original;
  return {
    text: difference > 0 ? `+${difference}` : difference < 0 ? String(difference) : '未变化',
    tone: difference > 0 ? 'increase' : difference < 0 ? 'decrease' : 'unchanged',
    changed: difference !== 0,
  };
}

export function registrationRowChanged(row) {
  return [
    ['stock', 'originalStock'],
    ['contractPending', 'originalPending'],
    ['pendingInspection', 'originalInspection'],
    ['defectivePending', 'originalDefective'],
    ['pendingInbound', 'originalInbound'],
    ['temporaryInbound', 'originalTemporary'],
  ].some(([field, original]) => quantityChange(row[field], row[original]).changed);
}
