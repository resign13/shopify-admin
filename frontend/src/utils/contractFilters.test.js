import test from 'node:test';
import assert from 'node:assert/strict';
import {contractExportQuery} from './contractFilters.js';

test('batch export keeps applied keyword and month but not list pagination',()=>{
  const query=new URLSearchParams(contractExportQuery({keyword:'  工厂 A ',createdMonth:'2026-11',page:3,pageSize:25}));
  assert.deepEqual(Object.fromEntries(query),{keyword:'工厂 A',createdMonth:'2026-11'});
});
test('selected contracts are deduplicated and distinguish an empty selection from all results',()=>{
  assert.equal(new URLSearchParams(contractExportQuery({},[3,1,3])).get('contractIds'),'3,1');
  assert.equal(new URLSearchParams(contractExportQuery({},[])).get('contractIds'),'');
  assert.equal(new URLSearchParams(contractExportQuery({})).has('contractIds'),false);
});
test('cleared filters do not leave a stale creation month in export',()=>{
  assert.equal(contractExportQuery({keyword:'',createdMonth:null,page:2}), '');
});
