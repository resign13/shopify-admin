import test from 'node:test';
import assert from 'node:assert/strict';
import { reorderForm, reorderPriceChanges, applyReorderPrices, attachmentHref } from './orderReorder.js';

test('reorder creates independent new draft with current prices and legacy attachments', () => {
  const source = {draft: {userId: 1, contactName: 'Customer', note: '辅料\nPacking note',
    shippingFee: 12.5, ownerAdminId: 2, status: 'completed', trackingNo: 'old', paymentLink: 'old',
    inheritedAttachmentUrls: Array.from({length: 20}, (_, n) => `/uploads/${n}.pdf`),
    items: [{productId:1, sizeCode:'Tall XL', quantity:3, unitPrice:29.9, oldUnitPrices:[20, 25]}]},
    issues:[{sku:'OLD', reason:'原尺码已移除'}], ownerNeedsConfirmation:true};
  const form = reorderForm(source);
  assert.equal(form.status, 'pending_payment'); assert.equal(form.trackingNo, '');
  assert.equal(form.paymentLink, ''); assert.equal(form.shippingFee, 12.5);
  assert.equal(form.ownerConfirmed, false); assert.equal(form.inheritedAttachmentUrls.length, 20);
  assert.equal(form.items[0].unitPrice, 29.9); assert.equal(form.note, source.draft.note);
  form.items[0].quantity = 8; form.items[0].oldUnitPrices.push(99);
  form.inheritedAttachmentUrls.pop(); form.pendingItems.pop();
  assert.equal(source.draft.items[0].quantity, 3); assert.deepEqual(source.draft.items[0].oldUnitPrices,[20,25]);
  assert.equal(source.draft.inheritedAttachmentUrls.length,20); assert.equal(source.issues.length,1);
  assert.equal('id' in form, false); assert.equal('requestId' in form, false);
});

test('price conflict updates only matching draft prices, keeps quantities and original price comparison', () => {
  const items = [{productId:1,sizeCode:'M',quantity:3,unitPrice:20,oldUnitPrices:[10]},
    {productId:2,sizeCode:'L',quantity:0,unitPrice:2,oldUnitPrices:[1]}];
  const products = {1:{sizePrices:[{sizeCode:'M',price:20}]}};
  applyReorderPrices(items, products, [{productId:1,sizeCode:'M',unitPrice:25}]);
  assert.equal(items[0].quantity,3); assert.equal(items[0].unitPrice,25);
  assert.equal(products[1].sizePrices[0].price,25); assert.deepEqual(items[0].oldUnitPrices,[10]);
  assert.equal(reorderPriceChanges(items).length,1);
});

test('inherited file links never execute stored markup or scripts', () => {
  for (const url of ['javascript:alert(1)','data:text/html,hi','//other.test/a','/uploads/\\evil','bad']) assert.equal(attachmentHref(url),'');
  for (const url of ['/uploads/old.pdf', 'https://example.test/a.jpg',
      '/api/attachments/12345678-1234-1234-1234-123456789abc/content/attachment.pdf']) assert.equal(attachmentHref(url), url);
  for (const url of ['/api/attachments/bad/content/file.pdf','/api/attachments/12345678-1234-1234-1234-123456789abc/content/../file.pdf']) assert.equal(attachmentHref(url),'');
});
test('a resumed reorder quote keeps its source identity, native currency, manual prices and anchors',()=>{
  const draft={sourceOrderId:5,currency:'CNY',exchangeRate:'7.200000',shippingFee:10,
    shippingConversionBase:{currency:'USD',amount:1.39},items:[{productId:1,sizeCode:'M',quantity:2,
      unitPrice:82,priceSource:'manual',referencePriceUsd:29.9,oldUnitPrices:[80],conversionBase:{currency:'USD',unitPrice:11.39}}]};
  const form=reorderForm({draft,sourceOrderId:5,issues:[],ownerNeedsConfirmation:false});
  assert.equal(form.sourceOrderId,5);assert.equal(form.currency,'CNY');assert.equal(form.exchangeRate,7.2);
  assert.equal(form.items[0].unitPrice,82);assert.equal(form.items[0].priceSource,'manual');
  assert.equal(form.shippingConversionBase.amount,1.39);assert.equal(form.items[0].conversionBase.unitPrice,11.39);
  assert.equal(reorderForm({draft,issues:[]}).sourceOrderId,5);
});
