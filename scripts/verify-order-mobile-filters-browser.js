// Read-only UI check on the already authenticated, dedicated *_test fixture.
// No login, seed, order/inventory mutation, or new browser/context is performed.
async (page) => {
  const base = 'http://127.0.0.1:5380';
  if (!page.url().startsWith(base + '/'))
    throw new Error('Explicit loopback 5380 *_test fixture required');
  const checks = [], errors = [], writes = [], screenshots = [];
  const check = (value, message) => { if (!value) throw new Error(message); checks.push(message); };
  const onError = error => errors.push(error.message);
  const onRequest = request => {
    const url = new URL(request.url());
    if (url.origin === base && url.pathname.startsWith('/api/') && !['GET', 'HEAD', 'OPTIONS'].includes(request.method()))
      writes.push(request.method() + ' ' + url.pathname);
  };
  const listPattern = '**/api/admin/orders?**';
  const largeCounts = { pending_payment: 1234567, allocated: 7654321, paid: 9999999 };
  const largeCountRoute = async route => {
    const request = route.request();
    if (request.method() !== 'GET' || new URL(request.url()).pathname !== '/api/admin/orders')
      return route.fallback();
    const response = await route.fetch();
    if (!response.ok()) return route.fulfill({ response });
    const data = await response.json();
    await route.fulfill({ response, json: { ...data, statusCounts: { ...data.statusCounts, ...largeCounts } } });
  };
  const filters = () => page.locator('.order-responsive-filters');
  const keyword = () => filters().getByRole('textbox', { name: '订单查询关键词', exact: true });
  const queryButton = () => filters().getByRole('button', { name: '查询', exact: true });
  const filterButton = () => filters().locator('.mobile-filter-toggle');
  const chip = key => filters().locator('.mobile-filter-chips .el-tag').filter({ hasText: key });
  const requestAfter = predicate => page.waitForResponse(response => {
    const request = response.request(), url = new URL(response.url());
    return url.origin === base && url.pathname === '/api/admin/orders' && request.method() === 'GET' && predicate(url.searchParams);
  });
  const rect = locator => locator.evaluate(element => {
    const box = element.getBoundingClientRect();
    return { x: box.x, y: box.y, width: box.width, height: box.height };
  });
  const currentStatus = () => page.locator('.m-order-status-select');
  const assertStatusDropdown = async width => {
    const trigger = currentStatus().locator('.el-select__wrapper');
    const triggerBox = await rect(trigger);
    const selectedSize = await currentStatus().locator('.el-select__selected-item').first()
      .evaluate(element => parseFloat(getComputedStyle(element).fontSize));
    check(selectedSize === 12, `${width}: selected status text is 12px despite global phone input CSS`);
    await trigger.click();
    const popper = page.locator('.m-order-status-popper.el-popper:visible');
    await popper.getByRole('option', { name: '全部状态', exact: true }).waitFor();
    await page.waitForFunction(() => {
      const element = document.querySelector('.m-order-status-popper.el-popper:not([style*="display: none"])');
      return element && element.getAttribute('data-popper-placement')?.startsWith('bottom');
    });
    const popupBox = await rect(popper);
    check(popupBox.y >= triggerBox.y + triggerBox.height - 1, `${width}: status menu opens below its trigger`);
    check(popupBox.x >= -1 && popupBox.x + popupBox.width <= width + 1, `${width}: status dropdown stays inside viewport`);
    check(await popper.getByRole('option').count() === 8, `${width}: all state options, including partial allocation, remain available`);
    check(await popper.getByRole('option').evaluateAll(elements => elements.every(element =>
      parseFloat(getComputedStyle(element).fontSize) === 13 && Number(getComputedStyle(element).fontWeight) <= 600)),
    `${width}: dropdown options are readable 13px, not oversized/bold`);
    await page.keyboard.press('Escape');
    await popper.waitFor({ state: 'hidden' });
  };
  page.on('pageerror', onError);
  page.on('request', onRequest);
  await page.route(listPattern, largeCountRoute);
  try {
    check(await page.evaluate(() => fetch('/api/auth/me').then(response => response.status)) === 200, 'existing fixture authentication is reused');
    for (const width of [360, 393, 430]) {
      await page.setViewportSize({ width, height: 852 });
      await page.goto(base + '/orders?' + new URLSearchParams({
        page: '1', pageSize: '25', status: 'paid', category: 'denim',
        keyword: 'applied-filter-keyword', dateFrom: '2026-10-01', dateTo: '2026-10-28',
      }));
      const strip = page.locator('.m-order-tab-list');
      await page.waitForFunction(() => document.querySelector('.m-order-tab-list button.active small')?.textContent === '9999999');
      check(await strip.getByRole('button').count() === 4, `${width}: a non-quick status produces the fourth tab`);
      check(JSON.stringify(await strip.locator('small').allTextContents()) === JSON.stringify(['1234567', '7654321', '9999999']),
        `${width}: large counts remain complete, not truncated or abbreviated`);
      check(await strip.evaluate(element => element.scrollWidth > element.clientWidth && getComputedStyle(element).overflowX === 'auto'),
        `${width}: large tabs scroll internally`);
      check(await strip.locator('button.active').evaluate(element => {
        const parent = element.parentElement;
        return element.offsetLeft >= parent.scrollLeft - 1 && element.offsetLeft + element.offsetWidth <= parent.scrollLeft + parent.clientWidth + 1;
      }), `${width}: active fourth tab is revealed horizontally`);
      const stripBox = await rect(strip), statusBox = await rect(currentStatus());
      check(stripBox.x >= -1 && stripBox.x + stripBox.width <= statusBox.x + 1 && statusBox.x + statusBox.width <= width + 1,
        `${width}: fixed status selector and scroll strip do not overlap/overflow`);
      check(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), `${width}: page has no horizontal overflow`);
      await assertStatusDropdown(width);

      const beforeQuery = await rect(queryButton()), beforeFilter = await rect(filterButton());
      await filterButton().click();
      await filters().locator('.el-date-editor').waitFor({ state: 'visible' });
      const afterQuery = await rect(queryButton()), afterFilter = await rect(filterButton());
      check(Math.abs(beforeQuery.x - afterQuery.x) <= 1 && Math.abs(beforeQuery.y - afterQuery.y) <= 1,
        `${width}: query button keeps its original search-row position when expanded`);
      check(Math.abs(beforeFilter.x - afterFilter.x) <= 1 && Math.abs(beforeFilter.y - afterFilter.y) <= 1,
        `${width}: filter toggle keeps its original search-row position when expanded`);
      check((await rect(filters().locator('.el-date-editor'))).y >= afterQuery.y + afterQuery.height - 1,
        `${width}: advanced fields are below the stable search row`);

      // Use actual fixture category options; only subsequent list GET responses
      // have synthetic counts. Input drafts are never sent via POST/PUT.
      const category = filters().locator(':scope > .el-select').first();
      await category.locator('.el-select__wrapper').click();
      const categoryOption = page.getByRole('option').filter({ hasText: /Outerwear|外套|outerwear/i });
      await categoryOption.waitFor();
      const categoryLabel = (await categoryOption.innerText()).trim();
      await categoryOption.click();
      await keyword().fill('unsubmitted-keyword-' + width);
      const removedCategory = requestAfter(params => !params.get('category') && params.get('keyword') === 'applied-filter-keyword');
      await chip('分类：denim').locator('.el-tag__close').click();
      const categoryResponse = await removedCategory;
      check(categoryResponse.ok(), `${width}: removing an applied category makes a successful GET`);
      const categoryParams = new URL(categoryResponse.url()).searchParams;
      check(!categoryParams.get('category') && categoryParams.get('keyword') === 'applied-filter-keyword' && categoryParams.get('status') === 'paid',
        `${width}: category chip removal changes only applied category, not unsubmitted keyword/category`);
      check(await keyword().inputValue() === 'unsubmitted-keyword-' + width, `${width}: keyword draft survives chip removal`);
      check((await category.locator('.el-select__placeholder').innerText()).trim() === categoryLabel,
        `${width}: unsubmitted outerwear category draft survives removal of applied denim`);
      await chip('分类：denim').waitFor({ state: 'hidden' });

      const removedDates = requestAfter(params => !params.get('dateFrom') && !params.get('dateTo') && params.get('keyword') === 'applied-filter-keyword');
      await chip('开始日期：2026-10-01').locator('.el-tag__close').click();
      const dateResponse = await removedDates;
      check(dateResponse.ok(), `${width}: removing a date chip makes a successful GET`);
      check(!new URL(dateResponse.url()).searchParams.get('dateFrom') && !new URL(dateResponse.url()).searchParams.get('dateTo'),
        `${width}: date endpoints are removed as one applied range`);
      check(await keyword().inputValue() === 'unsubmitted-keyword-' + width &&
        (await category.locator('.el-select__placeholder').innerText()).trim() === categoryLabel,
        `${width}: unrelated keyword/category drafts survive paired date removal`);
      await chip('结束日期：2026-10-28').waitFor({ state: 'hidden' });
      const path = `output/playwright/mobile-order-filters-${width}.png`;
      await page.screenshot({ path, fullPage: false, animations: 'disabled' });
      screenshots.push(path);
    }
    check(errors.length === 0, 'no page JavaScript errors');
    check(writes.length === 0, 'no authentication or business write requests');
    return { passed: true, fixtureOnly: true, readOnly: true, checkCount: checks.length, checks, screenshots, errors, writes };
  } finally {
    await page.unroute(listPattern, largeCountRoute);
    page.off('pageerror', onError);
    page.off('request', onRequest);
  }
}
