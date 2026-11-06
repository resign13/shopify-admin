async page => {
  if (!page.url().startsWith('http://127.0.0.1:5395/')) throw new Error('Isolated fixture required');
  const check = (value, message) => { if (!value) throw new Error(message); };
  await page.setViewportSize({width:1440,height:1000});
  await page.goto('http://127.0.0.1:5395/dashboard?dateFrom=2026-09-18&dateTo=2026-09-18');
  const choose = async (label, values) => {
    await page.getByRole('combobox',{name:label,exact:true}).press('Enter');
    for (const name of values) await page.getByRole('option',{name,exact:true}).click();
    await page.keyboard.press('Escape');
  };
  await choose('款号筛选',['GT-2026','EXTRA-00']);
  await choose('订单状态筛选',['已付款','待付款']);
  const overview = page.waitForResponse(r=>r.url().includes('view=workbench') && r.url().includes('statuses='));
  await page.locator('.responsive-filters').first().getByRole('button',{name:'查询',exact:true}).click();
  const result = await (await overview).json();
  check(result.metrics.orders===2 && result.metrics.units===6,'Multi-filter query results');
  await page.waitForURL(url=>url.searchParams.get('statuses')==='paid,pending_payment');
  await page.reload();
  await page.locator('.filter-scope').getByText(/已付款、待付款/).waitFor();
  check(new URL(page.url()).searchParams.get('style')==='EXTRA-00,GT-2026','Styles persisted');
  const request = page.waitForRequest(r=>r.url().includes('/style-performance/export?'));
  const downloaded = page.waitForEvent('download');
  await page.getByRole('button',{name:'导出 Excel',exact:true}).click();
  const query = new URL((await request).url()).searchParams;
  check(query.get('statuses')==='paid,pending_payment' && query.get('style')==='EXTRA-00,GT-2026','Export parity');
  await (await downloaded).saveAs('D:/dulizhan/output/dashboard-multifilter.xlsx');
  await page.screenshot({path:'D:/dulizhan/output/dashboard-multifilter-desktop.png'});
  await page.setViewportSize({width:390,height:844});
  await page.getByRole('button',{name:'经营筛选',exact:true}).click();
  await page.getByRole('combobox',{name:'订单状态筛选',exact:true}).press('Enter');
  await page.getByRole('option',{name:'已付款',exact:true}).click();
  await page.keyboard.press('Escape');
  const mobile = page.waitForResponse(r=>r.url().includes('view=workbench') && new URL(r.url()).searchParams.get('statuses')==='pending_payment');
  await page.locator('#mobile-dashboard-filters').getByRole('button',{name:'查询',exact:true}).click();
  check((await (await mobile).json()).metrics.orders===1,'Mobile multi-select deselection');
  await page.screenshot({path:'D:/dulizhan/output/dashboard-multifilter-mobile.png'});
  return {multiFilters:true, reload:true, exportParity:true, mobile:true};
}
