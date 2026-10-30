async (page) => {
  if (!page.url().startsWith('http://127.0.0.1:5395/')) throw new Error('Isolated export fixture required');
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto('http://127.0.0.1:5395/dashboard?dateFrom=2026-09-18&dateTo=2026-09-18&stylePage=2&stylePageSize=10&styleSort=units&styleDirection=asc');
  const panel = page.locator('.style-performance-panel');
  const button = panel.getByRole('button', { name: '导出 Excel', exact: true });
  const keyword = panel.getByRole('textbox', { name: '搜索款号、颜色 SKU 或商品名称' });
  const check = (value, message) => { if (!value) throw new Error(message); };
  const output = 'D:/dulizhan/output/';
  await button.waitFor();
  await panel.getByText('显示第 11–13 条，共 13 个款号').waitFor();
  await keyword.fill('not-applied');
  const firstRequest = page.waitForRequest(request => request.url().includes('/dashboard/style-performance/export?'));
  const firstDownload = page.waitForEvent('download');
  await button.click();
  const firstQuery = new URL((await firstRequest).url()).searchParams;
  check(!firstQuery.has('page') && !firstQuery.has('pageSize'), 'Export must not contain pagination');
  check(!firstQuery.has('keyword'), 'Unapplied keyword leaked into export');
  check(firstQuery.get('dateFrom') === '2026-09-18' && firstQuery.get('direction') === 'asc', 'Applied dates/sort lost');
  await (await firstDownload).saveAs(output + 'dashboard-style-export-all.xlsx');

  await keyword.fill('EXTRA');
  const filtered = page.waitForResponse(response => response.url().includes('view=style-performance') && response.url().includes('keyword=EXTRA'));
  await panel.getByRole('button', { name: '查询', exact: true }).click();
  check((await (await filtered).json()).total === 12, 'Filter should find all 12 extra styles');
  await panel.getByRole('listitem', { name: '第 2 页' }).click();
  await panel.getByText('显示第 11–12 条，共 12 个款号').waitFor();
  const filteredRequest = page.waitForRequest(request => request.url().includes('/dashboard/style-performance/export?'));
  const filteredDownload = page.waitForEvent('download');
  await button.click();
  check(new URL((await filteredRequest).url()).searchParams.get('keyword') === 'EXTRA', 'Applied filter missing');
  await (await filteredDownload).saveAs(output + 'dashboard-style-export-filtered.xlsx');
  await panel.screenshot({ path: output + 'dashboard-style-export-desktop.png' });

  const exportUrl = '**/api/admin/dashboard/style-performance/export?**';
  let calls = 0;
  let release;
  const gate = new Promise(resolve => { release = resolve; });
  await page.route(exportUrl, async route => {
    calls++;
    await gate;
    await route.fulfill({ status: 429, contentType: 'application/json', headers: { 'Retry-After': '5' },
      body: JSON.stringify({ code: 'export_capacity', message: '导出服务繁忙，请稍后重试。' }) });
  });
  const pending = page.waitForRequest(request => request.url().includes('/dashboard/style-performance/export?'));
  await button.click();
  await pending;
  check(await button.isDisabled(), 'Export button must reject repeat clicks while running');
  release();
  await page.getByText('导出服务繁忙，请稍后重试。', { exact: true }).waitFor();
  check(!await button.isDisabled(), 'Export button must recover after failure');
  check(await keyword.inputValue() === 'EXTRA' && calls === 1, 'Failure changed filters or retried unexpectedly');
  await page.unroute(exportUrl);
  await page.getByText('导出服务繁忙，请稍后重试。', { exact: true }).waitFor({ state: 'hidden' });

  for (const width of [360, 390, 430]) {
    await page.setViewportSize({ width, height: 844 });
    await button.scrollIntoViewIfNeeded();
    check(await button.isVisible(), 'Export unavailable on phone');
    check(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), 'Page overflows on phone');
  }
  await page.setViewportSize({ width: 390, height: 844 });
  await panel.getByRole('heading', { name: '款号商品表现' }).scrollIntoViewIfNeeded();
  await page.screenshot({ path: output + 'dashboard-style-export-mobile.png' });
  const mobileDownload = page.waitForEvent('download');
  await button.click();
  await (await mobileDownload).saveAs(output + 'dashboard-style-export-mobile.xlsx');
  return { appliedFiltersOnly: true, allPages: true, duplicateBlocked: true,
    failureRecovery: true, desktopDownload: true, mobileDownload: true, mobileWidths: [360, 390, 430] };
}
