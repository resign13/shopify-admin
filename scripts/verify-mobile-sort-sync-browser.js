// Last stage of admin-mobile-browser-fixture.py's shared authenticated CI loop.
// Only the existing synthetic fixture's category-order PUT is permitted.
async (page) => {
  const base = 'http://127.0.0.1:5380';
  if (new URL(page.url()).origin !== base || new URL(page.url()).pathname === '/login')
    throw Error('Authenticated isolated loopback 5380 *_test fixture required');
  const checks = [], screenshots = [], errors = [], deniedWrites = [], categoryWrites = [];
  const reads = new Map();
  const check = (value, message) => { if (!value) throw Error(message); checks.push(message); };
  const onError = error => errors.push(new URL(page.url()).pathname + ': ' + error.message);
  const onRequest = request => {
    const url = new URL(request.url());
    if (url.origin === base && request.method() === 'GET')
      reads.set(url.pathname, (reads.get(url.pathname) || 0) + 1);
  };
  const writeGuard = async route => {
    const request = route.request(), url = new URL(request.url());
    if (['GET', 'HEAD', 'OPTIONS'].includes(request.method())) return route.fallback();
    if (url.pathname === '/api/admin/categories/order' && request.method() === 'PUT') {
      categoryWrites.push(request.postDataJSON());
      return route.fallback();
    }
    deniedWrites.push(request.method() + ' ' + url.pathname);
    await route.abort('blockedbyclient');
  };
  const count = resource => reads.get('/api/admin/' + resource) || 0;
  const settle = async () => {
    await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
    await page.waitForLoadState('networkidle');
    check(!deniedWrites.length, 'No writes outside the category-order fixture operation');
  };
  const read = path => page.evaluate(async path => {
    const response = await fetch('/api/admin/' + path);
    if (!response.ok) throw Error('Fixture read failed: ' + path + ' ' + response.status);
    return response.json();
  }, path);
  const visit = async (path, width) => {
    await page.setViewportSize({ width, height: 900 });
    await page.goto(base + path);
    await page.locator('.workspace-content').waitFor();
    await settle();
  };
  const oneRead = async (resource, action, expected) => {
    const before = count(resource);
    const response = page.waitForResponse(response => {
      const url = new URL(response.url());
      return url.origin === base && url.pathname === '/api/admin/' + resource && response.request().method() === 'GET';
    });
    await action();
    const result = await response;
    check(result.ok(), resource + ' query succeeds');
    await settle();
    check(count(resource) === before + 1, resource + ' action sends exactly one list GET');
    const params = new URL(result.url()).searchParams, current = new URL(page.url()).searchParams;
    for (const [key, value] of Object.entries(expected)) {
      check((params.get(key) || '') === value, resource + ' request ' + key + ' is ' + JSON.stringify(value));
      check((current.get(key) || '') === value, resource + ' URL ' + key + ' matches the request');
    }
    return result;
  };
  const resizeWithoutRead = async (resource, width) => {
    const before = count(resource);
    await page.setViewportSize({ width, height: 900 });
    if (width < 768) await page.getByRole('navigation', { name: '快捷导航', exact: true }).waitFor();
    else await page.locator('.workspace-sidebar').waitFor({ state: 'visible' });
    await settle();
    check(count(resource) === before, resource + ' resize does not query the list');
  };
  const wrapper = combo => combo.locator('xpath=ancestor::div[contains(@class,"el-select__wrapper")]');
  const choose = async (combo, label) => {
    await wrapper(combo).click();
    await page.getByRole('option', { name: label, exact: true }).click();
  };
  const selectedLabel = async (combo, label) => {
    check((await wrapper(combo).locator('.el-select__selected-item:not(.el-select__input-wrapper)').innerText()).trim() === label,
      'Sort control displays ' + label);
  };
  const header = label => page.locator('.el-table__header-wrapper th').filter({ hasText: label }).first();
  const arrow = async (label, order) => {
    const cell = header(label); await cell.waitFor();
    check((await cell.getAttribute('class') || '').split(/\s+/).includes(order), label + ' PC arrow is ' + order);
  };
  const more = async (label, action) => {
    await page.getByRole('button', { name: label, exact: true }).click();
    const menu = page.getByRole('dialog', { name: label, exact: true });
    await menu.getByRole('button', { name: action, exact: true }).click();
    await menu.waitFor({ state: 'hidden' });
  };
  const screenshot = async name => {
    await page.evaluate(() => document.fonts.ready);
    const path = 'output/playwright/mobile-sort-' + name + '.png';
    await page.screenshot({ path, fullPage: false, animations: 'disabled' }); screenshots.push(path);
  };
  page.on('request', onRequest); page.on('pageerror', onError);
  await page.route(base + '/api/**', writeGuard);
  try {
    const auth = await page.evaluate(() => fetch('/api/auth/me').then(response => response.json()));
    check(auth.user?.email === 'admin@gingtto.test', 'Existing synthetic admin login is reused');
    check((await read('inventory/1')).product.sku === 'GT-2026-1', 'Synthetic fixture identity is verified');

    await visit('/products?page=1&pageSize=25&sort=price&direction=asc&status=active', 393);
    await more('商品操作', '排序与列表设置');
    const productSort = page.getByRole('combobox', { name: '列表排序', exact: true });
    await selectedLabel(productSort, '价格');
    check((await page.getByRole('button', { name: '切换排序方向', exact: true }).innerText()).includes('升序'), 'Product URL ascending order is reflected on initial load');
    const oldTable = await page.getByTestId('mobile-table').elementHandle();
    const productFilters = page.locator('.responsive-filters').first();
    await productFilters.getByRole('textbox').fill('GT-2026');
    await oneRead('products', () => productFilters.getByRole('button', { name: '查询', exact: true }).click(),
      { keyword: 'GT-2026', sort: 'price', direction: 'asc' });
    check(await oldTable.evaluate(element => !element.isConnected), 'Product filterKey actually rebuilt the table');
    await selectedLabel(productSort, '价格');
    check((await page.getByRole('button', { name: '切换排序方向', exact: true }).innerText()).includes('升序'), 'Product ascending direction survives table recreation');
    await oneRead('products', () => choose(productSort, '默认排序'), { keyword: 'GT-2026', sort: 'category', direction: '' });
    await selectedLabel(productSort, '排序');
    check(await page.getByRole('button', { name: '切换排序方向', exact: true }).count() === 0, 'Default category grouping clears the old price direction');
    await screenshot('products');

    await visit('/orders?page=1&pageSize=25&status=all&sort=createdAt&direction=desc', 1440);
    await oneRead('orders', () => header('下单时间').locator('.sort-caret.ascending').click(), { sort: 'createdAt', direction: 'asc' });
    await arrow('下单时间', 'ascending');
    await resizeWithoutRead('orders', 393);
    await oneRead('orders', () => more('订单操作', '按应付金额降序'), { sort: 'totalAmount', direction: 'desc' });
    await resizeWithoutRead('orders', 1440);
    await arrow('应付总额', 'descending'); await screenshot('orders-pc');

    await visit('/inventory?page=1&pageSize=25&sort=stock&direction=desc', 1440);
    await oneRead('inventory', () => header('现货余额').locator('.sort-caret.ascending').click(), { sort: 'stock', direction: 'asc' });
    await arrow('现货余额', 'ascending');
    await resizeWithoutRead('inventory', 393);
    await oneRead('inventory', () => more('库存操作', '现货余额降序'), { sort: 'stock', direction: 'desc' });
    await resizeWithoutRead('inventory', 1440);
    await arrow('现货余额', 'descending'); await screenshot('inventory-pc');

    await visit('/admin-users?page=1&pageSize=25&sort=createdAt&direction=desc', 1440);
    await oneRead('admin-users', () => header('姓名').locator('.sort-caret.ascending').click(), { sort: 'name', direction: 'asc' });
    await arrow('姓名', 'ascending');
    await resizeWithoutRead('admin-users', 393);
    const accountFilters = page.locator('.mobile-system-search');
    await accountFilters.getByRole('button', { name: '更多筛选', exact: true }).click();
    const accountSort = accountFilters.getByRole('combobox', { name: '账号排序', exact: true });
    await selectedLabel(accountSort, '姓名 · 升序');
    const accountKeyword = accountFilters.locator(':scope > .el-input input');
    const marker = 'mobile-sort-draft-' + Date.now();
    await accountKeyword.fill(marker);
    await choose(accountFilters.getByRole('combobox', { name: '账号状态', exact: true }), '停用');
    await oneRead('admin-users', () => choose(accountSort, '创建时间 · 最早优先'),
      { sort: 'createdAt', direction: 'asc', keyword: '', status: '' });
    check(await accountKeyword.inputValue() === marker, 'Account sort preserves the unsubmitted keyword');
    await selectedLabel(accountFilters.getByRole('combobox', { name: '账号状态', exact: true }), '停用');
    await oneRead('admin-users', () => accountFilters.getByRole('button', { name: '查询', exact: true }).click(),
      { sort: 'createdAt', direction: 'asc', keyword: marker, status: 'disabled' });
    await selectedLabel(accountSort, '创建时间 · 最早优先'); await screenshot('accounts');
    await resizeWithoutRead('admin-users', 1440); await arrow('创建时间', 'ascending');

    await visit('/categories?page=1&pageSize=25&keyword=', 393);
    const originalCategories = (await read('categories')).items;
    check(originalCategories.length >= 2, 'Existing fixture has categories to reorder without creating records');
    await more('分类操作', '排序与列表设置');
    const categorySort = page.getByRole('combobox', { name: '列表排序', exact: true });
    await choose(categorySort, '分类编码');
    await selectedLabel(categorySort, '分类编码');
    check((await page.getByRole('button', { name: '切换排序方向', exact: true }).innerText()).includes('降序'), 'Category code descending is selected before reordering');
    const target = originalCategories[1];
    const card = page.locator('.goods-card').filter({ has: page.locator('.goods-card-copy > strong', { hasText: target.labels.zh }) });
    await card.getByRole('button', { name: '更多', exact: true }).click();
    const reordered = page.waitForResponse(response => response.url() === base + '/api/admin/categories/order' && response.request().method() === 'PUT');
    await page.getByRole('dialog', { name: '更多操作', exact: true }).getByRole('button', { name: '上移一位', exact: true }).click();
    check((await reordered).ok(), 'Real fixture category reorder PUT succeeds');
    await settle(); await selectedLabel(categorySort, '排序');
    check((await page.getByRole('button', { name: '切换排序方向', exact: true }).innerText()).includes('升序'), 'Category control returns to ascending sortOrder after reorder');
    const expectedIds = originalCategories.map(item => item.id); [expectedIds[0], expectedIds[1]] = [expectedIds[1], expectedIds[0]];
    check(JSON.stringify((await read('categories')).items.map(item => item.id)) === JSON.stringify(expectedIds), 'Category data uses the newly saved global order');
    check(categoryWrites.length === 1 && JSON.stringify(categoryWrites[0].categoryIds) === JSON.stringify(expectedIds), 'Exactly one allowed category-order write contains the intended swap');
    await screenshot('categories');
    check(!errors.length, 'No page JavaScript errors' + (errors.length ? ': ' + errors.join('; ') : ''));
    check(!deniedWrites.length, 'No unexpected business writes');
    return { passed: true, fixtureOnly: true, checkCount: checks.length, checks, screenshots, categoryWrites: categoryWrites.length, unexpectedWrites: deniedWrites, errors };
  } finally {
    await page.unroute(base + '/api/**', writeGuard);
    page.off('request', onRequest); page.off('pageerror', onError);
  }
}
