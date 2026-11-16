// Real controls/downloads, bound to the repository's isolated order fixture.
async page => {
  const base=new URL(page.url()).origin;
  if(!['http://127.0.0.1:5360','http://127.0.0.1:5396'].includes(base))throw new Error('Isolated draft fixture required');
  let checks=0;
  const check=(ok,message)=>{if(!ok)throw new Error(message);checks++;};
  const api=(path,method='GET',body)=>page.evaluate(async({path,method,body})=>{
    const csrf=(await fetch('/api/auth/csrf').then(r=>r.json())).csrfToken;
    const r=await fetch('/api/admin/'+path,{method,headers:{'Content-Type':'application/json','X-CSRF-Token':csrf},...(body?{body:JSON.stringify(body)}:{})});
    if(!r.ok)throw new Error(path+': '+r.status);return r.json();
  },{path,method,body});
  await page.setViewportSize({width:1440,height:1000});
  await page.goto(base+'/orders');
  await page.waitForFunction(()=>location.pathname==='/login'||document.querySelector('.profile-button'));
  if(new URL(page.url()).pathname!=='/login'){
    await page.locator('.profile-button').click();await page.getByRole('menuitem',{name:'退出登录',exact:true}).click();
  }
  await page.waitForURL(url=>url.pathname==='/login');
  await page.getByRole('textbox',{name:'账号 / 邮箱'}).fill('admin@gingtto.test');
  await page.getByRole('textbox',{name:'密码',exact:true}).fill('Workbench-Test-2026');
  await page.getByRole('button',{name:'登录工作台',exact:true}).click();
  await page.waitForURL(url=>url.pathname!=='/login');await page.goto(base+'/orders');
  const before=(await api('inventory/1')).product.stock;
  const name='Draft invoice browser '+Date.now();
  const saved=await api('orders/drafts','POST',{draftKey:crypto.randomUUID(),draft:{contactName:name,shippingFee:0,note:'Saved draft quote',
    items:[{productId:1,sku:'Fixture draft SKU',productName:'Draft product',sizeCode:'M',quantity:2,unitPrice:17,priceSource:'manual'}]}});
  await page.getByRole('button',{name:'我的草稿',exact:true}).click();
  const drafts=page.getByRole('dialog',{name:'订单草稿',exact:true}).filter({has:page.getByRole('textbox',{name:'搜索草稿',exact:true})});
  const row=drafts.locator('.el-table__row').filter({hasText:name});
  await row.getByRole('button',{name:'导出订单详情',exact:true}).waitFor();
  let downloading=page.waitForEvent('download');
  await row.getByRole('button',{name:'导出订单详情',exact:true}).click();
  let file=await downloading;check(file.suggestedFilename().includes('DRAFT-'+saved.id),'Draft export not marked in filename');
  await file.saveAs('output/playwright/draft-invoice-list.xlsx');
  check((await api('inventory/1')).product.stock===before,'Draft list export touched inventory');
  await row.getByRole('button',{name:'继续编辑',exact:true}).click();
  await drafts.waitFor({state:'hidden'});
  const editor=page.getByRole('dialog',{name:'订单草稿',exact:true}).filter({has:page.getByRole('textbox',{name:'备注',exact:true})});
  const exportButton=editor.getByRole('button',{name:'导出订单详情',exact:true});
  await exportButton.waitFor();await page.waitForFunction(()=>!document.querySelector('.el-drawer .el-loading-mask'));
  check(await exportButton.isEnabled(),'Saved incomplete/zero-freight draft cannot be exported');
  await editor.getByRole('textbox',{name:'备注',exact:true}).fill('Changed but not saved');
  check(await exportButton.isDisabled(),'Unsaved draft can be exported');
  const saving=page.waitForResponse(r=>r.url().endsWith('/api/admin/orders/drafts/'+saved.id)&&r.request().method()==='PUT');
  await editor.getByRole('button',{name:'保存草稿',exact:true}).click();check((await saving).status()===200,'Partial draft save rejected');
  await page.getByText('草稿已保存，可从“我的草稿”继续编辑',{exact:true}).waitFor();
  downloading=page.waitForEvent('download');await exportButton.click();file=await downloading;
  await file.saveAs('output/playwright/draft-invoice-editor.xlsx');
  check((await api('inventory/1')).product.stock===before,'Editor draft export touched inventory');
  await page.screenshot({path:'output/playwright/draft-invoice-desktop.png',animations:'disabled'});
  await page.setViewportSize({width:390,height:844});
  const mobileExport=page.getByRole('button',{name:'导出订单详情',exact:true});
  await mobileExport.waitFor();
  check(await mobileExport.isVisible(),'Draft export missing on mobile');
  check(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),'Draft export caused horizontal overflow');
  await page.screenshot({path:'output/playwright/draft-invoice-mobile.png',animations:'disabled'});
  return {passed:true,checks,draftListExport:true,draftEditorExport:true,zeroFreight:true,unsavedBlocked:true,noInventoryChanges:true,mobile:true};
}
