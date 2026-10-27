async (page) => {
  const base='http://127.0.0.1:5380';
  if(!page.url().startsWith(base+'/')) throw new Error('Isolated fixture required');
  await page.setViewportSize({width:393,height:852});
  for(const [name,path] of [
    ['dashboard','/dashboard'],['orders','/orders?keyword=GT20260918'],
    ['inventory','/inventory?keyword=GT-2026'],['finance','/finance'],
  ]) {
    await page.goto(base+path);await page.waitForLoadState('networkidle');
    await page.evaluate(()=>document.fonts.ready);await page.evaluate(()=>scrollTo(0,0));
    await page.screenshot({path:'output/playwright/mobile-real-'+name+'-final.png',fullPage:false,animations:'disabled'});
  }
  await page.getByRole('button',{name:'商品成本',exact:true}).click();
  await page.locator('.mf-cost-search input').fill('GT-2026');
  await page.locator('.mf-cost-search').getByRole('button',{name:'查询',exact:true}).click();
  await page.waitForLoadState('networkidle');
  await page.screenshot({path:'output/playwright/mobile-real-costs-final.png',fullPage:false,animations:'disabled'});
  return {passed:true,viewport:'393x852',screens:['dashboard','orders','inventory','finance','costs'],fixtureOnly:true};
}
