import assert from 'node:assert/strict';
import { test } from 'node:test';
import { removeAppliedOrderFilter } from './orderFilters.js';

const applied = {
  keyword: 'applied customer', category: 'denim', salespersonId: '2',
  dateFrom: '2026-10-01', dateTo: '2026-10-28', status: 'paid',
  country: 'Germany', style: 'GT-2026', sort: 'createdAt', direction: 'asc',
  page: 4, pageSize: 50,
};
const draft = { keyword: 'unsubmitted customer', category: 'outerwear', salespersonId: '7' };
const draftDates = ['2026-09-01', '2026-09-30'];

test('removing a category uses only the applied query and preserves every divergent input draft', () => {
  const result = removeAppliedOrderFilter(applied, 'category', draft, draftDates);
  assert.deepEqual(result.query, { ...applied, category: '', page: 1 });
  assert.deepEqual(result.filters, draft);
  assert.deepEqual(result.dates, draftDates);
  assert.equal(result.query.keyword, applied.keyword);
  assert.equal(result.query.salespersonId, applied.salespersonId);
});

test('an input still matching its removed applied chip is cleared, unrelated drafts are not', () => {
  const result = removeAppliedOrderFilter(applied, 'category', { ...draft, category: 'denim' }, draftDates);
  assert.deepEqual(result.filters, { ...draft, category: '' });
  assert.deepEqual(result.dates, draftDates);
});

test('business-owner chip removal does not apply a different draft owner', () => {
  const result = removeAppliedOrderFilter(applied, 'salespersonId', draft, draftDates);
  assert.deepEqual(result.query, { ...applied, salespersonId: '', page: 1 });
  assert.equal(result.filters.salespersonId, '7');
});

test('removing status, country or style never injects editable drafts into the request', () => {
  for (const key of ['status', 'country', 'style']) {
    const result = removeAppliedOrderFilter(applied, key, draft, draftDates);
    assert.deepEqual(result.query, { ...applied, [key]: '', page: 1 });
    assert.deepEqual(result.filters, draft);
    assert.deepEqual(result.dates, draftDates);
  }
});

test('removing either date endpoint clears both applied endpoints but preserves a new draft range', () => {
  for (const key of ['dateFrom', 'dateTo']) {
    const result = removeAppliedOrderFilter(applied, key, draft, draftDates);
    assert.deepEqual(result.query, { ...applied, dateFrom: '', dateTo: '', page: 1 });
    assert.deepEqual(result.dates, draftDates);
    assert.deepEqual(result.filters, draft);
  }
});

test('the removed applied date range is also cleared from an unchanged date input', () => {
  const result = removeAppliedOrderFilter(applied, 'dateTo', draft, [applied.dateFrom, applied.dateTo]);
  assert.equal(result.dates, null);
  assert.equal(result.query.dateFrom, '');
  assert.equal(result.query.dateTo, '');
  assert.deepEqual(result.filters, draft);
});

test('chip removal is immutable and retains explicit unsubmitted empty inputs', () => {
  const query = Object.freeze({ ...applied });
  const inputs = Object.freeze({ keyword: '', category: '', salespersonId: '' });
  const dates = Object.freeze([...draftDates]);
  const result = removeAppliedOrderFilter(query, 'category', inputs, dates);
  assert.deepEqual(result.filters, inputs);
  assert.deepEqual(result.dates, dates);
  assert.notEqual(result.query, query);
  assert.notEqual(result.filters, inputs);
  assert.notEqual(result.dates, dates);
  assert.equal(query.category, 'denim');
  assert.equal(result.query.pageSize, 50);
  assert.equal(result.query.sort, 'createdAt');
  assert.equal(result.query.direction, 'asc');
});
