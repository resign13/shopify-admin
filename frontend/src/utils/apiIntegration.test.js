import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { beijingTime, expiryISO, apiExamples, apiStates, apiCommonHeaders, apiReadEndpoints } from './apiIntegration.js';
test('Beijing expiry and display are independent of browser timezone',()=>{
  assert.equal(expiryISO('2099-10-19 12:30:00'),'2099-10-19T04:30:00.000Z');
  assert.equal(expiryISO(''),null);
  assert.throws(()=>expiryISO('2020-01-01 00:00:00'));
  assert.throws(()=>expiryISO('bad'));
  assert.equal(beijingTime('2026-10-19T04:30:00Z'),'2026-10-19 12:30:00');
  assert.equal(beijingTime(null),'—');
});
test('docs use token placeholders and cursor full scan with no credential persistence',()=>{
  const examples=apiExamples('https://example.test/api/external/v1');
  assert.match(examples.curl,/Bearer TOKEN/);
  const curlLines=examples.curl.split('\n');
  assert.equal(curlLines.length,3);
  assert.ok(curlLines[0].endsWith('\\') && curlLines[1].endsWith('\\'));
  assert.ok(curlLines[1].trimStart().startsWith('-H '));
  assert.doesNotMatch(examples.curl,/^\s*\+/m);
  assert.match(examples.python,/os.environ\["TOKEN"\]/);
  assert.match(examples.python,/nextCursor/);
  assert.doesNotMatch(JSON.stringify(examples),/localStorage|token=/);
  assert.equal(apiStates.admin_blocked,'管理员禁用');
});

test('docs distinguish common authentication, optional list filters and required identifiers',()=>{
  assert.deepEqual(apiCommonHeaders.filter(p=>p.required).map(p=>p.name),['Authorization']);
  assert.equal(apiCommonHeaders.find(p=>p.name==='Authorization').location,'请求头');
  assert.equal(apiCommonHeaders.find(p=>p.name==='Accept').required,false);
  const [list,product,inventory]=apiReadEndpoints;
  assert.equal(list.path,'/products');
  assert.equal(list.parameters.filter(p=>p.required).length,0);
  assert.deepEqual(list.parameters.map(p=>p.name),['limit','cursor','keyword','categoryId','styleCodes','skus']);
  assert.equal(list.parameters.find(p=>p.name==='limit').defaultValue,'50');
  assert.deepEqual(product.parameters.map(p=>[p.name,p.location,p.required]),[['productId','路径参数',true]]);
  assert.deepEqual(inventory.parameters.map(p=>[p.name,p.location,p.required]),[['productIds','查询参数',true]]);
  for(const p of [...apiCommonHeaders,...apiReadEndpoints.flatMap(e=>e.parameters)]) {
    assert.ok(p.name && p.location && p.type && p.defaultValue && p.description && p.example);
    assert.equal(typeof p.required,'boolean');
  }
});

test('documented query names and required inventory list match the actual read API parser',()=>{
  const source=readFileSync(new URL('../../../admin-backend/external_api.py',import.meta.url),'utf8');
  assert.match(source,/values\('productIds', required=True, ids=True\)/);
  assert.match(source,/positive\(request\.args\.get\('limit', '50'\), 100\)/);
  for(const name of ['cursor','keyword','categoryId'])assert.ok(source.includes(`request.args.get('${name}'`));
  assert.match(source,/\[\('styleCodes','style_code'\), \('skus','sku'\)\]/);
  assert.match(source,/product_id = positive\(str\(product_id\)\)/);
});

test('each read endpoint has a copyable authenticated GET example without a request body',()=>{
  const examples=apiExamples('https://example.test/api/external/v1');
  assert.match(examples.curl,/'https:\/\/example\.test\/api\/external\/v1\/products'$/);
  assert.doesNotMatch(examples.curl,/\?/);
  assert.match(examples.curlProduct,/\/products\/123'$/);
  assert.match(examples.curlFiltered,/--get --fail-with-body/);
  assert.match(examples.curlFiltered,/--data-urlencode 'styleCodes=CS2209,CS2211'/);
  assert.match(examples.curlInventory,/--get --fail-with-body/);
  assert.match(examples.curlInventory,/--data-urlencode 'productIds=123,456'/);
  for(const endpoint of apiReadEndpoints)assert.match(examples[endpoint.exampleKey],/Authorization: Bearer TOKEN/);
  for(const key of ['curl','curlFiltered','curlProduct','curlInventory']){
    assert.doesNotMatch(examples[key],/token=|api_key=|Cookie:|Content-Type:/i);
    const lines=examples[key].split('\n');
    assert.ok(lines.slice(0,-1).every(line=>line.endsWith('\\')));
  }
});

test('Python example retains full pagination and batches the entire catalog inventory',()=>{
  const source=apiExamples('https://example.test/api/external/v1').python;
  assert.match(source,/cursor = data\["nextCursor"\]/);
  assert.match(source,/for p in products\]/);
  assert.doesNotMatch(source,/products\[:100\]/);
  assert.match(source,/range\(0, len\(ids\), 100\)/);
  assert.match(source,/ids\[start:start \+ 100\]/);
  assert.match(source,/not_found_ids.extend\(data\["notFoundIds"\]\)/);
});
