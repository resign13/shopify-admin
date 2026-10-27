// WebKit/iPhone smoke test. The cookie state belongs only to the 5380 *_test fixture.
async (page) => {
  const base='http://127.0.0.1:5380';
  if(!page.url().startsWith(base+'/')) throw new Error('Isolated fixture required');
  const check=(v,m)=>{if(!v) throw new Error(m);};
  const errors=[]; const onError=e=>errors.push(e.message); page.on('pageerror',onError);
  const routes=['dashboard','orders','inventory','finance','products','size-charts','categories','contracts','presale','store-accounts','admin-users','audit-logs','api-integrations'];
  for(const name of routes) {
    await page.goto(base+'/'+name); await page.locator('.workspace-content').waitFor();
    await page.waitForLoadState('networkidle'); await page.evaluate(()=>document.fonts.ready);
    check(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),'WebKit overflow '+name);
  }
  await page.goto(base+'/orders');
  await page.waitForLoadState('networkidle');
  await page.getByRole('button',{name:'订单操作',exact:true}).click();
  const more=page.getByRole('dialog',{name:'订单操作',exact:true});
  await more.getByRole('button',{name:'我的草稿',exact:true}).waitFor();
  check(await more.locator('.el-drawer__title').evaluate(el=>{const r=el.getBoundingClientRect();return r.width>10&&r.height>10&&getComputedStyle(el).clipPath==='none';}),'Phone drawer title is visually hidden');
  check(await more.evaluate(el=>el.getBoundingClientRect().height<innerHeight),'Bottom sheet is not a sheet');
  await more.getByRole('button',{name:'取消',exact:true}).click(); await more.waitFor({state:'hidden'});
  await page.getByRole('button',{name:'新增订单',exact:true}).click();
  const editor=page.getByRole('dialog',{name:'新增订单',exact:true});
  await editor.getByRole('button',{name:'下一步',exact:true}).waitFor();
  await page.waitForLoadState('networkidle');
  await page.setViewportSize({width:393,height:430});
  check(await editor.getByRole('button',{name:'下一步',exact:true}).evaluate(el=>{const r=el.getBoundingClientRect();return r.top>=0 && r.bottom<=innerHeight;}),'Reduced viewport hides editor footer');
  await editor.getByRole('button',{name:'取消',exact:true}).click(); await editor.waitFor({state:'hidden'});
  await page.setViewportSize({width:393,height:852});
  await page.goto(base+'/inventory');
  await page.waitForLoadState('networkidle');
  await page.locator('.m-stock-sizes button').first().click();
  const registration=page.getByRole('dialog',{name:'登记库存',exact:true});
  await registration.locator('.m-registration-grid .el-input-number').first().waitFor();
  await page.waitForLoadState('networkidle');
  check(await registration.locator('.m-registration-grid .el-input-number').count()===6,'Missing inventory stage');
  await registration.getByRole('button',{name:'取消',exact:true}).click(); await registration.waitFor({state:'hidden'});
  await page.getByRole('navigation',{name:'快捷导航'}).getByRole('button',{name:'全部',exact:true}).click();
  const nav=page.getByRole('dialog',{name:'全部模块',exact:true});
  await nav.getByRole('link',{name:'财务管理',exact:true}).click(); await nav.waitFor({state:'hidden'});
  await page.waitForURL(u=>u.pathname==='/finance');
  await page.waitForLoadState('networkidle');
  check(!errors.length,'WebKit errors: '+errors.join('; ')); page.off('pageerror',onError);
  return {passed:true,browser:'WebKit',device:'iPhone 16',modules:13,phoneSheets:true,reducedViewportFooter:true,allInventoryStages:true,navigation:true,errors};
}
