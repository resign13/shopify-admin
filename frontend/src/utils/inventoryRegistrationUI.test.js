import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { quantityChange, registrationRowChanged } from './inventoryRegistrationUI.js';

test('quantity labels distinguish unchanged, added, reduced and incomplete drafts', () => {
  assert.deepEqual(quantityChange(8, 8), { text: '未变化', tone: 'unchanged', changed: false });
  assert.deepEqual(quantityChange(11, 8), { text: '+3', tone: 'increase', changed: true });
  assert.deepEqual(quantityChange(5, 8), { text: '-3', tone: 'decrease', changed: true });
  for (const invalid of [null, undefined, NaN, 1.5]) {
    assert.deepEqual(quantityChange(invalid, 0), { text: '待填写', tone: 'incomplete', changed: true });
  }
  assert.equal(quantityChange(2147483647, -2147483648).text, '+4294967295');
});

test('changed-size summary counts quantities, not read-only quota information', () => {
  const row = { stock: -5, originalStock: -5, contractPending: 10, originalPending: 10,
    pendingInspection: 8, originalInspection: 8, defectivePending: 3, originalDefective: 3,
    pendingInbound: 4, originalInbound: 4, temporaryInbound: 7, originalTemporary: 7 };
  assert.equal(registrationRowChanged(row), false);
  for (const field of ['stock', 'contractPending', 'pendingInspection', 'defectivePending', 'pendingInbound', 'temporaryInbound']) {
    assert.equal(registrationRowChanged({ ...row, [field]: row[field] + 1 }), true, field);
  }
  assert.equal(registrationRowChanged({ ...row, overdeliveryUsed: 15, overdeliveryRemaining: 0 }), false);
  assert.equal(registrationRowChanged({ ...row, temporaryInbound: undefined }), true);
});

test('presentation helpers do not mutate inventory or quota values', () => {
  const row = { stock: -5, originalStock: -5, contractPending: 0, originalPending: 1,
    pendingInspection: 115, originalInspection: 0, defectivePending: 0, originalDefective: 0,
    pendingInbound: 0, originalInbound: 0, temporaryInbound: 0, originalTemporary: 0,
    originalContractQuantity: 100, overdeliveryUsed: 15, overdeliveryRemaining: 0 };
  const before = structuredClone(row);
  registrationRowChanged(Object.freeze(row));
  quantityChange(row.stock, row.originalStock);
  assert.deepEqual(row, before);
});

test('allowance details are accessible by click and retain all quota fields without tall table notes', () => {
  const view = readFileSync(new URL('../views/InventoryView.vue', import.meta.url), 'utf8');
  const allowance = readFileSync(new URL('../components/InventoryInspectionAllowance.vue', import.meta.url), 'utf8');
  assert.match(view, /<InventoryInspectionAllowance :row="row"/);
  assert.doesNotMatch(view, /overdelivery-note/);
  assert.match(allowance, /<ElPopover trigger="click"/);
  assert.match(allowance, /:aria-label="`验货额度 \$\{row.sizeCode\}`"/);
  for (const field of ['originalContractQuantity', 'overdeliveryLimit', 'overdeliveryUsed', 'overdeliveryRemaining', 'overdeliveryInspection']) {
    assert.match(allowance, new RegExp(`row\\.${field}`));
  }
  assert.equal((view.match(/<InventoryQuantityChange /g) || []).length, 6);
});
