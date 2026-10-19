import test from 'node:test';
import assert from 'node:assert/strict';
import { beijingTime, expiryISO, apiExamples, apiStates } from './apiIntegration.js';
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
