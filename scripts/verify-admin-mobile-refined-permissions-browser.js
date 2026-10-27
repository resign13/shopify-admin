async (page) => {
  const base='http://127.0.0.1:5380';
  if(!page.url().startsWith(base+'/')) throw new Error('Isolated fixture required');
  const check=(v,m)=>{if(!v) throw new Error(m);};
  const finance=await page.evaluate(async()=>{
    const r=await fetch('/api/admin/admin-users?page=1&pageSize=100&keyword=mobile-finance-');
    if(!r.ok) throw new Error('Admin fixture setup required');
    return (await r.json()).items.find(u=>u.role==='finance');
  });
  check(finance,'Run the isolated finance/system fixture check first');
  const browser=page.context().browser(),results=[];
  for(const account of [
    {role:'sales',email:'sales@gingtto.test',password:'Workbench-Test-2026'},
    {role:'warehouse',email:'warehouse@gingtto.test',password:'Workbench-Test-2026'},
    {role:'finance',email:finance.email,password:'MobileFinance-Test-2026'},
    {role:'customer',email:'customer@gingtto.test',password:'Workbench-Test-2026'},
  ]) {
    const context=await browser.newContext({viewport:{width:393,height:852},isMobile:true,hasTouch:true,
      userAgent:'Mozilla/5.0 (Linux; Android 14; Pixel 7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Mobile Safari/537.36'});
    const p=await context.newPage();
    try {
      await p.goto(base+'/login');
      await p.getByRole('textbox',{name:'账号 / 邮箱'}).fill(account.email);
      await p.getByRole('textbox',{name:'密码',exact:true}).fill(account.password);
      await p.getByRole('button',{name:'登录工作台',exact:true}).click();
      await p.locator('.workspace-content').waitFor();await p.waitForLoadState('networkidle');
      await p.getByRole('navigation',{name:'快捷导航'}).getByRole('button',{name:'全部',exact:true}).click();
      const menu=p.getByRole('dialog',{name:'全部模块',exact:true});await menu.waitFor();
      const mobile=await menu.locator('a').evaluateAll(nodes=>nodes.map(n=>n.getAttribute('href')).sort());
      await menu.getByRole('button',{name:'关闭此对话框',exact:true}).click();await menu.waitFor({state:'hidden'});
      await p.setViewportSize({width:1440,height:1000});
      const desktop=await p.locator('.workspace-sidebar nav a').evaluateAll(nodes=>nodes.map(n=>n.getAttribute('href')).sort());
      check(JSON.stringify(mobile)===JSON.stringify(desktop),account.role+' mobile/desktop modules differ');
      await p.setViewportSize({width:393,height:852});
      if(account.role==='warehouse') {
        await p.goto(base+'/orders');await p.waitForLoadState('networkidle');
        check(await p.locator('.m-order-card').count()>0,'Warehouse orders missing');
        check((await p.locator('.m-order-amount').allTextContents()).every(text=>/^\d+ 件$/.test(text.trim())),'Warehouse mobile exposes order amount');
        check(await p.getByRole('button',{name:'新增订单',exact:true}).count()===0,'Warehouse can create order');
        check(await p.evaluate(async()=> (await fetch('/api/admin/finance/costs')).status)===403,'Warehouse accessed costs');
      }
      if(account.role==='sales') {
        check(!mobile.includes('/admin-users')&&!mobile.includes('/finance'),'Sales gained admin/finance defaults');
        check(await p.evaluate(async()=> (await fetch('/api/admin/admin-users')).status)===403,'Sales accessed admin accounts');
      }
      if(account.role==='finance') {
        check(mobile.includes('/finance')&&mobile.includes('/contracts'),'Finance defaults missing');
        check(!mobile.includes('/orders'),'Finance gained order-edit module');
        await p.goto(base+'/finance');await p.locator('.mobile-finance').waitFor();
      }
      if(account.role==='customer') {
        check(JSON.stringify(mobile)===JSON.stringify(['/inventory']),'Read-only modules expanded');
        await p.getByRole('button',{name:'查看全部库存阶段',exact:true}).click();
        check(await p.locator('.m-stock-extra-summary > span').count()===1,'Read-only summary exposes internal stages');
        await p.getByRole('button',{name:'库存排序',exact:true}).click();
        const sorting=p.getByRole('dialog',{name:'库存排序',exact:true});
        await sorting.getByRole('button',{name:'现货余额升序',exact:true}).waitFor();
        check(await sorting.getByRole('button',{name:'导入库存',exact:true}).count()===0,'Read-only sort exposes writes');
        const sorted=p.waitForResponse(r=>r.url().includes('/api/admin/inventory?')&&r.url().includes('sort=stock'));
        await sorting.getByRole('button',{name:'现货余额升序',exact:true}).click();
        check((await sorted).ok(),'Read-only stock sorting failed');
        await sorting.waitFor({state:'hidden'});
      }
      results.push({role:account.role,modules:mobile,desktopParity:true,androidTouch:true});
    } finally {await context.close();}
  }
  return {passed:true,permissionsPassed:true,roles:results,fixtureOnly:true};
}
