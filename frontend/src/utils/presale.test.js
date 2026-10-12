import { test } from 'node:test'
import assert from 'node:assert/strict'
import { moveStyle, selectedStyles } from './presale.js'
import { roleModules, defaultRoleModules, editableRolePermissions, moduleGroups } from '../permissions.js'
const items=[{styleCode:'OLD',firstListedAt:'2020-01-01',firstProductId:1},{styleCode:'NEW',firstListedAt:'2025-01-01',firstProductId:2}]
test('automatic newest first and missing references stay visible',()=>{
 assert.deepEqual(selectedStyles(['OLD','MISSING','NEW'],items,'automatic').map(r=>r.styleCode),['NEW','OLD','MISSING'])
 assert.equal(selectedStyles(['MISSING'],items,'automatic')[0].missing,true)
})
test('manual cross-category move and append are non-mutating',()=>{
 const source=['OLD','NEW'];assert.deepEqual(moveStyle(source,1,0),['NEW','OLD']);assert.deepEqual(source,['OLD','NEW'])
 assert.deepEqual(selectedStyles(source,items,'manual').map(r=>r.styleCode),source)
 assert.deepEqual(moveStyle(source,0,-1),source)
})
test('presale is an opt-in sales capability, not a default or a warehouse/customer module',()=>{
 assert.ok(roleModules('sales').includes('presale'));assert.ok(!defaultRoleModules('sales').includes('presale'))
 assert.ok(defaultRoleModules('admin').includes('presale'))
 for(const role of ['warehouse','customer'])assert.ok(!roleModules(role).includes('presale'))
 const keys=moduleGroups.flatMap(g=>g.items.map(([key])=>key))
 for(const old of ['home-config','activity-zone/apply','activity-zone/manage'])assert.ok(!keys.includes(old))
})

test('editing legacy accounts drops retired hidden permissions without granting presale',()=>{
 assert.deepEqual(editableRolePermissions('sales',['orders','home-config','activity-zone/apply','products']),['orders','products'])
 assert.ok(!editableRolePermissions('sales',null).includes('presale'))
 assert.deepEqual(editableRolePermissions('sales',['orders','presale']),['orders','presale'])
 assert.deepEqual(editableRolePermissions('warehouse',['orders','presale']),['orders'])
})
