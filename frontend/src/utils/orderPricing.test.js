import test from 'node:test';
import assert from 'node:assert/strict';
import { scaled, validAmount, validRate, convertAmount, catalogQuote, quoteTotal, previewQuoteChange } from './orderPricing.js';
test('exact decimal validation and half-up conversion',()=>{
  assert.equal(scaled('7.123456',6),7123456n);assert.equal(scaled(0.000001,6),1n);
  for(const bad of [null,'',true,-1,Infinity,'NaN','1.001']) assert.equal(validAmount(bad),false);
  for(const bad of [null,0,'7.1234567',-1,Infinity]) assert.equal(validRate(bad),false);
  assert.equal(validAmount(0),true);assert.equal(validRate('7.123456'),true);
  assert.equal(convertAmount(2.33,'USD','CNY','7.123456'),16.60);
  assert.equal(quoteTotal([{unitPrice:16.60,quantity:3}],0),49.80);
  assert.equal(quoteTotal([{unitPrice:0.1,quantity:3}],0.2),0.5);
});
test('currency round trips use the original manual quote, not rounded intermediate prices',()=>{
  const quote={currency:'USD',exchangeRate:7.123456,shippingFee:2.33,items:[{unitPrice:2.33,quantity:3,priceSource:'manual'}]};
  const cny=previewQuoteChange(quote,'CNY',7.123456);
  assert.equal(cny.items[0].unitPrice,16.60);
  const usd=previewQuoteChange(cny,'USD',7.123456);
  assert.equal(usd.items[0].unitPrice,2.33);assert.equal(usd.shippingFee,2.33);
  assert.equal(quote.items[0].unitPrice,2.33);
});
test('rate-only updates reprice catalog draft rows but preserve negotiated and saved prices',()=>{
  const quote={currency:'CNY',exchangeRate:7,shippingFee:10,items:[{quantity:1,...catalogQuote(10,'CNY',7)}, {quantity:0,unitPrice:66,priceSource:'manual'}]};
  const preview=previewQuoteChange(quote,'CNY',7.2);
  assert.equal(preview.items[0].unitPrice,72);assert.equal(preview.items[1].unitPrice,66);assert.equal(preview.shippingFee,10);
  const saved=previewQuoteChange(quote,'CNY',7.2,true);
  assert.equal(saved.items[0].unitPrice,70);assert.equal(saved.items[0].priceSource,'manual');
});
test('CNY requires an FX rate but USD still works without finance settings',()=>{
  const quote={currency:'USD',exchangeRate:null,shippingFee:0,items:[{quantity:1,...catalogQuote(0)}]};
  assert.equal(previewQuoteChange(quote,'USD',null).items[0].unitPrice,0);
  assert.throws(()=>previewQuoteChange(quote,'CNY',null));
  assert.throws(()=>convertAmount(9999999999.99,'USD','CNY',7));
});
test('changing the rate resets manual conversion anchors but never changes a native negotiated quote',()=>{
  const usd={currency:'USD',exchangeRate:7,shippingFee:1,items:[{unitPrice:10,quantity:1,priceSource:'manual'}]};
  const cny=previewQuoteChange(usd,'CNY',7);
  const newRate=previewQuoteChange(cny,'CNY',8);
  assert.equal(newRate.items[0].unitPrice,70);assert.equal(newRate.shippingFee,7);
  const back=previewQuoteChange(newRate,'USD',8);
  assert.equal(back.items[0].unitPrice,8.75);assert.equal(back.shippingFee,0.88);
});
test('serialized draft anchors preserve a small negotiated quote across currency toggles',()=>{
  const quote={currency:'USD',exchangeRate:0.4,shippingFee:0.07,items:[{unitPrice:0.07,quantity:1,priceSource:'manual'}]};
  const saved=JSON.parse(JSON.stringify(previewQuoteChange(quote,'CNY',0.4)));
  assert.equal(saved.items[0].unitPrice,0.03);
  const resumed=previewQuoteChange(saved,'USD',0.4);
  assert.equal(resumed.items[0].unitPrice,0.07);assert.equal(resumed.shippingFee,0.07);
});
