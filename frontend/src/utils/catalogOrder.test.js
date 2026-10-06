import assert from 'node:assert/strict';
import { readFileSync, existsSync } from 'node:fs';
import { test } from 'node:test';
import { compareProductCategories, sortProductsByCategory } from './catalogOrder.js';

test('category order, category ID tie-break, then stable intra-category order', () => {
  const items = [
    { id: 1, categoryId: 2, categorySortOrder: 2 },
    { id: 2, categoryId: 1, categorySortOrder: 1 },
    { id: 3, categoryId: 1, categorySortOrder: 1 },
    { id: 4, categoryId: 3, categorySortOrder: 1 },
    { id: 5 },
  ];
  assert.deepEqual([...items].sort(compareProductCategories).map((p) => p.id), [2, 3, 4, 1, 5]);
  assert.deepEqual(items.map((p) => p.id), [1, 2, 3, 4, 5]);
  assert.deepEqual([...items].sort((a, b) => compareProductCategories(a, b) || b.id - a.id).map((p) => p.id), [3, 2, 4, 1, 5]);
});

test('price sorting cannot split categories, mirrored storefront helper stays in sync', () => {
  const items = [
    { id: 1, categoryId: 2, categorySortOrder: 1, price: 1 },
    { id: 2, categoryId: 1, categorySortOrder: 0, price: 20 },
    { id: 3, categoryId: 1, categorySortOrder: 0, price: 10 },
  ];
  assert.deepEqual(items.sort((a, b) => compareProductCategories(a, b) || a.price - b.price).map((p) => p.id), [3, 2, 1]);
  const storefront = new URL('../../../../shopify/frontend/src/storefront/utils/catalogOrder.js', import.meta.url);
  if (existsSync(storefront)) {
    assert.equal(readFileSync(storefront, 'utf8'), readFileSync(new URL('./catalogOrder.js', import.meta.url), 'utf8'));
  }
});

test('admin table category fallback groups mixed API rows and preserves cached secondary order', () => {
  const categories = [{ key: 'outerwear' }, { key: 'denim' }];
  const products = [
    { id: 5, categoryKey: 'denim', stock: -8 },
    { id: 3, categoryKey: 'outerwear', stock: 6 },
    { id: 4, categoryKey: 'denim', stock: 10 },
    { id: 2, categoryKey: 'outerwear', stock: 20 },
    { id: 1, stock: 5 },
  ];
  assert.deepEqual(sortProductsByCategory(products, categories).map((p) => p.id), [3, 2, 5, 4, 1]);
  assert.deepEqual(sortProductsByCategory(products, [...categories].reverse()).map((p) => p.id), [5, 4, 3, 2, 1]);
  assert.deepEqual(products.map((p) => p.id), [5, 3, 4, 2, 1]);
  assert.equal(products[0].stock, -8);
});
