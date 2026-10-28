import test from 'node:test';
import assert from 'node:assert/strict';
import { scaled, validAmount, validRate, convertAmount, catalogQuote, prepareCatalogPriceRestore, quoteTotal } from './orderPricing.js';
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

const restoreLines = () => [
  { productId:1, sizeCode:'M', quantity:2, unitPrice:11, priceSource:'manual', preserveQuote:true, conversionBase:{USD:11}, catalogPriceChanged:true },
  { productId:1, sizeCode:'L', quantity:0, unitPrice:12, priceSource:'manual', preserveQuote:true },
];
const restoreProducts = prices => ({1:{sizePrices:prices.map(([sizeCode,price])=>({sizeCode,price}))}});

test('catalog restore prepares the whole row, preserves quantities and supports zero price',()=>{
  const lines=restoreLines(), before=structuredClone(lines);
  const restored=prepareCatalogPriceRestore(lines,restoreProducts([['M',29.9],['L',0]]));
  assert.deepEqual(lines,before);
  assert.deepEqual(restored.map(line=>[line.quantity,line.unitPrice,line.priceSource,line.referencePriceUsd,line.preserveQuote]),[
    [2,29.9,'catalog',29.9,false],[0,0,'catalog',0,false],
  ]);
  assert.equal(restored[0].conversionBase,undefined);
  assert.equal(restored[0].catalogPriceChanged,false);
  assert.notEqual(restored[0],lines[0]);
});

test('historical missing size rejects restore without altering any earlier or later line',()=>{
  for(const sizes of [[['M',29.9]],[['L',29.9]],[]]) {
    const lines=restoreLines(), before=structuredClone(lines);
    assert.throws(()=>prepareCatalogPriceRestore(lines,restoreProducts(sizes)),/原尺码已移除/);
    assert.deepEqual(lines,before);
  }
});

test('late invalid catalog quote or conversion failure leaves all negotiated prices intact',()=>{
  for(const price of ['',-1,'NaN','1.001']) {
    const lines=restoreLines(), before=structuredClone(lines);
    assert.throws(()=>prepareCatalogPriceRestore(lines,restoreProducts([['M',29.9],['L',price]])));
    assert.deepEqual(lines,before);
  }
  const lines=restoreLines(), before=structuredClone(lines);
  assert.throws(()=>prepareCatalogPriceRestore(lines,restoreProducts([['M',1],['L',9999999999.99]]),'CNY',7.2),/换算金额超出范围/);
  assert.deepEqual(lines,before);
  assert.throws(()=>prepareCatalogPriceRestore(lines,restoreProducts([['M',1],['L',2]]),'CNY',null),/有效本单汇率/);
  assert.deepEqual(lines,before);
});

test('successful whole-row restore uses the current order currency and exact conversion',()=>{
  const lines=restoreLines();
  const restored=prepareCatalogPriceRestore(lines,restoreProducts([['M',2.33],['L',0]]),'CNY','7.123456');
  assert.deepEqual(restored.map(line=>line.unitPrice),[16.6,0]);
  assert.deepEqual(lines.map(line=>line.unitPrice),[11,12]);
});
