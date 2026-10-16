import test from 'node:test';
import assert from 'node:assert/strict';
import { createSelectionRecord, selectionChanged, selectionChanges, selectionQuantity, selectionSizes,
  mergeSelectionQuantities, prepareSelectionApplication, orderProductSizes } from './orderSelection.js';
import { quoteTotal } from './orderPricing.js';

const product = (id = 1) => ({ id, sku: `SKU-${id}`, name: { zh: '商品' },
  sizePrices: [{ sizeCode: 'M', price: 12.3, stock: -3 }, { sizeCode: 'Tall XL', price: 15, stock: 0 }] });
const line = (extras = {}) => ({ productId: 1, sku: 'SKU-1', sizeCode: 'M', quantity: 3,
  unitPrice: 8, priceSource: 'manual', referencePriceUsd: 12.3, preserveQuote: true, ...extras });

test('each product keeps its own configured size order, including descending numeric codes', () => {
  const p=product();p.sizePrices=['36','34','32','30','28','S/28','均码','Tall XL'].map(sizeCode=>({sizeCode,price:9}));
  assert.deepEqual(selectionSizes(p),['36','34','32','30','28','S/28','均码','Tall XL']);
  const record=createSelectionRecord(p,[]);record.quantities['28']=2;record.quantities['S/28']=3;
  const result=prepareSelectionApplication([record],[p],[]);
  assert.equal(result.items.find(i=>i.sizeCode==='28').quantity,2);
  assert.equal(result.items.find(i=>i.sizeCode==='S/28').quantity,3);
  assert.equal(result.items.length,2);
  assert.deepEqual(selectionSizes(product()),['M','Tall XL']);
  assert.deepEqual(selectionSizes({sizePrices:[]}),[]);
});

test('prefills only exact real sizes; staged edits never mutate order lines', () => {
  const items = [line(), line({sizeCode:'Removed', quantity:7}), line({productId:2,quantity:9})];
  const before = structuredClone(items);
  const record = createSelectionRecord(product(), items);
  assert.deepEqual(record.quantities, { M: 3, 'Tall XL': 0 });
  assert.equal(selectionChanged(record), false);
  record.quantities.M = '2'; record.quantities['Tall XL'] = '4';
  assert.deepEqual(selectionChanges(record), [{sizeCode:'M',quantity:2},{sizeCode:'Tall XL',quantity:4}]);
  assert.deepEqual(items, before);
});

test('new zero-only rows are not pending; explicit zero clears existing quantities', () => {
  const fresh = createSelectionRecord(product(), []);
  assert.equal(selectionChanged(fresh), false);
  const record = createSelectionRecord(product(), [line()]);
  record.quantities.M = '0';
  assert.equal(selectionChanged(record), true);
  const result = prepareSelectionApplication([record], [product()], [line()]);
  assert.equal(result.items[0].quantity, 0);
  assert.equal(quoteTotal(result.items), 0);
  assert.deepEqual(result.notices, [{sku:'SKU-1',sizeCode:'M',before:3,after:0,clear:true}]);
  assert.deepEqual(prepareSelectionApplication([fresh], [product()], []).updates, []);
});

test('overwrite is not additive; every quote field and unrelated historical line survives', () => {
  const items = [line(), line({sizeCode:'Removed',quantity:2}),line({productId:2,quantity:4})];
  const before = structuredClone(items), record = createSelectionRecord(product(), items);
  record.quantities.M = 2; record.quantities['Tall XL'] = 1;
  const result = prepareSelectionApplication([record], [product()], items);
  assert.deepEqual(result.items[0], {...items[0],quantity:2});
  assert.deepEqual(result.items.slice(1,3), items.slice(1));
  assert.deepEqual(result.items[3], {productId:1,sku:'SKU-1',productName:'商品',sizeCode:'Tall XL',quantity:1,
    unitPrice:15,priceSource:'catalog',referencePriceUsd:15,preserveQuote:false});
  assert.equal(quoteTotal(result.items), 79);
  assert.deepEqual(items, before);
});

test('new positive sizes only; zero price and signed shortage do not block selection', () => {
  const p = product(); p.sizePrices[0].price = 0;
  const record = createSelectionRecord(p, []); record.quantities.M = 2;
  const result = prepareSelectionApplication([record], [p], []);
  assert.equal(result.items.length, 1);
  assert.equal(result.items[0].unitPrice, 0);
  assert.equal(result.items[0].quantity, 2);
});

