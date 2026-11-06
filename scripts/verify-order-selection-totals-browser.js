// The fixture guard and login keep this regression on an isolated local *_test DB.
async page => {
  const base = 'http://127.0.0.1:5421';
  if (!page.url().startsWith(base + '/')) throw new Error('Isolated fixture required');
  const check = (value, message) => { if (!value) throw new Error(message); };
  const login = async role => {
    await page.goto(base + '/login');
    await page.getByRole('textbox',{name:'账号 / 邮箱'}).fill(`${role}@gingtto.test`);
    await page.getByRole('textbox',{name:'密码',exact:true}).fill('Workbench-Test-2026');
    await page.getByRole('button',{name:'登录工作台',exact:true}).click();
    await page.waitForURL(url => url.pathname !== '/login');
    await page.goto(base + '/orders?page=1&pageSize=25');
    await page.getByText('SUMMARY-028',{exact:true}).waitFor();
  };
  const pick = async code => {
    const row = page.getByRole('row').filter({hasText:code});
    await row.locator('.el-checkbox__inner').click();
  };
  const summary = page.getByTestId('order-selection-totals');
  const text = async id => (await page.getByTestId(id).innerText()).replace(/\s+/g, ' ');
  await page.setViewportSize({width:1920,height:1000});
  await login('admin');
  await pick('SUMMARY-028');
  check((await text('selection-goods-total')).includes('CNY ¥100.20'), 'Selected CNY goods');
  check((await text('selection-payable-total')).includes('CNY ¥105.20'), 'Selected CNY payable');
  await pick('SUMMARY-027');
  check((await text('selection-goods-total')).includes('$0.10'), 'USD separately');
  check((await text('selection-payable-total')).includes('$0.30'), 'USD payable includes shipping');
  await page.getByRole('listitem',{name:'第 2 页'}).click();
  await page.getByText('SUMMARY-001',{exact:true}).waitFor();
  await pick('SUMMARY-001');
  check(await page.getByRole('row').filter({hasText:'SUMMARY-001'}).locator('.el-checkbox__input').evaluate(el=>el.classList.contains('is-checked')), 'Visible row reflects its selection');
  check((await text('selection-goods-total')).includes('$0.20'), 'Cross-page goods');
  check((await text('selection-payable-total')).includes('$0.60'), 'Cross-page payable');
  check((await summary.innerText()).includes('CNY ¥100.20'), 'Cross-page retains CNY');
  await pick('SUMMARY-001');
  check((await text('selection-goods-total')).includes('$0.10'), 'Deselection updates goods');
  check((await text('selection-payable-total')).includes('$0.30'), 'Deselection updates payable');
  await pick('SUMMARY-001');
  await page.screenshot({path:'output/playwright/order-selection-totals-desktop.png'});
  await page.getByRole('button',{name:'清空选择',exact:true}).click();
  check(await summary.count()===0, 'Clear removes summary');
  await page.getByRole('listitem',{name:'第 1 页'}).click();
  await page.getByText('SUMMARY-028',{exact:true}).waitFor();
  await page.locator('.el-table__header-wrapper thead .el-checkbox__inner').click();
  check((await text('selection-goods-total')).includes('$2.40'), 'Select page goods');
  check((await text('selection-payable-total')).includes('$7.20'), 'Select page payable');
  await page.getByRole('textbox',{name:'订单查询关键词'}).fill('SUMMARY-001');
  await page.locator('main form.filters').getByRole('button',{name:'查询',exact:true}).click();
  await page.getByText('SUMMARY-001',{exact:true}).waitFor();
  check(await summary.count()===0, 'Filtering clears selection');
  await page.locator('.profile-button').click();
  await page.getByRole('menuitem',{name:'退出登录',exact:true}).click();
  await login('warehouse');
  await pick('SUMMARY-028');
  check(await summary.count()===0, 'Warehouse cannot see financial totals');
  return {selectionTotals:true, mixedCurrency:true, crossPage:true, clearAndFilter:true, warehouseHidden:true};
}
