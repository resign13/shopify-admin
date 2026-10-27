// This fixture guard is intentional: automated navigation and form checks never
// use the synchronized manual database or a production site.
async (page) => {
  const base='http://127.0.0.1:5360';
  if(!page.url().startsWith(base+'/')) throw new Error('Local *_test fixture required');
  const check=(value,message)=>{if(!value)throw new Error(message);};
  const errors=[];page.on('pageerror',error=>errors.push(error.message));
  page.on('console',message=>{if(message.type()==='error' && /TypeError|ReferenceError|\[ElTable\]|Unhandled/.test(message.text()))errors.push(message.text());});
  page.on('dialog',dialog=>dialog.accept());
  const routes=['/dashboard','/orders','/products','/inventory','/finance','/contracts','/presale','/categories','/store-accounts','/admin-users','/audit-logs','/api-integrations','/size-charts','/products/1/edit'];
  const results=[];
  for(const width of [360,390,430,768,1024,1440,1920]) {
    await page.setViewportSize({width,height:900});
    for(const route of routes) {
      await page.goto(base+route);await page.waitForLoadState('networkidle');
      const measurement=await page.evaluate(()=>({width:innerWidth,scroll:document.documentElement.scrollWidth,
        left:document.querySelector('.workspace-main')?.getBoundingClientRect().left,
        cards:document.querySelectorAll('.mobile-record').length}));
      results.push({width,route,...measurement});
      check(measurement.scroll<=width+1,`Horizontal overflow ${route} at ${width}: ${measurement.scroll}`);
      if(width<1024)check(measurement.left===0,`Sidebar consumes compact width: ${route}`);
      if(width===390 && ['/orders','/inventory','/finance'].includes(route))await page.screenshot({path:`output/playwright/admin-mobile-${route.slice(1)}.png`,fullPage:true});
      if(width===1440 && route==='/orders')await page.screenshot({path:'output/playwright/admin-mobile-orders-desktop.png',fullPage:true});
      if(width===768 && route==='/inventory')await page.screenshot({path:'output/playwright/admin-mobile-inventory-tablet.png',fullPage:true});
    }
  }
  check(!errors.length,'Uncaught browser errors: '+errors.join('; '));
  return {layout:true,routeChecks:results,uncaughtErrors:errors};
}
