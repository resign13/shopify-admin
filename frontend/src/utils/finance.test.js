import test from 'node:test';
import assert from 'node:assert/strict';
import {financeCostPageSize,financeCostFilters,financeCostKey,financeCodes,financeActiveStates,financeReportDates,financeReportKey,batchTargets,clearBatchTargets,costChanges,costValue} from './finance.js';
import {roleModules,defaultRoleModules,editableRolePermissions,moduleGroups} from '../permissions.js';

test('partially allocated orders remain in default finance reports',()=>{
  assert.ok(financeActiveStates.includes('partially_allocated'));
  const query=JSON.parse(financeReportKey({statuses:[],exchangeRate:7}));
  assert.ok(query.statuses.includes('partially_allocated'));
});
test('finance is an explicit capability, never inferred for sales',()=>{
  assert.deepEqual(defaultRoleModules('finance'),['finance','contracts']);assert.ok(roleModules('admin').includes('finance'));
  for(const r of ['sales','warehouse','customer'])assert.ok(!defaultRoleModules(r).includes('finance'));
  assert.ok(roleModules('sales').includes('finance'));assert.ok(!roleModules('customer').includes('finance'));
});

test('all staff departments can opt into modules without silently receiving them',()=>{
 const modules=moduleGroups.flatMap(group=>group.items.map(([key])=>key));
 for(const role of ['admin','sales','warehouse','finance']){
  assert.deepEqual(roleModules(role),modules);
  assert.deepEqual(editableRolePermissions(role,['finance','contracts','admin-users']),['finance','contracts','admin-users']);
  assert.deepEqual(editableRolePermissions(role,[]),[]);
 }
 assert.deepEqual(defaultRoleModules('warehouse'),['inventory','orders']);
 assert.deepEqual(editableRolePermissions('finance',['finance']),['finance']);
 assert.deepEqual(editableRolePermissions('customer',['finance','inventory','contracts']),['inventory']);
 const selected=defaultRoleModules('finance');selected.push('orders');
 assert.deepEqual(defaultRoleModules('finance'),['finance','contracts']);
});
test('batch updates selected styles, independent of colors and sizes',()=>{
  assert.equal(financeCostPageSize,20);
  const rows=[{styleCode:'A',costCny:null,draftCost:undefined,version:'0'},
    {styleCode:'B',costCny:'0.00',draftCost:0,version:'1'},
    {styleCode:'C',costCny:'2.00',draftCost:2,version:'1'}];
  const targets=batchTargets(rows,['A','B']);assert.equal(targets.length,2);
  targets.forEach(row=>row.draftCost=10.25);
  assert.deepEqual(costChanges(rows),[{styleCode:'A',costCny:'10.25',version:'0'},{styleCode:'B',costCny:'10.25',version:'1'}]);
  assert.equal(rows[2].draftCost,2);assert.equal(costValue(undefined),null);
});
test('multi-code search supports both comma forms',()=>assert.deepEqual(financeCodes(' A,B，A, '),['A','B']));
test('cost export uses only normalized last-queried filters, never pagination or draft data',()=>{
  const query={styleCodes:' A,B，A, ',keyword:' black ',category:'denim',missingOnly:false,page:2,pageSize:20,selected:['A'],costCny:'123'};
  assert.deepEqual(financeCostFilters(query),{styleCodes:'A,B',keyword:'black',category:'denim',missingOnly:false});
  assert.equal(financeCostKey(query),financeCostKey({...query,styleCodes:'b,a'}));
  for(const change of [{styleCodes:'A'},{keyword:'blue'},{category:''},{missingOnly:true}])assert.notEqual(financeCostKey(query),financeCostKey({...query,...change}));
});
test('default reporting period covers thirty Beijing calendar dates across year boundaries',()=>{
  assert.deepEqual(financeReportDates('2026-01-01'),{dateFrom:'2025-12-03',dateTo:'2026-01-01'});
  assert.deepEqual(financeReportDates('2024-03-01'),{dateFrom:'2024-02-01',dateTo:'2024-03-01'});
});
test('report dirty state compares normalized queries without losing multi-code or numeric precision',()=>{
  const original={...financeReportDates('2026-10-13'),customerName:' Alice ',customerId:3,salespersonIds:[2,1],styleCodes:['A，B','A'],statuses:[...financeActiveStates],exchangeRate:7.123456};
  const server={...original,customerName:'Alice',customerId:'3',salespersonIds:['1','2'],styleCodes:['B','A'],statuses:[...financeActiveStates].reverse(),exchangeRate:'7.123456'};
  assert.equal(financeReportKey(original),financeReportKey(server));
  for(const change of [{dateTo:'2026-10-12'},{customerName:'Bob'},{customerId:null},{salespersonIds:['unassigned']},{styleCodes:['A']},{statuses:['paid']},{exchangeRate:7.123457}])assert.notEqual(financeReportKey({...original,...change}),financeReportKey(original));
  assert.equal(financeReportKey({...original,statuses:[]}),financeReportKey(original));
  assert.notEqual(financeReportKey({...original,exchangeRate:null}),financeReportKey(original));
  assert.deepEqual(original.salespersonIds,[2,1]);assert.deepEqual(original.styleCodes,['A，B','A']);
});
test('clearing only selected styles includes zero and preserves others',()=>{
  const rows=[{styleCode:'A',costCny:'5.00',draftCost:5,version:'1'},
    {styleCode:'B',costCny:'0.00',draftCost:0,version:'2'},
    {styleCode:'C',costCny:'9.00',draftCost:9,version:'1'},
    {styleCode:'D',costCny:null,draftCost:undefined,version:'0'}];
  const targets=clearBatchTargets(rows,['A','B','D']);assert.equal(targets.length,2);
  targets.forEach(row=>row.draftCost=undefined);
  assert.deepEqual(costChanges(rows),[{styleCode:'A',costCny:null,version:'1'},{styleCode:'B',costCny:null,version:'2'}]);
  assert.equal(rows[2].draftCost,9);assert.equal(clearBatchTargets(rows,['A','B','D']).length,0);
  assert.equal(clearBatchTargets(rows,[]).length,0);assert.equal(batchTargets(rows,['OTHER']).length,0);
});
test('clearing a newly entered unsaved cost restores missing state without generating a save',()=>{
  const rows=[{styleCode:'A',costCny:null,draftCost:20,version:'0'}];
  clearBatchTargets(rows,['A']).forEach(row=>row.draftCost=undefined);
  assert.deepEqual(costChanges(rows),[]);
});
