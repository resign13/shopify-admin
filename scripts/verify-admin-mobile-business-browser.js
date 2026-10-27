// Full interactions against the explicitly isolated order-selection fixture.
async (page) => {
  const base='http://127.0.0.1:5360';
  if(!page.url().startsWith(base+'/'))throw new Error('Isolated *_test fixture required');
  const check=(value,message)=>{if(!value)throw new Error(message);};
  const api=(path,method='GET',body)=>page.evaluate(async({path,method,body})=>{
    const csrf=await fetch('/api/auth/csrf').then(r=>r.json());
    const r=await fetch('/api/admin/'+path,{method,headers:{'Content-Type':'application/json','X-CSRF-Token':csrf.csrfToken},...(body?{body:JSON.stringify(body)}:{})});
    if(!r.ok)throw new Error('Fixture API '+path+': '+r.status);return r.json();
  },{path,method,body});
  await page.unrouteAll();await page.setViewportSize({width:390,height:844});await page.goto(base+'/orders');await page.waitForLoadState('networkidle');
  await page.getByRole('button',{name:'展开导航',exact:true}).click();
  await page.getByRole('link',{name:'库存管理',exact:true}).waitFor();
  await page.getByRole('link',{name:'订单管理',exact:true}).click();
  check(await page.locator('.workspace-sidebar').getAttribute('aria-hidden')==='true','Navigation did not close');
  await page.locator('.mobile-record-select').first().click();
  let reads=0;const listener=r=>{if(r.url().includes('/api/admin/orders?'))reads++;};page.on('request',listener);
  await page.setViewportSize({width:1440,height:1000});await page.locator('main .el-table').waitFor();
  await page.waitForFunction(()=>document.querySelectorAll('main .el-table__row .el-checkbox.is-checked').length===1);
  await page.setViewportSize({width:390,height:844});
  check(await page.getByRole('checkbox',{name:'选择第 1 项',exact:true}).isChecked(),'Selection lost on resize');
  check(reads===0,'Resizing issued duplicate business queries');page.off('request',listener);
  await page.getByRole('button',{name:'清空选择',exact:true}).click();
  const previous=await page.locator('main .mobile-table > .mobile-record').count();
  await page.route('**/api/admin/orders?**',r=>r.abort('failed'));
  await page.locator('.responsive-filters input').first().fill('fixture-retry');
  await page.getByRole('button',{name:'查询',exact:true}).click();
  await page.getByRole('alert').filter({hasText:'连接失败'}).waitFor();
  check(await page.locator('main .mobile-table > .mobile-record').count()===previous,'Failed query discarded old rows');
  await page.unroute('**/api/admin/orders?**');await page.getByRole('button',{name:'重试',exact:true}).click();await page.waitForLoadState('networkidle');
  await page.goto(base+'/inventory?keyword=GT-2026-1');await page.waitForLoadState('networkidle');
  const before=(await api('inventory/1')).product;
  const m=before.sizePrices.find(s=>s.sizeCode==='M');
  await page.getByRole('button',{name:'登记数量',exact:true}).first().click();
  const dialog=page.getByRole('dialog',{name:'登记库存与到货进度',exact:true});
  const row=dialog.locator('.mobile-record').filter({has:page.getByRole('spinbutton',{name:'现货余额 M',exact:true})});
  await row.waitFor();
  for(const label of ['现货余额','合同未送','待验货','次品','合格','临时待入库'])check(await row.getByRole('spinbutton',{name:label+' M',exact:true}).isVisible(),'Missing mobile stage '+label);
  await row.getByRole('spinbutton',{name:'现货余额 M',exact:true}).fill(String(m.stock+1));
  await row.getByRole('spinbutton',{name:'现货余额 M',exact:true}).press('Tab');
  await row.getByRole('spinbutton',{name:'待验货 M',exact:true}).fill(String(m.pendingInspection+1));
  await row.getByRole('spinbutton',{name:'待验货 M',exact:true}).press('Tab');
  check(Number(await row.getByRole('spinbutton',{name:'合同未送 M',exact:true}).inputValue())===m.contractPending-1,'Stage transfer not preserved');
  await page.screenshot({path:'output/playwright/admin-mobile-inventory-registration.png',fullPage:false});
  const saved=page.waitForResponse(r=>r.url().endsWith('/api/admin/inventory/1')&&r.request().method()==='PUT');
  await dialog.getByRole('button',{name:'保存修改',exact:true}).click();check((await saved).ok(),'Inventory save failed');await dialog.waitFor({state:'hidden'});
  const after=(await api('inventory/1')).product.sizePrices.find(s=>s.sizeCode==='M');
  check(after.stock===m.stock+1&&after.pendingInspection===m.pendingInspection+1&&after.contractPending===m.contractPending-1,'Saved stages differ from preview');
  check(after.pendingInbound===m.pendingInbound&&after.temporaryInbound===m.temporaryInbound,'Untouched stages changed');
  // Batch selection remains a page selection, and confirmation is still atomic.
  await page.getByRole('button',{name:'列表操作',exact:true}).click();
  await page.getByRole('button',{name:'全部勾选',exact:true}).click();
  await page.getByRole('button',{name:'列表操作',exact:true}).click();
  await page.getByRole('button',{name:'一键入库',exact:true}).click();
  const receipt=page.getByRole('dialog').filter({has:page.getByRole('button',{name:'确认入库',exact:true})});
  await receipt.locator('.mobile-record').first().waitFor();
  check(await receipt.evaluate(el=>el.getBoundingClientRect().width<=innerWidth+1),'Receipt does not fit phone');
  const receive=page.waitForResponse(r=>r.url().includes('/api/admin/inventory/batch/receive')&&r.request().method()==='POST');
  await receipt.getByRole('button',{name:'确认入库',exact:true}).click();check((await receive).ok(),'Batch inbound failed');await receipt.waitFor({state:'hidden'});
  check((await api('inventory/1')).product.sizePrices.find(s=>s.sizeCode==='M').pendingInbound===0,'Batch receipt did not clear qualified quantity');
  const dl=page.waitForEvent('download');await page.getByRole('button',{name:'导出库存',exact:true}).click();
  const file=await dl;check(!(await file.failure()),'Mobile Excel download failed');await file.saveAs('output/playwright/admin-mobile-inventory.xlsx');
  // Unsaved edits use the same confirmation, including layout changes.
  await page.getByRole('button',{name:'登记数量',exact:true}).first().click();
  await dialog.getByRole('spinbutton',{name:'临时待入库 M',exact:true}).fill('3');await dialog.getByRole('spinbutton',{name:'临时待入库 M',exact:true}).press('Tab');
  await dialog.getByRole('button',{name:'取消',exact:true}).click();
  const leave=page.getByRole('dialog',{name:'未保存修改',exact:true});await leave.waitFor();
  await leave.getByRole('button',{name:'取消',exact:true}).click();
  check(await dialog.getByRole('spinbutton',{name:'临时待入库 M',exact:true}).inputValue()==='3','Cancelled leave lost draft');
  await dialog.getByRole('button',{name:'取消',exact:true}).click();await leave.getByRole('button',{name:'确认',exact:true}).click();await dialog.waitFor({state:'hidden'});
  await page.goto(base+'/api-integrations');await page.waitForLoadState('networkidle');
  if(await page.getByRole('button',{name:'生成 Key',exact:true}).count()) {
    await page.getByRole('button',{name:'生成 Key',exact:true}).click();
    await page.getByRole('dialog',{name:'生成 Key',exact:true}).getByRole('button',{name:'确认生成',exact:true}).click();
    const secret=page.getByRole('dialog',{name:'请立即保存完整 Key',exact:true});
    await secret.waitFor();check((await secret.getByRole('textbox',{name:'完整 API Key'}).inputValue()).length>30,'Missing one-time key');
    await secret.getByRole('button',{name:'已保存，关闭',exact:true}).click();await secret.waitFor({state:'hidden'});
    check(await page.getByRole('textbox',{name:'完整 API Key'}).count()===0,'One-time key remains in DOM');
  }
  await page.getByRole('tab',{name:'接口说明',exact:true}).click();
  check(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),'API docs overflow');
  return {navigation:true,selectionSurvivesResize:true,noResizeRequests:true,failureRetainsRows:true,
    allSixInventoryStages:true,stageTransfer:true,inventorySave:true,batchInbound:true,excelDownload:true,
    unsavedConfirmation:true,keyOneTimeDisplay:true,apiDocs:true};
}
