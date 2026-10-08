import test from 'node:test';
import assert from 'node:assert/strict';
import { operationNames, operationFields, operationValue } from './orderOperations.js';

const statuses = { paid: '已付款', cancelled: '已取消' };
const money = value => `$${Number(value).toFixed(2)}`;

test('history formats statuses, amounts, zero and multiline notes without losing values', () => {
  assert.equal(operationValue('status', 'paid', statuses, money), '已付款');
  assert.equal(operationValue('status', 'future', statuses, money), 'future');
  assert.equal(operationValue('shippingFee', 0, statuses, money), '$0.00');
  assert.equal(operationValue('unitPrice', [12, 14], statuses, money), '$12.00 / $14.00');
  assert.equal(operationValue('quantity', 0, statuses, money), '0');
  assert.equal(operationValue('attachments', 1, statuses, money), '1 个文件');
  assert.equal(operationValue('note', 'First\nSecond', statuses, money), 'First\nSecond');
  assert.equal(operationValue('note', null, statuses, money), '未填写');
  assert.equal(operationValue('note', '', statuses, money), '未填写');
});

test('known actions and field labels match the order history response', () => {
  assert.equal(operationNames.restore, '恢复订单');
  assert.equal(operationNames.cancel, '取消订单');
  assert.equal(operationNames.update, '修改订单');
  assert.equal(operationNames.create, undefined);
  assert.equal(operationFields.quantity, '数量');
  assert.equal(operationFields.note, '备注');
  assert.equal(operationFields.attachments, '订单附件');
});
