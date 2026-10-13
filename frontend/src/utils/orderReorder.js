import { customerProfile } from './customerTemplates.js';

export function reorderForm(result) {
  const draft = result.draft;
  return {
    ...customerProfile(draft), ownerAdminId: draft.ownerAdminId ?? null,
    secondaryOrderNo: draft.secondaryOrderNo || '',
    shippingFee: Number(draft.shippingFee || 0),
    status: 'pending_payment', trackingNo: '', paymentLink: '',
    labelImageUrls: [], labelPdfUrl: '',
    inheritedAttachmentUrls: [...(draft.inheritedAttachmentUrls || [])],
    items: draft.items.map(item => ({ ...item, oldUnitPrices: [...item.oldUnitPrices] })),
    pendingItems: result.issues.map(item => ({ ...item })),
    ownerConfirmed: !result.ownerNeedsConfirmation,
  };
}

export function reorderPriceChanges(items) {
  return items.filter(row => row.quantity > 0 && row.oldUnitPrices?.some(price =>
    Math.round(Number(price) * 100) !== Math.round(Number(row.unitPrice) * 100)));
}

export function applyReorderPrices(items, products, changes) {
  for (const change of changes) {
    const row = items.find(item => item.productId === change.productId && item.sizeCode === change.sizeCode);
    if (row) {
      row.oldUnitPrices ??= [row.unitPrice];
      row.unitPrice = change.unitPrice;
    }
    const size = products[change.productId]?.sizePrices?.find(size => size.sizeCode === change.sizeCode);
    if (size) size.price = change.unitPrice;
  }
}

export function attachmentHref(url) {
  if (typeof url !== 'string') return '';
  if (url.startsWith('/uploads/') && !url.includes('\\')) return url;
  try { return ['http:', 'https:'].includes(new URL(url).protocol) ? url : ''; }
  catch { return ''; }
}
