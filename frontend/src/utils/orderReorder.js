import { customerProfile } from './customerTemplates.js';

export function reorderForm(result) {
  const draft = result.draft;
  return {
    ...customerProfile(draft), ownerAdminId: draft.ownerAdminId ?? null,
    sourceOrderId: result.sourceOrderId ?? draft.sourceOrderId ?? null,
    secondaryOrderNo: draft.secondaryOrderNo || '',
    shippingFee: Number(draft.shippingFee || 0),
    currency: draft.currency || 'USD', exchangeRate:draft.exchangeRate==null?null:Number(draft.exchangeRate), shippingConversionBase:draft.shippingConversionBase||null,
    status: 'pending_payment', trackingNo: '', paymentLink: '',
    labelImageUrls: [], labelPdfUrl: '',
    inheritedAttachmentUrls: [...(draft.inheritedAttachmentUrls || [])],
    items: draft.items.map(item => ({ ...item, oldPriceCurrency:item.oldPriceCurrency||draft.currency||'USD',oldUnitPrices: [...(item.oldUnitPrices || [item.unitPrice])] })),
    pendingItems: result.issues.map(item => ({ ...item })),
    ownerConfirmed: !result.ownerNeedsConfirmation,
  };
}

export function reorderPriceChanges(items, currency = 'USD') {
  return items.filter(row => row.quantity > 0 && ((row.oldPriceCurrency && row.oldPriceCurrency !== currency) || row.oldUnitPrices?.some(price =>
    Math.round(Number(price) * 100) !== Math.round(Number(row.unitPrice) * 100))));
}

export function applyReorderPrices(items, products, changes) {
  for (const change of changes) {
    const row = items.find(item => item.productId === change.productId && item.sizeCode === change.sizeCode);
    if (row && row.priceSource !== 'manual') {
      row.oldUnitPrices ??= [row.unitPrice];
      row.unitPrice = change.unitPrice;
      row.referencePriceUsd = change.referencePriceUsd ?? change.unitPrice;
      row.priceSource='catalog';row.preserveQuote=false;row.conversionBase=undefined;row.catalogPriceChanged=false;
    }
    const size = products[change.productId]?.sizePrices?.find(size => size.sizeCode === change.sizeCode);
    if (size) size.price = change.referencePriceUsd ?? change.unitPrice;
  }
}

export function attachmentHref(url) {
  if (typeof url !== 'string') return '';
  if (/^\/api\/attachments\/[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}\/content(?:\/[^/?#\\]+)?$/i.test(url)) return url;
  if (url.startsWith('/uploads/') && !url.includes('\\')) return url;
  try { return ['http:', 'https:'].includes(new URL(url).protocol) ? url : ''; }
  catch { return ''; }
}
