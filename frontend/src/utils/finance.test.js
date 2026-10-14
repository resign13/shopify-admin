import test from 'node:test';
import assert from 'node:assert/strict';
import {financeCodes,financeActiveStates,financeReportDates,financeReportKey,batchTargets,clearBatchTargets,costChanges,costValue} from './finance.js';
import {roleModules,defaultRoleModules,editableRolePermissions,moduleGroups} from '../permissions.js';
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
test('real-size batch selection neither adds sizes nor touches unselected variants',()=>{
  const rows=[{id:1,sizes:[{sizeCode:'Tall XL',costCny:null,draftCost:undefined,version:'0'}]},
    {id:2,sizes:[{sizeCode:'S',costCny:'0.00',draftCost:0,version:'1'}]},
    {id:3,sizes:[{sizeCode:'Tall XL',costCny:'2.00',draftCost:2,version:'1'}]}];
  const targets=batchTargets(rows,[1,2],'Tall XL');assert.equal(targets.length,1);
  targets[0].size.draftCost=0;assert.deepEqual(costChanges(rows),[{productId:1,sizeCode:'Tall XL',costCny:'0.00',version:'0'}]);
  assert.equal(batchTargets(rows,[1,2],'').length,2);assert.equal(costValue(undefined),null);
});
test('multi-code search supports both comma forms',()=>assert.deepEqual(financeCodes(' A,B，A, '),['A','B']));
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
test('clearing respects selected colors and real size, including zero, without clearing other costs',()=>{
  const rows=[{id:1,sizes:[{sizeCode:'S',costCny:'5.00',draftCost:5,version:'1'},{sizeCode:'M',costCny:'7.00',draftCost:7,version:'1'}]},
    {id:2,sizes:[{sizeCode:'S',costCny:'0.00',draftCost:0,version:'2'},{sizeCode:'M',costCny:null,draftCost:undefined,version:'0'}]},
    {id:3,sizes:[{sizeCode:'S',costCny:'9.00',draftCost:9,version:'1'}]}];
  const targets=clearBatchTargets(rows,[1,2],'S');assert.equal(targets.length,2);
  targets.forEach(({size})=>size.draftCost=undefined);
  assert.deepEqual(costChanges(rows),[{productId:1,sizeCode:'S',costCny:null,version:'1'},{productId:2,sizeCode:'S',costCny:null,version:'2'}]);
  assert.equal(rows[0].sizes[1].draftCost,7);assert.equal(rows[2].sizes[0].draftCost,9);
  assert.equal(clearBatchTargets(rows,[1,2],'S').length,0);assert.equal(clearBatchTargets(rows,[1,2],'').length,1);
  assert.equal(clearBatchTargets(rows,[1,2],'Nonexistent').length,0);assert.equal(clearBatchTargets(rows,[],'').length,0);
});
test('clearing a newly entered unsaved cost restores missing state without generating a save',()=>{
  const rows=[{id:1,sizes:[{sizeCode:'Tall XL',costCny:null,draftCost:20,version:'0'}]}];
  clearBatchTargets(rows,[1],'Tall XL').forEach(({size})=>size.draftCost=undefined);
  assert.deepEqual(costChanges(rows),[]);
});
