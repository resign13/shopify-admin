import test from 'node:test';
import assert from 'node:assert/strict';
import { allowedOrderStatuses, cancellationPending } from './orderCancellation.js';
import {roleModules,rolePermissions,defaultRoleModules,editableRolePermissions} from '../permissions.js';
const names=Object.fromEntries(['pending_payment','paid','partially_allocated','allocated','shipped','completed','cancelled'].map(x=>[x,x]));
test('partial allocation may go back; allocated and later never go back or directly cancel',()=>{
  assert.ok(allowedOrderStatuses({status:'partially_allocated'},names).pending_payment);
  assert.ok(allowedOrderStatuses({status:'partially_allocated'},names).paid);
  assert.deepEqual(Object.keys(allowedOrderStatuses({status:'paid'},names)),['paid','partially_allocated','allocated','shipped','completed']);
  assert.deepEqual(Object.keys(allowedOrderStatuses({status:'allocated'},names)),['allocated','shipped','completed']);
  assert.deepEqual(Object.keys(allowedOrderStatuses({status:'completed'},names)),['completed']);
});
test('cancelled restores only recorded source; pending requests freeze status choices',()=>{
  assert.deepEqual(Object.keys(allowedOrderStatuses({status:'cancelled',cancelledFromStatus:'paid'},names)),['paid','cancelled']);
  assert.deepEqual(Object.keys(allowedOrderStatuses({status:'cancelled'},names)),['cancelled']);
  const order={status:'allocated',cancelRequest:{state:'pending'}};
  assert.ok(cancellationPending(order));assert.deepEqual(Object.keys(allowedOrderStatuses(order,names)),['allocated']);
});
test('approval is an operation grant, not a module or a default staff grant',()=>{
  assert.ok(defaultRoleModules('admin').includes('orders.cancel.approve'));
  assert.ok(!defaultRoleModules('sales').includes('orders.cancel.approve'));
  assert.ok(!roleModules('admin').includes('orders.cancel.approve'));
  assert.ok(rolePermissions('sales').includes('orders.cancel.approve'));
  assert.deepEqual(editableRolePermissions('sales',['orders','orders.cancel.approve']),['orders','orders.cancel.approve']);
});
