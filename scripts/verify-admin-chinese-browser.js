// Isolated fixture only: no real exports or business writes.
async (page) => {
  const base = new URL(page.url()).origin;
  if (!['http://127.0.0.1:5380', 'http://127.0.0.1:5386'].includes(base))
    throw new Error('Explicit isolated admin *_test browser fixture required');
  const check = (value, message) => { if (!value) throw new Error(message); };
  const orderQuery = /\/api\/admin\/orders\?/;
  const exportRoute = /\/api\/admin\/orders\/(?:export|export-by-sheet)(?:\?|$)/;
  const query = () => page.getByRole('button', { name: '查询', exact: true });
  const search = () => page.getByRole('textbox', { name: '订单查询关键词', exact: true });
  const alert = text => page.getByRole('alert').filter({ hasText: text }).last();
  const results = [];
  const pageErrors = [];
  const onError = error => pageErrors.push(error.message);
  page.on('pageerror', onError);
  try {
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto(base + '/orders?page=1&pageSize=25');
    await page.getByRole('button', { name: '导出订单 ▾', exact: true }).waitFor();
    await page.getByRole('button', { name: '订单详情', exact: true }).first().waitFor();
    const realValidation = await page.evaluate(async () => {
      const response = await fetch('/api/admin/orders?keyword=' + 'a'.repeat(201));
      const body = await response.json();
      return { status: response.status, code: body.code, message: body.message };
    });
    check(realValidation.status === 400 && realValidation.code === 'query_too_long'
      && /[\u3400-\u9fff]/u.test(realValidation.message) && realValidation.message.includes('200'), 'Real backend validation lost its Chinese reason or code');

    for (const fixture of [
      { status: 403, body: { message: 'Forbidden' }, expected: '没有执行此操作的权限' },
      { status: 409, body: { message: 'Conflict' }, expected: '数据已更新' },
      { status: 429, body: { code: 'rate_limited', message: 'Too many requests. Try again later.' }, expected: '请求过于频繁' },
      { status: 502, html: '<html>Bad Gateway</html>', expected: '服务暂时不可用' },
    ]) {
      await page.route(orderQuery, route => route.fulfill({ status: fixture.status,
        headers: { 'Retry-After': '3' }, contentType: fixture.html ? 'text/html' : 'application/json',
        body: fixture.html || JSON.stringify(fixture.body) }));
      const keyword = '保留当前查询' + fixture.status;
      await search().fill(keyword);
      await query().click();
      await alert(fixture.expected).waitFor();
      check(await search().inputValue() === keyword, 'Failed query discarded input');
      results.push(fixture.status);
      await page.unroute(orderQuery);
    }
    await search().fill(''); await query().click();
    await page.getByRole('button', { name: '订单详情', exact: true }).first().waitFor();
    await page.route(exportRoute, route => route.fulfill({ status: 504,
      contentType: 'application/json', body: JSON.stringify({ code: 'export_timeout', message: 'Export task timed out' }) }));
    await page.getByRole('button', { name: '导出订单 ▾', exact: true }).click();
    await page.getByRole('menuitem', { name: /合并表格/ }).click();
    await alert('导出生成超时').waitFor();
    await page.waitForFunction(() => [...document.querySelectorAll('[role="alert"]')]
      .some(el => el.textContent.includes('导出生成超时') && Number(getComputedStyle(el).opacity) > .95));
    await page.screenshot({ path: 'output/playwright/admin-chinese-desktop-export.png', fullPage: false });
    await page.unroute(exportRoute);

    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto(base + '/orders?page=1&pageSize=25');
    await page.locator('.m-order-card').first().waitFor();
    const count = await page.locator('.m-order-card').count();
    await page.route(orderQuery, route => route.abort('failed'));
    await search().fill('网络异常保留输入');
    await query().click();
    await alert('连接失败').waitFor();
    check(await search().inputValue() === '网络异常保留输入', 'Mobile network failure discarded input');
    check(await page.locator('.m-order-card').count() === count, 'Mobile network failure discarded rows');
    await page.screenshot({ path: 'output/playwright/admin-chinese-mobile-network.png', fullPage: false });
    await page.unroute(orderQuery);
    await search().fill(''); await query().click();
    check(pageErrors.length === 0, 'Browser page error: ' + pageErrors.join('; '));
    return { passed: true, realBackendChineseValidation: true, statuses: results,
      desktopExportTimeoutChinese: true, mobileNetworkChinese: true,
      inputAndRowsRetained: true, businessWrites: false, fixtureOnly: true };
  } finally {
    await page.unroute(orderQuery);
    await page.unroute(exportRoute);
    page.off('pageerror', onError);
  }
}
