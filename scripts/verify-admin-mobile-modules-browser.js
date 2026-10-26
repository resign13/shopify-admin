// UI writes are restricted to the isolated order-selection browser fixture.
async (page) => {
  const base='http://127.0.0.1:5360';
  if(!page.url().startsWith(base+'/'))throw new Error('Isolated *_test fixture required');
  const check=(v,m)=>{if(!v)throw new Error(m);};
  const photo={name:'mobile-fixture.png',mimeType:'image/png',buffer:Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAGAAAABgCAIAAABt+uBvAAAA10lEQVR4nO3SMRHAIAAEQYguNKEJqVEAZ2C3/e7m59pncPc9NgRqHhQECgIFgYJAQaAgUBAoCBQECgIFgYJAQaAgUBAoCBQECgIFgYJAQaAgUBAoCBQECgIFgYJAQaAgUBAoCBQECgIFgYJAQaAgUBAoCBQECgIFgYJAQaAgUBAoCBQECgIFgYJAQaAgUBAoCBQECgIFgYJAQaAgUBAoCBQECgIFgYJAQaAgUBAoCBQECgIFgYJAQaAgUBAoCBQECgIFgYJAQaAgUBAoCBQECgIFgYJA4+0Hy7QCCmtm5CEAAAAASUVORK5CYII=','base64')};
  const fits=async dialog=>{
    await dialog.evaluate(el=>Promise.all(el.getAnimations({subtree:true}).map(a=>a.finished.catch(()=>{}))));
    check(await dialog.evaluate(el=>{const r=el.getBoundingClientRect();return r.left>=-1&&r.right<=innerWidth+1&&r.bottom<=innerHeight+1;}),'Phone overlay overflow');
  };
  await page.setViewportSize({width:390,height:844});
  await page.goto(base+'/products/1/edit');
  const title=page.getByRole('textbox',{name:/商品标题/});await title.waitFor();
  const oldTitle=await title.inputValue();await title.fill(oldTitle+' · 手机验收');
  // Route back uses the existing dirty guard and retains data when cancelled.
  await page.getByRole('button',{name:'展开导航',exact:true}).click();
  await page.getByRole('link',{name:'订单管理',exact:true}).click();
  const dirty=page.getByRole('dialog',{name:'未保存修改',exact:true});await dirty.waitFor();
  await dirty.getByRole('button',{name:'取消',exact:true}).click();
  check(await title.inputValue()===oldTitle+' · 手机验收','Route cancellation discarded product draft');
  const productSaved=page.waitForResponse(r=>r.url().endsWith('/api/admin/products/save-group')&&r.request().method()==='POST');
  await page.getByRole('button',{name:'保存商品',exact:true}).click();check((await productSaved).ok(),'Phone product save failed');
  await page.waitForURL(u=>u.pathname==='/products');
  await page.goto(base+'/contracts');await page.getByRole('button',{name:'＋ 新建合同',exact:true}).click();
  const contract=page.getByRole('dialog',{name:'新建采购合同',exact:true});await fits(contract);
  await contract.getByRole('textbox',{name:'甲方（必填）',exact:true}).fill('手机验收采购方');
  await contract.getByRole('textbox',{name:'乙方 / 工厂名称（必填）',exact:true}).fill('隔离库工厂');
  await contract.getByRole('textbox',{name:'合同号（必填）',exact:true}).fill('MOBILE-'+Date.now());
  await contract.getByPlaceholder('选择交货日期').fill('2026-12-01');await contract.getByPlaceholder('选择交货日期').press('Enter');
  await contract.getByRole('button',{name:'下一步',exact:true}).click();
  await contract.getByRole('button',{name:'选择已有商品',exact:true}).click();
  const picker=page.getByRole('dialog',{name:'选择商品',exact:true});
  await picker.locator('.mobile-record').filter({has:page.getByText('GT-2026-1',{exact:true})}).getByRole('button',{name:'加入',exact:true}).click();
  await picker.getByRole('button',{name:'关闭此对话框',exact:true}).click();
  await contract.locator('.size-grid label').filter({has:page.getByText('M',{exact:true})}).getByRole('spinbutton').fill('2');
  // Upload failure keeps the form, then a user-initiated retry succeeds.
  const style=contract.locator('.contract-images section').first();
  await page.route('**/api/admin/uploads',r=>r.abort('failed'));
  await style.locator('input[type=file]').setInputFiles(photo);
  await style.getByRole('button',{name:'重试',exact:true}).waitFor();
  check(await contract.locator('.size-grid label').filter({has:page.getByText('M',{exact:true})}).getByRole('spinbutton').inputValue()==='2','Upload failure lost quantities');
  await page.unroute('**/api/admin/uploads');
  await style.getByRole('button',{name:'重试',exact:true}).click();
  await style.locator('.image-tile').waitFor();
  await contract.locator('.contract-images section').nth(1).locator('input[type=file]').setInputFiles(photo);
  await contract.locator('.contract-images section').nth(1).locator('.image-tile').waitFor();
  await contract.getByRole('button',{name:'下一步',exact:true}).click();
  const saved=page.waitForResponse(r=>r.url().endsWith('/api/admin/contracts')&&r.request().method()==='POST');
  await contract.getByRole('button',{name:/确认创建/}).click();check((await saved).ok(),'Phone contract save failed');
  const detail=page.getByRole('dialog').filter({has:page.getByRole('button',{name:'导出合同 Excel',exact:true})});
  const download=page.waitForEvent('download');await detail.getByRole('button',{name:'导出合同 Excel',exact:true}).click();check(!(await (await download).failure()),'Contract export failed');
  await detail.getByRole('button',{name:'关闭',exact:true}).click();
  await page.goto(base+'/presale');await page.getByRole('button',{name:'＋ 添加款号',exact:true}).click();
  const presale=page.getByRole('dialog',{name:'添加完整款号（全部颜色）',exact:true});await fits(presale);
  await presale.locator('.mobile-record-select:not(.is-disabled)').first().click();
  await presale.getByRole('button',{name:'添加 1 款',exact:true}).click();
  const presaleSaved=page.waitForResponse(r=>r.url().includes('/api/admin/presale')&&r.request().method()==='PUT');
  await page.getByRole('button',{name:'保存修改',exact:true}).click();check((await presaleSaved).ok(),'Presale save failed');
  await page.goto(base+'/admin-users');await page.getByRole('button',{name:'＋ 新建账号',exact:true}).click();
  const account=page.getByRole('dialog',{name:'新建账号',exact:true});await fits(account);
  await account.getByRole('textbox',{name:'*姓名',exact:true}).fill('手机验收账号');
  await account.getByRole('textbox',{name:'*登录账号 / 邮箱',exact:true}).fill('mobile-'+Date.now()+'@gingtto.test');
  await account.getByRole('textbox',{name:/登录密码/}).fill('Mobile-Fixture-2026');
  await account.getByRole('button',{name:'恢复部门默认',exact:true}).click();
  const accountSaved=page.waitForResponse(r=>r.url().endsWith('/api/admin/admin-users')&&r.request().method()==='POST');
  await account.getByRole('button',{name:'保存账号',exact:true}).click();check((await accountSaved).ok(),'Phone account save failed');await account.waitFor({state:'hidden'});
  return {productSave:true,routeGuardRetainsDraft:true,contractCreate:true,contractExport:true,uploadFailureRetainsInput:true,uploadRetry:true,presaleSave:true,accountSave:true};
}
