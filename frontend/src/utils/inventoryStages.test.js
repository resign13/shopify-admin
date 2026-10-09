import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { registrationError, moveProcurementStage, defectiveReturnPreview, procurementPreview } from './inventoryStages.js';
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

const contractBase = () => ({contractPending:100,pendingInspection:0,pendingInbound:0,
  originalContractQuantity:100,contractReceived:0,overdeliveryLimit:15,overdeliveryUsed:0,overdeliveryInspection:0,overdeliveryQualified:0});
test('original-contract allowance accepts 115, rejects 116, and never makes pending negative', () => {
  const base=contractBase();const extra=procurementPreview(base,115,0);
  assert.equal(extra.contractPending,0);assert.equal(extra.overdeliveryUsed,15);assert.equal(extra.overdeliveryInspection,15);
  assert.throws(()=>procurementPreview(base,116,0),/累计15%/);
  assert.equal(procurementPreview({...base,originalContractQuantity:6,contractPending:6,overdeliveryLimit:0},6,0).overdeliveryUsed,0);
});
test('qualified transfers preserve provenance; draft undo does not spend quota', () => {
  const base=contractBase();const row={...base,sizeCode:'M',stock:0,temporaryInbound:0,defectivePending:0,registrationBase:base};
  row.pendingInspection=115;assert.equal(moveProcurementStage(row,'inspection',115,0),'');
  assert.equal(row.overdeliveryUsed,15);assert.equal(row.contractPending,0);
  row.pendingInspection=100;assert.equal(moveProcurementStage(row,'inspection',100,115),'');
  assert.equal(row.overdeliveryUsed,0);
  row.pendingInbound=100;assert.equal(moveProcurementStage(row,'inbound',100,0),'');
  assert.equal(row.pendingInspection,0);
  const delivered={...base,contractPending:0,pendingInspection:115,...procurementPreview(base,115,0)};
  assert.equal(procurementPreview(delivered,0,115).overdeliveryQualified,15);
  assert.equal(defectiveReturnPreview({...delivered,defectivePending:20}).contractAfter,5);
});
test('spent quota and original normal counter cannot be renewed by pending edits', () => {
  const base={...contractBase(),contractReceived:100,contractPending:100};
  assert.throws(()=>procurementPreview(base,16,0),/累计15%/);
  assert.equal(procurementPreview(base,15,0).overdeliveryUsed,15);
  assert.throws(()=>procurementPreview({...base,overdeliveryUsed:15},1,0),/累计15%/);
});
test('stage edits do not silently discard manual contract adjustments', () => {
  const base=contractBase();const row={...base,registrationBase:base,contractPending:101,pendingInspection:10,defectivePending:0};
  assert.match(moveProcurementStage(row,'inspection',10,0),/先单独保存/);
  assert.equal(row.contractPending,101);assert.equal(row.pendingInspection,0);
});
