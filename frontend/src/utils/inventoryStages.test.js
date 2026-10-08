import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { registrationError, moveProcurementStage, defectiveReturnPreview } from './inventoryStages.js';
const size = () => ({ sizeCode: 'M', stock: -5, contractPending: 10, pendingInspection: 8, pendingInbound: 4, temporaryInbound: 7, defectivePending: 3 });

test('defect and temporary quantity inputs use right-side integer step controls', () => {
  const view = readFileSync(new URL('../views/InventoryView.vue', import.meta.url), 'utf8');
  for (const field of ['defectivePending', 'temporaryInbound']) {
    const input = view.match(new RegExp(`<ElInputNumber\\s[^>]*v-model="row\\.${field}"[^>]*>`))?.[0];
    assert.ok(input, `${field} input exists`);
    assert.match(input, /controls-position="right"/);
    assert.doesNotMatch(input, /:controls="false"/);
    assert.match(input, /:min="0"/);
    assert.match(input, /:precision="0"/);
  }
});

test('bulk inventory actions require selection and select-all only touches current rows', () => {
  const view = readFileSync(new URL('../views/InventoryView.vue', import.meta.url), 'utf8');
  const table = readFileSync(new URL('../components/DataTable.vue', import.meta.url), 'utf8');
  assert.match(view, /:selectable="canEdit"/);
  assert.match(view, /@selection-change="selectedRows = \$event"/);
  assert.match(view, /selectedRows\.value\.map\(p => p\.id\)/);
  assert.match(table, /selectCurrentPage: \(\) => props\.rows\.forEach/);
  for (const source of ['normal', 'defective', 'temporary']) {
    assert.match(view, new RegExp(`:disabled="!selectedRows.length[^"\n]*" @click="prepareSelectedReceipt\\('${source}'\\)"`));
  }
});

test('inventory selection boxes have larger visuals and 44px click targets without affecting other tables', () => {
  const view = readFileSync(new URL('../views/InventoryView.vue', import.meta.url), 'utf8');
  const table = readFileSync(new URL('../components/DataTable.vue', import.meta.url), 'utf8');
  assert.match(view, /\blarge-selection\b/);
  assert.match(table, /largeSelection: Boolean/);
  assert.match(table, /:width="largeSelection \? 64 : 40"/);
  assert.match(table, /\.selection-large[^{}]*\.el-checkbox\)[\s\S]*?width: 44px;[\s\S]*?height: 44px;/);
  assert.match(table, /\.selection-large[^{}]*\.el-checkbox__inner\)[\s\S]*?width: 22px;[\s\S]*?height: 22px;/);
});
test('defects are an independent saved reserve, not a transfer', () => {
  const row=size(); assert.equal(registrationError([row]), '');
  assert.deepEqual(defectiveReturnPreview(row), { quantity: 3, contractAfter: 13, inspectionAfter: 5, defectiveAfter: 0 });
  assert.equal(row.stock,-5); assert.equal(row.temporaryInbound,7);
  row.defectivePending=9; assert.match(registrationError([row]), /不能超过待验货/);
});
test('qualified transfers cannot spend the defect reserve', () => {
  const row=size();row.pendingInbound=10;
  assert.match(moveProcurementStage(row,'inbound',10,4),/预留/);
  assert.equal(row.pendingInbound,4);assert.equal(row.pendingInspection,8);
  row.pendingInbound=9;assert.equal(moveProcurementStage(row,'inbound',9,4),'');
  assert.equal(row.pendingInspection,3);assert.equal(row.contractPending,10);
});
test('inspection edits preserve the reserve and procurement delta', () => {
  const row=size();row.pendingInspection=2;
  assert.match(moveProcurementStage(row,'inspection',2,8),/预留/);
  assert.equal(row.pendingInspection,8);assert.equal(row.contractPending,10);
  row.pendingInspection=5;assert.equal(moveProcurementStage(row,'inspection',5,8),'');
  assert.equal(row.contractPending,13);
});
test('signed stock and other stages remain integer bounded', () => {
  for (const field of ['contractPending','pendingInspection','pendingInbound','temporaryInbound','defectivePending']) {
    for (const bad of [-1, 1.5, 2147483648, null]) {
      assert.ok(registrationError([{...size(),[field]:bad}]));
    }
  }
  assert.equal(registrationError([{...size(),stock:-2147483648}]),'');
});
