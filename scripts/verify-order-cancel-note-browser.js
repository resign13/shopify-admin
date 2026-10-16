// Run only on the dedicated local *_test UI fixture started on port 5360.
async (page) => {
  const base = 'http://127.0.0.1:5360';
  if (!page.url().startsWith(base + '/')) throw new Error('Isolated fixture required');
  const check = (ok, message) => { if (!ok) throw new Error(message); };
  const api = (path, method='GET', body) => page.evaluate(async ({path,method,body}) => {
    const csrf = await fetch('/api/auth/csrf').then(r=>r.json());
    const r = await fetch('/api/admin/'+path,{method,headers:{'X-CSRF-Token':csrf.csrfToken,'Content-Type':'application/json'},
      ...(body ? {body:JSON.stringify(body)} : {})});
    if (!r.ok) throw new Error(`Fixture API ${path}: ${r.status}`);
    return r.json();
  }, {path,method,body});
  const login = async role => {
    await page.goto(base+'/orders?page=1&pageSize=25');
    await page.locator('.profile-button').click();
    await page.getByRole('menuitem',{name:'退出登录',exact:true}).click();
    await page.waitForURL(url=>url.pathname==='/login');
    await page.getByRole('textbox',{name:'账号 / 邮箱'}).fill(role+'@gingtto.test');
    await page.getByRole('textbox',{name:'密码',exact:true}).fill('Workbench-Test-2026');
    await page.getByRole('button',{name:'登录工作台',exact:true}).click();
    await page.waitForURL(url=>url.pathname!=='/login');
    await page.goto(base+'/orders?page=1&pageSize=25');
    await page.getByRole('button',{name:'订单详情',exact:true}).first().waitFor();
  };
  const query = async no => {
    if (new URL(page.url()).searchParams.get('keyword') === no) {
      await page.reload();
      await page.getByRole('button',{name:'订单详情',exact:true}).waitFor();
      return;
    }
    await page.getByRole('textbox',{name:'订单查询关键词'}).fill(no);
    const response = page.waitForResponse(r=>r.url().includes('/api/admin/orders?') && new URL(r.url()).searchParams.get('keyword')===no);
    await page.locator('main form.filters').getByRole('button',{name:'查询',exact:true}).click();
    check((await response).status()===200,'Query failed');
    await page.getByRole('button',{name:'订单详情',exact:true}).waitFor();
  };
  const stock = async () => {
    const p = (await api('inventory/1')).product;
    return JSON.stringify([p.stock,p.sizePrices.map(s=>[s.sizeCode,s.stock])]);
  };
  await page.setViewportSize({width:1920,height:1080});
  await login('admin');
  const initialStock = await stock();
  const created = await api('orders','POST',{requestId:crypto.randomUUID(),userId:1,ownerAdminId:2,
    contactName:'Cancellation UI Fixture',phone:'123456',country:'Germany',address:'Fixture address',note:'Original packing note',
    shippingFee:12.5,items:[{productId:1,sizeCode:'M',quantity:2,unitPrice:20},{productId:1,sizeCode:'L',quantity:1,unitPrice:25}]});
  const id=created.order.id;
  const detail=async ()=>(await api(`orders/${id}`)).order;
  const no=(await detail()).orderNo, reservedStock=await stock();
  check(reservedStock!==initialStock,'Create did not reserve stock');
  const transition=async status=>{const o=await detail();await api(`orders/${id}`,'PUT',{version:o.version,status});};
  const openCancel=async()=>{
    await page.getByRole('button',{name:`修改订单 ${no} 状态`,exact:true}).click();
    await page.getByRole('menuitem',{name:'已取消',exact:true}).click();
    const dialog=page.getByRole('dialog',{name:'取消订单',exact:true});
    await dialog.getByRole('textbox',{name:'取消备注（选填）',exact:true}).waitFor();
    return dialog;
  };
  const drawer=()=>page.getByRole('dialog',{name:'订单详情 · '+no,exact:true});
  const openDetail=async()=>{
    await page.getByRole('button',{name:'订单详情',exact:true}).click();
    await drawer().getByText('Original packing note',{exact:true}).waitFor();
    return drawer();
  };
  const noteDialog=()=>page.getByRole('dialog',{name:'修改取消备注',exact:true});
  const applyNote=async text=>{
    await drawer().getByRole('button',{name:/^(修改|填写)取消备注$/}).click();
    await noteDialog().getByRole('textbox',{name:'取消备注（选填）',exact:true}).fill(text);
    const r=page.waitForResponse(r=>r.url().endsWith(`/api/admin/orders/${id}`) && r.request().method()==='PUT');
    await noteDialog().getByRole('button',{name:'保存取消备注',exact:true}).click();
    check((await r).status()===200,'Note-only save failed');
    await noteDialog().waitFor({state:'hidden'});
  };
  await query(no);
  let dialog=await openCancel();
  await dialog.getByRole('textbox',{name:'取消备注（选填）',exact:true}).fill('Unsaved reason');
  await dialog.getByRole('button',{name:'返回',exact:true}).click();
  await page.getByRole('dialog',{name:'确认操作',exact:true}).getByRole('button',{name:'确认',exact:true}).click();
  check((await detail()).status==='pending_payment' && await stock()===reservedStock,'Discarded cancellation wrote business data');
  dialog=await openCancel();
  await dialog.getByRole('textbox',{name:'取消备注（选填）',exact:true}).fill('List reason\nSecond line');
  // A second window changes the version; textarea must survive the 409.
  await transition('allocated');
  const rejected=page.waitForResponse(r=>r.url().endsWith(`/api/admin/orders/${id}`) && r.request().method()==='PUT');
  await dialog.getByRole('button',{name:'确认取消订单',exact:true}).click();
  check((await rejected).status()===409,'Expected conflict not returned');
  check(await dialog.getByRole('textbox',{name:'取消备注（选填）',exact:true}).inputValue()==='List reason\nSecond line','Conflict lost reason');
  await dialog.getByRole('button',{name:'刷新订单版本（保留备注）',exact:true}).click();
  await dialog.getByText('已配货 → 已取消；商品库存按现有规则返还。',{exact:true}).waitFor();
  const saved=page.waitForResponse(r=>r.url().endsWith(`/api/admin/orders/${id}`) && r.request().method()==='PUT');
  await dialog.getByRole('button',{name:'确认取消订单',exact:true}).click();
  check((await saved).status()===200,'Cancellation after refresh failed');
  await dialog.waitFor({state:'hidden'});
  check(await stock()===initialStock,'Cancellation did not return exactly original quantities');
  await page.getByTestId('cancel-note-mark').waitFor();
  await page.getByTestId('cancel-note-mark').focus();
  await page.getByRole('tooltip').filter({hasText:'List reason'}).waitFor();
  check(await page.getByRole('tooltip').filter({hasText:'List reason'}).evaluate(el=>getComputedStyle(el).pointerEvents==='none'),'Note tooltip blocks row actions');
  await openDetail();
  check((await drawer().getByTestId('cancel-note-detail').textContent()).includes('List reason'),'Detail note missing');
  await applyNote('Updated reason\n<img src=x onerror=alert(1)>');
  check(await stock()===initialStock,'Note edit affected inventory');
  check(await drawer().getByTestId('cancel-note-detail').locator('img').count()===0,'Note HTML interpreted');
  const o=await detail();
  check(o.note==='Original packing note' && o.totalAmount===77.5 && o.shippingFee===12.5,'Note edit altered original fields');
  await drawer().getByText('$65.00',{exact:true}).waitFor();
  await drawer().getByText('$77.50',{exact:true}).waitFor();
  await page.screenshot({path:'output/playwright/order-cancel-note-desktop.png',fullPage:true,animations:'disabled'});
  await applyNote('');
  check((await detail()).cancelNote==='','Clear did not persist');
  await drawer().getByRole('button',{name:'关闭',exact:true}).click();
  check(await page.getByTestId('cancel-note-mark').count()===0,'Empty note icon remains');
  await transition('paid'); await query(no);
  check(await stock()===reservedStock && (await detail()).cancelNote==='','Restore did not clear note or reserve stock');
  dialog=await openCancel();
  check(await dialog.getByRole('textbox',{name:'取消备注（选填）',exact:true}).inputValue()==='','Recancel inherited old reason');
  await dialog.getByRole('button',{name:'返回',exact:true}).click();
  // Full order editor cancellation entry.
  await openDetail(); await drawer().getByRole('button',{name:'修改订单资料',exact:true}).click();
  await drawer().locator('.el-form-item').filter({has:page.getByRole('combobox',{name:/订单状态/})}).locator('.el-select').click();
  await page.getByRole('option',{name:'已取消',exact:true}).click();
  await drawer().getByRole('textbox',{name:'取消备注（选填）',exact:true}).fill('Full editor reason');
  const fullSave=page.waitForResponse(r=>r.url().endsWith(`/api/admin/orders/${id}/details`) && r.request().method()==='PUT');
  await drawer().getByRole('button',{name:'保存修改',exact:true}).click();
  await page.getByRole('dialog',{name:'确认操作',exact:true}).getByRole('button',{name:'确认',exact:true}).click();
  check((await fullSave).status()===200,'Full editor cancellation failed');
  check((await detail()).cancelNote==='Full editor reason' && await stock()===initialStock,'Full editor note/stock incorrect');
  await drawer().getByRole('button',{name:'修改订单资料',exact:true}).waitFor();
  await drawer().getByRole('button',{name:'关闭',exact:true}).click();
  await transition('paid');
  // Warehouse quick-status cancellation and no financial disclosure.
  await login('warehouse'); await query(no); await openDetail();
  await drawer().getByRole('button',{name:'修改订单状态',exact:true}).click();
  await drawer().locator('.el-form-item').filter({has:page.getByRole('combobox',{name:/订单状态/})}).locator('.el-select').click();
  await page.getByRole('option',{name:'已取消',exact:true}).click();
  await drawer().getByRole('textbox',{name:'取消备注（选填）',exact:true}).fill('Warehouse reason');
  const quickSave=page.waitForResponse(r=>r.url().endsWith(`/api/admin/orders/${id}`) && r.request().method()==='PUT');
  await drawer().getByRole('button',{name:'保存修改',exact:true}).click();
  await page.getByRole('dialog',{name:'确认操作',exact:true}).getByRole('button',{name:'确认',exact:true}).click();
  const quick=await quickSave;
  check(quick.status()===200,'Warehouse cancellation failed');
  check(!('totalAmount' in (await quick.json()).order),'Warehouse financial disclosure');
  check(await stock()===initialStock,'Warehouse cancel stock incorrect');
  await drawer().getByRole('button',{name:'修改取消备注',exact:true}).waitFor();
  await applyNote('Warehouse amended');
  await drawer().getByRole('button',{name:'关闭',exact:true}).click();
  // Sales can see own cancellation note; mobile tap and dialog layout.
  await login('sales'); await query(no);
  await page.setViewportSize({width:390,height:844});
  await page.getByTestId('cancel-note-mark').click();
  await page.getByRole('tooltip').filter({hasText:'Warehouse amended'}).waitFor();
  await openDetail();
  await drawer().getByRole('button',{name:'修改取消备注',exact:true}).click();
  check(await noteDialog().getByRole('textbox',{name:'取消备注（选填）',exact:true}).inputValue()==='Warehouse amended','Sales note missing');
  const bounds=await noteDialog().boundingBox();
  check(bounds.width<=390 && bounds.x>=0,'Mobile dialog overflow');
  await page.screenshot({path:'output/playwright/order-cancel-note-mobile.png',fullPage:true,animations:'disabled'});
  await noteDialog().getByRole('button',{name:'返回',exact:true}).click();
  const events=(await api(`orders/${id}/operations`)).items;
  check(events.some(e=>e.changes.some(c=>c.field==='cancelNote' && c.after==='Warehouse amended')),'Note audit missing');
  return {listCancel:true,discardNoWrite:true,conflictKeepsInput:true,refreshThenConfirm:true,stockReturnedOnce:true,
    tooltipKeyboardAndMobileTap:true,tooltipDoesNotBlockActions:true,detailNoteEditAndClear:true,plainTextEscaping:true,ordinaryNoteAndMoneyUnchanged:true,
    restoreClears:true,recancelBlank:true,fullEditorEntry:true,warehouseEntry:true,warehouseMoneyHidden:true,
    salesOwnOrderVisible:true,narrowLayout:true,audit:true};
}
