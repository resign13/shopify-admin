import test from 'node:test';
import assert from 'node:assert/strict';
import { scaled, validAmount, validRate, convertAmount, catalogQuote, quoteTotal } from './orderPricing.js';
test('exact decimal validation and half-up conversion',()=>{
  assert.equal(scaled('7.123456',6),7123456n);assert.equal(scaled(0.000001,6),1n);
  for(const bad of [null,'',true,-1,Infinity,'NaN','1.001']) assert.equal(validAmount(bad),false);
  for(const bad of [null,0,'7.1234567',-1,Infinity]) assert.equal(validRate(bad),false);
  assert.equal(validAmount(0),true);assert.equal(validRate('7.123456'),true);
  assert.equal(convertAmount(2.33,'USD','CNY','7.123456'),16.60);
  assert.equal(quoteTotal([{unitPrice:16.60,quantity:3}],0),49.80);
  assert.equal(quoteTotal([{unitPrice:0.1,quantity:3}],0.2),0.5);
});
test('USD catalog quotes and negotiated totals work without an exchange rate',()=>{
  const first=catalogQuote('12.30');
  assert.equal(first.unitPrice,12.3);assert.equal(first.priceSource,'catalog');
  assert.equal(quoteTotal([{...first,quantity:3},{unitPrice:0,quantity:2}],1.11),38.01);
});
