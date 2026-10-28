import assert from 'node:assert/strict';
import { test } from 'node:test';
import { readFileSync } from 'node:fs';
import { createTableSort, normalizeSortState, queryToSortState, sortStateToQuery } from './tableSort.js';

// Models Element Plus's synchronous sort-change echo and useList's query merge.
// The production controller and conversion helpers are used, not copied logic.
function fixture(initial, defaults = {}) {
  let query = { page: 4, pageSize: 25, ...defaults, ...initial }, requests = 0;
  let controller;
  const changes = [], calls = [];
  const table = {
    sort(prop, order) { calls.push({ prop, order }); controller.change({ prop, order }); },
    clearSort() { calls.push({ prop: '', order: null }); },
  };
  const changed = value => {
    changes.push(value);
    query = { ...query, ...sortStateToQuery(value, defaults), page: 1 };
    requests++;
    controller.sync(queryToSortState(query), table);
  };
  const mount = () => {
    controller = createTableSort(queryToSortState(query), changed);
    controller.sync(queryToSortState(query), table);
  };
  mount();
  return {
    get state() { return controller.value; }, get query() { return query; },
    get requests() { return requests; }, changes, calls, mount,
    user: value => controller.change(value),
    restore: () => controller.sync(controller.value, table),
    external(next) { query = { ...query, ...next }; controller.sync(queryToSortState(query), table); },
  };
}

test('URL/cache sort initializes the indicator without emitting or resetting page', () => {
  const f = fixture({ sort: 'totalAmount', direction: 'asc' });
  assert.deepEqual(f.state, { prop: 'totalAmount', order: 'ascending' });
  assert.equal(f.query.page, 4);
  assert.equal(f.requests, 0);
  assert.equal(f.changes.length, 0);
});

test('filterKey remount reconstructs the indicator from the authoritative query', () => {
  const f = fixture({ sort: 'createdAt', direction: 'desc' });
  f.external({ sort: 'totalAmount', direction: 'asc', page: 3, status: 'paid' });
  f.mount();
  assert.deepEqual(f.state, { prop: 'totalAmount', order: 'ascending' });
  assert.equal(f.query.page, 3);
  assert.equal(f.requests, 0);
});

test('phone More sorting then PC recreation restores the new arrow with one user request', () => {
  const f = fixture({ sort: 'createdAt', direction: 'desc' });
  f.external({ sort: 'totalAmount', direction: 'asc', page: 1 }); // phone parent list.sort
  f.restore(); // desktop ElTable recreated after phone
  assert.deepEqual(f.calls.at(-1), { prop: 'totalAmount', order: 'ascending' });
  assert.equal(f.requests, 0); // the parent action owns its request, no echo query
  assert.equal(f.user({ prop: 'stock', order: 'descending' }), true);
  f.restore();
  assert.equal(f.requests, 1);
  assert.deepEqual(f.state, { prop: 'stock', order: 'descending' });
});

test('external reset/route back and repeated sync never emit or reset page', () => {
  const f = fixture({ sort: 'createdAt', direction: 'desc' });
  f.external({ sort: '', direction: '', page: 5 });
  f.restore();
  assert.deepEqual(f.state, { prop: '', order: null });
  assert.deepEqual(f.calls.at(-1), { prop: '', order: null });
  assert.equal(f.query.page, 5);
  assert.equal(f.requests, 0);
});

test('Element Plus null order clears the old prop, and its duplicate echo emits once', () => {
  const f = fixture({ sort: 'stock', direction: 'asc' });
  assert.equal(f.user({ prop: 'stock', order: null }), true);
  assert.equal(f.user({ prop: 'stock', order: null }), false);
  assert.deepEqual(f.state, { prop: '', order: null });
  assert.equal(f.query.sort, '');
  assert.equal(f.query.direction, '');
  assert.equal(f.requests, 1);
  assert.deepEqual(f.changes, [{ prop: '', order: null }]);
});

test('clearing Products/Inventory restores category default without a route-default reload', () => {
  const defaults = { sort: 'category' };
  const f = fixture({ sort: 'stock', direction: 'asc' }, defaults);
  f.user({ prop: 'stock', order: null });
  assert.deepEqual(f.state, { prop: '', order: null });
  assert.equal(f.query.sort, 'category');
  const normalize = q => JSON.stringify(Object.entries(q).filter(([, v]) => v !== '' && v != null).map(([k,v]) => [k,String(v)]).sort());
  const route = Object.fromEntries(Object.entries(f.query).filter(([,v]) => v !== '' && v != null));
  assert.equal(normalize(f.query), normalize({ page: 1, pageSize: 25, ...defaults, ...route }));
  assert.equal(f.requests, 1);
  f.restore();
  assert.equal(f.requests, 1);
});

test('default category is not exposed as a nonexistent phone option; explicit defaults remain intact', () => {
  assert.deepEqual(queryToSortState({ sort: 'category', direction: 'asc' }), { prop: '', order: null });
  assert.deepEqual(sortStateToQuery({ prop: 'old', order: null }, { sort: 'createdAt', direction: 'asc' }), { sort: 'createdAt', direction: 'asc' });
});

test('legacy uncontrolled consumers keep local sort state, with no duplicate user events', () => {
  const events = [], controller = createTableSort(undefined, value => events.push(value));
  controller.change({ prop: 'stock', order: 'descending' });
  controller.change({ prop: 'stock', order: 'descending' });
  assert.deepEqual(controller.value, { prop: 'stock', order: 'descending' });
  assert.equal(events.length, 1);
  controller.sync(controller.value, { sort: (prop, order) => controller.change({ prop, order }) });
  assert.equal(events.length, 1);
  assert.deepEqual(normalizeSortState({ prop: 'stock', order: undefined }), { prop: '', order: null });
});

test('shared components wire optional controlled props and clear-safe useList conversion', () => {
  const source = name => readFileSync(new URL(name, import.meta.url), 'utf8');
  const table = source('../components/AdaptiveTable.js');
  assert.match(table, /sortState: \{ type: Object, default: undefined \}/);
  assert.match(table, /watch\(\[\s*\(\) => props\.sortState\?\.prop,\s*\(\) => props\.sortState\?\.order,\s*\(\) => props\.sortState !== undefined,/);
  assert.match(table, /watch\(table, restoreSort\)/);
  assert.match(table, /defaultSort: sort\.value,/);
  assert.match(table, /sorting\.change\(value\)/);
  assert.match(source('../components/DataTable.vue'), /:sort-state="sortState"/);
  assert.match(source('../composables/workbench.js'), /\.\.\.sortStateToQuery\(\{ prop, order \}, defaults\)/);
});
