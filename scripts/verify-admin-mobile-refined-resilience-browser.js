async (page) => {
  const base='http://127.0.0.1:5380';
  if(!page.url().startsWith(base+'/')) throw new Error('Isolated fixture required');
  const check=(v,m)=>{if(!v) throw new Error(m);};
  const context=await page.context().browser().newContext({viewport:{width:393,height:852},storageState:await page.context().storageState()});
  const p=await context.newPage();
  try {
    await p.goto(base+'/orders');await p.waitForLoadState('networkidle');
    const before=await p.locator('.m-order-card').count();check(before>0,'Order fixture missing');
    await p.route('**/api/admin/orders?**',route=>route.abort('failed'));
    await p.getByRole('textbox',{name:'订单查询关键词'}).fill('network-error-fixture');
    await p.getByRole('button',{name:'查询',exact:true}).click();
    await p.getByRole('alert').filter({hasText:'连接失败'}).waitFor();
    check(await p.locator('.m-order-card').count()===before,'Network failure discarded existing orders');
    check(await p.getByRole('textbox',{name:'订单查询关键词'}).inputValue()==='network-error-fixture','Network failure discarded input');
    await p.unroute('**/api/admin/orders?**');
    await p.getByRole('textbox',{name:'订单查询关键词'}).fill('');
    await p.getByRole('button',{name:'查询',exact:true}).click();await p.waitForLoadState('networkidle');
    check(await p.locator('.m-order-card').count()===before,'Manual retry did not restore query');
    // Clearing this isolated browser context does not revoke the shared server session.
    await context.clearCookies();
    await p.getByRole('textbox',{name:'订单查询关键词'}).fill('session-expired-fixture');
    await p.getByRole('button',{name:'查询',exact:true}).click();
    await p.waitForURL(u=>u.pathname==='/login');
    check(await p.locator('.mobile-bottom-nav').count()===0,'Expired session retained business navigation');
    return {passed:true,networkRetainsRows:true,networkRetainsInput:true,manualRetry:true,authoritative401ReturnsToLogin:true,fixtureOnly:true};
  } finally {await context.close();}
}