test('invalid input is pending and rejected without truncation, clamping or partial merge', () => {
  for (const value of ['-1','1.2','1e2',2147483648,Infinity,true,'12a',' 1 ']) {
    const record = createSelectionRecord(product(), []); record.quantities.M = value;
    assert.equal(selectionChanged(record), true);
    assert.throws(() => selectionChanges(record), /SKU-1 \/ M/);
  }
  for (const value of ['',null,undefined,'0','000',0]) assert.equal(selectionQuantity(value), 0);
  assert.equal(selectionQuantity('2147483647'), 2147483647);
  const items = [line()], before = structuredClone(items);
  assert.throws(() => mergeSelectionQuantities(items, [{product:product(),quantities:[{sizeCode:'M',quantity:2}, {sizeCode:'Tall XL',quantity:-1}]}]));
  assert.deepEqual(items, before);
});

test('unavailable product and removed size reject the whole batch with useful identity', () => {
  const first = createSelectionRecord(product(), []), second = createSelectionRecord(product(2), []);
  first.quantities.M = 2; second.quantities.M = 3;
  assert.throws(() => prepareSelectionApplication([first,second], [product()], []), /SKU-2.*下架/);
  const p = product(2); p.sizePrices = [];
  assert.throws(() => prepareSelectionApplication([first,second], [product(),p], []), /SKU-2 \/ M.*尺码已移除/);
});

test('fresh directory price changes prompt only for new lines, never replace manual deals', () => {
  const record = createSelectionRecord(product(), [line()]);
  record.quantities.M = 2; record.quantities['Tall XL'] = 3;
  const fresh = product(); fresh.sizePrices.forEach(s => s.price = 20);
  const result = prepareSelectionApplication([record], [fresh], [line()]);
  assert.equal(result.items[0].unitPrice, 8);
  assert.equal(result.items[1].unitPrice, 20);
  assert.deepEqual(result.notices[1], {sku:'SKU-1',sizeCode:'Tall XL',oldPrice:15,newPrice:20});
});

test('repeated application cannot add quantity twice and uses a new baseline after apply', () => {
  const record = createSelectionRecord(product(), []); record.quantities.M = 2;
  const {updates,items} = prepareSelectionApplication([record], [product()], []);
  assert.deepEqual(mergeSelectionQuantities(items, updates), items);
  assert.equal(selectionChanged(createSelectionRecord(product(), items)), false);
});

test('line cap counts positive exact variants; zero historical placeholders do not consume slots', () => {
  const many = Array.from({length:500},(_,i)=>line({productId:10+i}));
  const update = [{product:product(),quantities:[{sizeCode:'M',quantity:1}]}];
  assert.throws(() => mergeSelectionQuantities(many,update), /500/);
  const result = mergeSelectionQuantities([...many.slice(1),line({productId:9,quantity:0})],update);
  assert.equal(result.filter(row=>row.quantity>0).length,500);
  assert.equal(many.length,500);
});

test('exact identities avoid color or size collisions and reject duplicate updates', () => {
  const p=product();p.sizePrices.push({sizeCode:'__proto__',price:3});
  const record=createSelectionRecord(p,[]);record.quantities.__proto__=2;
  assert.equal(selectionChanges(record)[0].sizeCode,'__proto__');
  const updates=[{product:p,quantities:[{sizeCode:'M',quantity:1},{sizeCode:'M',quantity:2}]}];
  assert.throws(()=>mergeSelectionQuantities([],updates),/重复应用/);
  assert.throws(()=>mergeSelectionQuantities([line(),line()],[]),/重复/);
});


test('explicit join accepts zero-only new SKU as a single draft anchor and never duplicates it', () => {
  const p=product(), record=createSelectionRecord(p,[]);
  const joined=prepareSelectionApplication([record],[p],[],'USD',null,{join:true});
  assert.equal(joined.items.length,1);
  assert.equal(joined.items[0].quantity,0);
  assert.equal(quoteTotal(joined.items),0);
  assert.deepEqual(mergeSelectionQuantities(joined.items,joined.updates),joined.items);
  assert.deepEqual(orderProductSizes(p,joined.items,p.id),['M','Tall XL']);
  const empty={id:2,sku:'NO-SIZE',sizePrices:[]};
  assert.throws(()=>prepareSelectionApplication([createSelectionRecord(empty,[])],[empty],[],'USD',null,{join:true}),/未配置尺码/);
  assert.throws(()=>prepareSelectionApplication([record],[],[],'USD',null,{join:true}),/下架/);
});

test('main editor sizes belong to each product and preserve old removed sizes without a cross-product union', () => {
  const p=product();p.sizePrices=['36','34','32'].map(sizeCode=>({sizeCode,price:9}));
  const items=[line({sizeCode:'Legacy XL'}),line({productId:2,sizeCode:'110'})];
  assert.deepEqual(orderProductSizes(p,items,1),['36','34','32','Legacy XL']);
  assert.deepEqual(orderProductSizes(undefined,items,1),['Legacy XL']);
  assert.deepEqual(orderProductSizes(product(2),items,2),['M','Tall XL','110']);
});
