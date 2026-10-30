// Search presentation and behavior only; run on the independent 5380 *_test fixture.
async (page) => {
  const base='http://127.0.0.1:5380';
  if(!page.url().startsWith(base+'/')) throw new Error('Isolated mobile fixture required');
  const check=(v,m)=>{if(!v) throw new Error(m);};
  const errors=[],measurements=[];
  const onError=e=>errors.push(e.message);page.on('pageerror',onError);
  const settle = async () => page.waitForFunction(() => ![...document.querySelectorAll('.workspace-content .el-loading-mask')].some(el=>el.getBoundingClientRect().height && getComputedStyle(el).visibility!=='hidden'));
  const resources={'/store-accounts':'store-users','/api-integrations':'api-integrations/me','/finance':'finance/options'};
  const visit=async route=>{
    const path=new URL(base+route).pathname, resource=resources[path]||path.slice(1);
    const response=page.waitForResponse(r=>new URL(r.url()).pathname==='/api/admin/'+resource);
    await page.goto(base+route);
    const loaded=await response;check(loaded.ok(),'Initial search data failed: '+path);await loaded.finished();
    await page.locator('.workspace-content').waitFor();await settle();
  };
  const loadTab=async(button,resource)=>{
    const response=page.waitForResponse(r=>new URL(r.url()).pathname==='/api/admin/'+resource);
    await button.click();const loaded=await response;check(loaded.ok(),'Search tab data failed: '+resource);await loaded.finished();await settle();
  };
  const searchRows=[
    ['/orders','.responsive-filters'],['/inventory','.responsive-filters'],
    ['/products','.responsive-filters'],['/size-charts','.responsive-filters'],
    ['/categories','.goods-search'],['/contracts','.goods-search'],
    ['/admin-users','.mobile-system-search'],['/store-accounts','.mobile-system-search'],
    ['/audit-logs','.ma-search'],['/finance','.mf-cost-search'],
    ['/api-integrations','.mapi-account-search'],
  ];
  for(const width of [360,393,430]) {
    await page.setViewportSize({width,height:852});
    for(const [route,selector] of searchRows) {
      await visit(route);
      if(route==='/finance') await loadTab(page.getByRole('button',{name:'商品成本',exact:true}),'finance/costs');
      if(route==='/api-integrations') await loadTab(page.getByRole('tab',{name:'账号管理',exact:true}),'api-integrations/accounts');
      const search=page.locator(selector).first();await search.locator('.el-input__wrapper').first().waitFor();
      await page.evaluate(()=>document.fonts.ready);
      const m=await search.locator('.el-input__wrapper').first().evaluate(el=>({height:el.getBoundingClientRect().height,
        background:getComputedStyle(el).backgroundColor,radius:getComputedStyle(el).borderRadius,
        inputFont:getComputedStyle(el.querySelector('input')).fontSize,
        icon:!!el.querySelector('.el-input__prefix')||getComputedStyle(el,'::before').backgroundImage!=='none',
        overflow:document.documentElement.scrollWidth>innerWidth+1}));
      check(m.height===48&&m.background==='rgb(255, 255, 255)'&&m.radius==='16px','Search style differs: '+route+' '+width+' '+JSON.stringify(m));
      check(m.inputFont==='16px'&&m.icon&&!m.overflow,'Search fit/icon/font: '+route+' '+width);
      measurements.push({width,route,...m});
      if(width===393 && ['/orders','/inventory','/products','/finance'].includes(route)) {
        await page.screenshot({path:'output/playwright/mobile-search-'+route.slice(1)+'.png',animations:'disabled'});
      }
    }
  }
  await page.setViewportSize({width:393,height:852});await visit('/orders?page=1&pageSize=25');
  const beforeCount=await page.locator('.m-order-card').count();
  check(beforeCount>0,'Orders fixture did not load before search');
  const keyword=page.getByRole('textbox',{name:'订单查询关键词'});
  const filtered=page.waitForResponse(r=>r.url().includes('/api/admin/orders?')&&r.url().includes('keyword=GT202609180002'));
  await keyword.fill('GT202609180002');await keyword.press('Enter');check((await filtered).ok(),'Enter search failed');
  await page.waitForFunction(()=>document.querySelectorAll('.m-order-card').length===1);
  await keyword.fill('');
  const cleared=page.waitForResponse(r=>r.url().includes('/api/admin/orders?')&&!r.url().includes('keyword='));
  await page.getByRole('button',{name:'查询',exact:true}).click();check((await cleared).ok(),'Query button failed');
  await page.waitForFunction(expected=>document.querySelectorAll('.m-order-card').length===expected,beforeCount);
  await page.getByRole('button',{name:'更多筛选',exact:true}).click();
  await page.locator('.responsive-filters.is-expanded .el-select').first().waitFor();
  check(await keyword.inputValue()==='','Expanding filters changed keyword');
  await page.getByRole('button',{name:'收起筛选',exact:true}).click();
  await visit('/inventory?page=1&pageSize=25');
  const stock=page.waitForResponse(r=>r.url().includes('/api/admin/inventory?')&&r.url().includes('keyword=GT-2026-1'));
  await page.locator('.responsive-filters input').first().fill('GT-2026-1');
  await page.getByRole('button',{name:'查询',exact:true}).click();check((await stock).ok(),'Inventory query failed');
  await page.waitForFunction(()=>document.querySelectorAll('.m-stock-card').length===1);
  // Only the search presentation changes below 768px.
  await page.setViewportSize({width:1440,height:1000});await visit('/orders');
  await page.screenshot({path:'output/playwright/mobile-search-pc-after.png',animations:'disabled'});
  check(!errors.length,'Browser errors: '+errors.join('; '));page.off('pageerror',onError);
  return {passed:true,layoutChecks:measurements.length,measurements,enterSearch:true,queryButton:true,filtersPreserveInput:true,inventoryQuery:true,errors};
}
