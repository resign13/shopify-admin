// Guarded UI fixture only; all API writes here target the dedicated *_test DB.
async (page) => {
  const base='http://127.0.0.1:5360';
  if(!page.url().startsWith(base+'/'))throw new Error('Isolated fixture required');
  // Reset only this script's fault-injection route when rerunning a failed check.
  await page.unroute('**/api/admin/orders/1');
  const check=(ok,msg)=>{if(!ok)throw new Error(msg);};
  const api=(path,method='GET',body)=>page.evaluate(async({path,method,body})=>{
    const csrf=await fetch('/api/auth/csrf').then(r=>r.json());
    const r=await fetch('/api/admin/'+path,{method,headers:{'Content-Type':'application/json','X-CSRF-Token':csrf.csrfToken},...(body?{body:JSON.stringify(body)}:{})});
    if(!r.ok)throw new Error(`Fixture API ${path}: ${r.status}`);
    return r.json();
  },{path,method,body});
  const setStock=async(pid,sizes)=>{
    const product=(await api(`inventory/${pid}`)).product;
    await api(`inventory/${pid}`,'PUT',{version:product.version,sizeStocks:sizes});
  };
  const getOrder=async(id=1)=>(await api(`orders/${id}`)).order;
  const open=async(id=1)=>{
    const order=await getOrder(id);
    await page.goto(base+'/orders?page=1&pageSize=25&keyword='+encodeURIComponent(order.orderNo));
    await page.getByRole('button',{name:'订单详情',exact:true}).click();
    const detail=page.getByRole('dialog',{name:'订单详情 · '+order.orderNo,exact:true});
    await detail.getByRole('button',{name:'刷新详情',exact:true}).waitFor();
    return detail;
  };
  const login=async(role)=>{
    await page.goto(base+'/orders?page=1&pageSize=25');
    await page.locator('.profile-button').click();
    await page.getByRole('menuitem',{name:'退出登录',exact:true}).click();
    await page.waitForURL(u=>u.pathname==='/login');
    await page.getByRole('textbox',{name:'账号 / 邮箱'}).fill(role+'@gingtto.test');
    await page.getByRole('textbox',{name:'密码',exact:true}).fill('Workbench-Test-2026');
    await page.getByRole('button',{name:'登录工作台',exact:true}).click();
    await page.waitForURL(u=>u.pathname!=='/login');
  };
  const refresh=async(detail)=>{
    const response=page.waitForResponse(r=>r.url().endsWith('/api/admin/orders/1') && r.request().method()==='GET');
    await detail.getByRole('button',{name:'刷新详情',exact:true}).click();
    const result=await response;check(result.status()===200,'Detail refresh failed');
    await result.finished();
    // A network response event precedes response.json() and Vue's render tick.
    // Wait for the actual UI recovery, including when the stock value is unchanged.
    await detail.getByTestId('order-stock-stale').waitFor({state:'hidden'});
  };
  const hint=(detail,pid=1,size='M')=>detail.getByTestId(`detail-stock-${pid}-${size}`);
  await page.setViewportSize({width:1920,height:1080});
  await login('admin');
  const initialOrder=await getOrder();
  if(initialOrder.status!=='paid')await api('orders/1','PUT',{version:initialOrder.version,status:'paid'});
  await setStock(1,{M:12,L:0}); await setStock(2,{M:-5});
  let inventoryReads=0;
  const count=r=>{if(r.method()==='GET' && /\/api\/admin\/inventory\//.test(r.url()))inventoryReads++;};
  page.on('request',count);
  let detail=await open();
  check(await hint(detail).textContent()==='库存 12','Current balance deducted order quantities a second time');
  check(await hint(detail,2).textContent()==='库存 -5 · 欠货','Signed shortage missing');
  check((await hint(detail,2).getAttribute('class')).includes('is-shortage'),'Shortage is not highlighted');
  check(!(await hint(detail).getAttribute('class')).includes('is-shortage'),'Positive balance incorrectly highlighted');
  check((await hint(detail).getAttribute('title')).includes('非本单独立欠货'),'Scope explanation missing');
  check(await detail.getByRole('columnheader',{name:'库存',exact:true}).count()===0,'Unexpected extra inventory column');
  check((await hint(detail).locator('..').textContent()).trim().startsWith('2'),'Purchased quantity changed');
  check(inventoryReads===0,'Detail unnecessarily fetched inventory module');
  await page.screenshot({path:'output/playwright/order-detail-stock-desktop.png',fullPage:true,animations:'disabled'});
  const previous=await getOrder();
  await page.route('**/api/admin/orders/1',r=>r.fulfill({status:503,contentType:'application/json',body:JSON.stringify({message:'Fixture temporary failure'})}));
  await detail.getByRole('button',{name:'刷新详情',exact:true}).click();
  await detail.getByTestId('order-stock-stale').waitFor();
  check(await hint(detail).textContent()==='库存 12','Refresh error cleared previous balance');
  check((await hint(detail).getAttribute('title')).includes('上次读取结果'),'Old balance not labelled stale');
  await page.unroute('**/api/admin/orders/1');
  page.off('request',count);
  await setStock(1,{M:-7});
  page.on('request',count);
  await refresh(detail);
  await page.waitForFunction(()=>document.querySelector('[data-testid="detail-stock-1-M"]')?.textContent==='库存 -7 · 欠货');
  check(await detail.getByTestId('order-stock-stale').count()===0,'Stale warning remains after successful refresh');
  const updated=await getOrder();
  check(updated.version===previous.version && updated.items[0].quantity===previous.items[0].quantity,'Read/refresh changed order');
  await detail.getByRole('button',{name:'关闭',exact:true}).click();
  // Zero and historical missing sizes do not borrow the product's total stock.
  detail=await open(4);
  check(await hint(detail,1,'L').textContent()==='库存 0','Zero stock not displayed');
  await detail.getByRole('button',{name:'关闭',exact:true}).click();
  detail=await open(2);
  check(await hint(detail,1,'').textContent()==='库存不可用','Blank historical size guessed inventory');
  check(await hint(detail,2,'Removed-size').textContent()==='库存不可用','Removed size guessed inventory');
  await detail.getByRole('button',{name:'关闭',exact:true}).click();
  // A late refresh for a closed drawer must not overwrite a different order.
  detail=await open();
  const earlier=await getOrder();
  let release, started;
  const held=new Promise(resolve=>{release=resolve;});
  const intercepted=new Promise(resolve=>{started=resolve;});
  await page.route('**/api/admin/orders/1',async r=>{started();await held;await r.fulfill({status:200,contentType:'application/json',body:JSON.stringify({order:earlier})});});
  await detail.getByRole('button',{name:'刷新详情',exact:true}).click();await intercepted;
  await detail.getByRole('button',{name:'关闭',exact:true}).click();
  const secondOrder=await getOrder(2);
  await page.getByRole('textbox',{name:'订单查询关键词'}).fill(secondOrder.orderNo);
  const secondList=page.waitForResponse(r=>r.url().includes('/api/admin/orders?') && new URL(r.url()).searchParams.get('keyword')===secondOrder.orderNo);
  await page.locator('main form.filters').getByRole('button',{name:'查询',exact:true}).click();await secondList;
  await page.getByRole('button',{name:secondOrder.orderNo,exact:true}).waitFor();
  await page.getByRole('button',{name:'订单详情',exact:true}).click();
  detail=page.getByRole('dialog',{name:'订单详情 · '+secondOrder.orderNo,exact:true});
  await hint(detail,1,'').waitFor();
  const lateResponse=page.waitForResponse(r=>r.url().endsWith('/api/admin/orders/1'));
  release();await lateResponse;
  await page.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))));
  check(await hint(detail,1,'').textContent()==='库存不可用','Late stock response replaced a different order');
  await page.unroute('**/api/admin/orders/1');
  await detail.getByRole('button',{name:'关闭',exact:true}).click();
  // Cancellation is already reflected in the balance; note-only saves preserve it.
  let order=await getOrder();
  const cancelled=await api('orders/1','PUT',{version:order.version,status:'cancelled',cancelNote:'Stock check'});
  check(cancelled.order.items[0].currentStock===-5,'Cancel did not return exactly the order quantity');
  detail=await open();
  check(await hint(detail).textContent()==='库存 -5 · 欠货','Cancelled detail added stock back twice');
  await detail.getByRole('button',{name:'修改取消备注',exact:true}).click();
  const dialog=page.getByRole('dialog',{name:'修改取消备注',exact:true});
  await dialog.getByRole('textbox',{name:'取消备注（选填）',exact:true}).fill('Stock note amended');
  const noteSaved=page.waitForResponse(r=>r.url().endsWith('/api/admin/orders/1') && r.request().method()==='PUT');
  await dialog.getByRole('button',{name:'保存取消备注',exact:true}).click();
  const noteResponse=await noteSaved;check(noteResponse.status()===200,'Note save failed');
  check((await noteResponse.json()).order.items[0].currentStock===-5,'Note save changed inventory');
  await dialog.waitFor({state:'hidden'});
  check(await hint(detail).textContent()==='库存 -5 · 欠货','Note save lost balance in detail');
  await detail.getByRole('button',{name:'关闭',exact:true}).click();
  check(inventoryReads===0,'Order-only detail made inventory-module requests');
  page.off('request',count);
  // Warehouse and a finance account with only finance/orders grants both see stock.
  await login('warehouse'); detail=await open();
  check(await hint(detail).textContent()==='库存 -5 · 欠货','Warehouse missing stock');
  check(await detail.getByRole('columnheader',{name:'单价',exact:true}).count()===0,'Warehouse sees prices');
  await page.route('**/api/admin/orders/1',r=>r.fulfill({status:503,contentType:'application/json',body:JSON.stringify({message:'Fixture temporary failure'})}));
  await detail.getByRole('button',{name:'刷新详情',exact:true}).click();
  await detail.getByTestId('order-stock-stale').waitFor();await page.unroute('**/api/admin/orders/1');
  await detail.getByRole('button',{name:'修改订单状态',exact:true}).click();
  await detail.getByRole('button',{name:'取消修改',exact:true}).click();
  check(await detail.getByTestId('order-stock-stale').count()===1,'Cancelling edits hid stale-stock warning');
  await refresh(detail);
  check(await detail.getByTestId('order-stock-stale').count()===0,'Warehouse retry did not clear stale warning');
  const download=page.waitForEvent('download');
  await page.goto(base+'/orders?page=1&pageSize=25&keyword='+encodeURIComponent(order.orderNo));
  await page.getByRole('button',{name:'导出订单 ▾',exact:true}).click();
  await page.getByRole('menuitem',{name:/合并表格/}).click();
  await download;
  detail=await open();
  await detail.getByTestId('warehouse-printed-mark').waitFor();
  check(await hint(detail).textContent()==='库存 -5 · 欠货','Export/printed mark changed inventory');
  await detail.getByRole('button',{name:'关闭',exact:true}).click();
  await login('finance');
  check(await page.evaluate(()=>fetch('/api/admin/inventory/1').then(r=>r.status))===403,'Fixture finance unexpectedly has inventory access');
  detail=await open();
  check(await hint(detail).textContent()==='库存 -5 · 欠货','Order grant alone does not show inventory');
  await detail.getByRole('button',{name:'关闭',exact:true}).click();
  await login('sales'); detail=await open();
  check(await hint(detail).textContent()==='库存 -5 · 欠货','Sales own-order stock missing');
  check(await page.evaluate(()=>fetch('/api/admin/orders/2').then(r=>r.status))===404,'Sales can view another owner order');
  await page.setViewportSize({width:390,height:844});
  await hint(detail).scrollIntoViewIfNeeded();
  const quantityBox=await hint(detail).boundingBox();
  check(quantityBox.x>=0 && quantityBox.x+quantityBox.width<=391,'Mobile stock hint outside table viewport');
  check(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth),'Mobile page horizontally overflows');
  await page.screenshot({path:'output/playwright/order-detail-stock-mobile.png',fullPage:true,animations:'disabled'});
  return {currentNotDoubleDeducted:true,negativeAndZero:true,realSizeAndColor:true,sharedHint:true,
    readOnlyVersion:true,refreshFailureRetainsLabelledData:true,retryUpdates:true,missingSizesUnavailable:true,lateResponseIgnored:true,
    cancelledNotDoubleReturned:true,noteSaveKeepsStock:true,noInventoryEndpointDependency:true,
    warehouseRedaction:true,cancelEditPreservesStaleWarning:true,printedMarkPreserved:true,financeOrderOnly:true,salesOwnership:true,mobile:true};
}
