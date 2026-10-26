async (page) => {
  const base = 'http://127.0.0.1:5380';
  if (!page.url().startsWith(base + '/')) throw new Error('Isolated mobile fixture required');
  const check = (value, message) => { if (!value) throw new Error(message); };
  const visit = async path => { await page.goto(base + path); await page.waitForLoadState('networkidle'); };
  const settleViewport = async () => page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
  const calendarWidths = [];
  for (const width of [360, 393, 430]) {
    await page.setViewportSize({ width, height: 852 });
    await visit('/orders');
    await page.getByRole('button', { name: '更多筛选', exact: true }).click();
    await page.getByPlaceholder('开始日期', { exact: true }).click();
    const calendar = page.locator('.el-date-range-picker:visible');
    await calendar.waitFor();
    await calendar.evaluate(el => Promise.all((el.closest('.el-popper') || el).getAnimations({ subtree: true }).map(a => a.finished.catch(() => {}))));
    const layout = await calendar.evaluate(el => {
      const rect = el.getBoundingClientRect();
      const body = el.querySelector('.el-picker-panel__body').getBoundingClientRect();
      const panels = [...el.querySelectorAll('.el-date-range-picker__content')].map(p => {
        const r = p.getBoundingClientRect();
        return { left: r.left, right: r.right, top: r.top, bottom: r.bottom };
      });
      const cell = el.querySelector('td.available').getBoundingClientRect();
      return { width: innerWidth, left: rect.left, right: rect.right, bodyWidth: body.width,
        panelWidth: rect.width, panels, cellHeight: cell.height, cellWidth: cell.width };
    });
    check(layout.left >= 0 && layout.right <= width + 1, 'Date popup exceeds viewport');
    check(layout.bodyWidth <= layout.panelWidth + 1, 'Date picker retains desktop minimum width');
    check(layout.panels[1].top >= layout.panels[0].bottom - 1, 'Date calendars are not stacked');
    check(layout.cellHeight >= 43.9 && layout.cellWidth >= 43.9, 'Calendar touch target is too small');
    if (width === 393) await page.screenshot({ path: 'output/playwright/iphone16-date-range.png', animations: 'disabled' });
    const month = calendar.locator('.el-date-range-picker__content.is-left');
    const dates = month.locator('td.available:not(.prev-month):not(.next-month)');
    await dates.filter({ hasText: /^10$/ }).click();
    const endMonth = width === 393 ? calendar.locator('.el-date-range-picker__content.is-right') : month;
    await endMonth.locator('td.available:not(.prev-month):not(.next-month)').filter({ hasText: /^12$/ }).click();
    await calendar.waitFor({ state: 'hidden' });
    check((await page.getByPlaceholder('开始日期', { exact: true }).inputValue()).endsWith('-10'), 'Start date not retained');
    check((await page.getByPlaceholder('结束日期', { exact: true }).inputValue()).endsWith('-12'), 'End date not retained');
    calendarWidths.push(width);
  }
  await page.setViewportSize({ width: 393, height: 852 });
  await visit('/finance');
  await page.getByText('汇率与导入导出', { exact: false }).click();
  const rate = page.getByRole('spinbutton', { name: '核算汇率', exact: true });
  await rate.fill('7.123456'); await rate.press('Tab');
  await page.setViewportSize({ width: 1440, height: 1000 });
  await settleViewport();
  check(await rate.isVisible(), 'Finance tools hidden after desktop resize');
  check(await rate.inputValue() === '7.123456', 'Resize discarded finance input');
  await page.setViewportSize({ width: 393, height: 852 });
  await settleViewport();
  if (!(await rate.isVisible())) await page.getByText('汇率与导入导出', { exact: false }).click();
  await rate.waitFor({ state: 'visible' });
  check(await rate.inputValue() === '7.123456', 'Phone resize discarded finance input');
  await visit('/orders');
  await page.setViewportSize({ width: 852, height: 393 });
  await page.getByRole('button', { name: '＋ 新增订单', exact: true }).click();
  const editor = page.getByRole('dialog', { name: '新增订单', exact: true });
  await page.waitForFunction(() => [...document.querySelectorAll('.el-drawer.open')].some(el => {
    const r = el.getBoundingClientRect();
    return el.querySelector('.el-drawer__title')?.textContent === '新增订单' && r.left >= -1 && r.right <= innerWidth + 1;
  }));
  const save = editor.getByRole('button', { name: '创建待付款订单', exact: true });
  check(await save.evaluate(el => { const r = el.getBoundingClientRect(); return r.top >= 0 && r.bottom <= innerHeight + 1; }), 'Landscape hides order save action');
  await editor.getByRole('button', { name: '取消', exact: true }).click();
  return { mobileDateRanges: calendarWidths, fullCalendars: true, crossMonthSelection: true, touchTargets: true,
    financeResizeRetainsInput: true, landscapeOrderFooter: true, businessWrites: 0 };
}
