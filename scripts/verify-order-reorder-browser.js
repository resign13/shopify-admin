// Real browser checks run only against the guarded weights *_test fixture.
async (page) => {
  const base = 'http://127.0.0.1:5360';
  page.removeAllListeners('dialog');
  page.on('dialog', dialog => dialog.accept());
  if (!page.url().startsWith(base + '/')) throw new Error('Isolated fixture required');
  const check = (condition, message) => { if (!condition) throw new Error(message); };
  const api = (path, method = 'GET', body) => page.evaluate(async ({path, method, body}) => {
    const response = await fetch('/api/admin/' + path, {method,
      headers:{Authorization:'Bearer '+localStorage.getItem('lumiere-admin-token'),'Content-Type':'application/json'},
      ...(body ? {body:JSON.stringify(body)} : {})});
    if (!response.ok) throw new Error('Fixture API '+path+': '+response.status);
    return response.json();
  }, {path, method, body});
  await page.goto(base + '/orders');
  await page.waitForFunction(() => location.pathname === '/login' || document.querySelector('.profile-button'));
  if (!new URL(page.url()).pathname.startsWith('/login')) {
    await page.locator('.profile-button').click();
    await page.getByRole('menuitem',{name:'退出登录',exact:true}).click();
  }
  await page.waitForURL(url=>url.pathname==='/login');
  await page.getByRole('textbox',{name:'账号 / 邮箱'}).fill('admin@gingtto.test');
  await page.getByRole('textbox',{name:'密码',exact:true}).fill('Workbench-Test-2026');
  await page.getByRole('button',{name:'登录工作台',exact:true}).click();
  await page.waitForURL(url=>url.pathname!=='/login');
  await page.goto(base+'/orders');
  const resetList=page.waitForResponse(r=>r.url().includes('/api/admin/orders?')&&!new URL(r.url()).searchParams.get('keyword'));
  await page.locator('main form.filters').getByRole('button',{name:'重置',exact:true}).click();
  check((await resetList).status()===200,'Order filters did not reset');
  const initialProduct=(await api('products/1')).product;
  initialProduct.title=initialProduct.name.zh||initialProduct.name.en; initialProduct.familyCode=initialProduct.colorGroup;
  initialProduct.sizePrices.forEach(size=>{size.price=29.9;});
  await api('products/save-group','POST',{products:[initialProduct],versions:{[initialProduct.id]:initialProduct.version}});
  const source = (await api('orders','POST',{
    requestId:crypto.randomUUID(), userId:1, ownerAdminId:2, contactName:'Reorder QA',phone:'123456',
    country:'Germany',address:'18 Market Street',apartment:'Room 8',city:'Berlin',state:'Berlin',zip:'12345',
    contactValue:'buyer@example.test',shippingFee:12.5,note:'Keep labels and packaging\n辅料备注保留',
    labelImageUrls:['/uploads/fixture.jpg'],labelPdfUrl:'/uploads/fixture.pdf',
    items:[{productId:1,sizeCode:'M',quantity:2,unitPrice:20},{productId:1,sizeCode:'L',quantity:3,unitPrice:25}]
  })).order;
  const original = (await api(`orders/${source.id}`)).order;
  const balance = async () => (await api('inventory/1')).product.stock;
  const before = await balance();
  await page.reload();
  const sourceRow = page.locator('.el-table__row').filter({has:page.getByText(source.orderNo,{exact:true})});
  await sourceRow.getByRole('button',{name:'再来一单',exact:true}).click();
  const draft = page.getByRole('dialog',{name:`再来一单 · 来源订单 ${source.orderNo}`,exact:true});
  await draft.getByRole('textbox',{name:/收货人/}).waitFor();
  check(await draft.getByRole('textbox',{name:/收货人/}).inputValue()==='Reorder QA','Contact not copied');
  check(await draft.getByRole('textbox',{name:'备注',exact:true}).inputValue()===original.note,'Note not copied');
  check(await draft.getByRole('spinbutton',{name:'运费（USD）',exact:true}).inputValue()==='12.50','Freight not copied');
  check(await draft.getByTestId('inherited-attachments').getByRole('link').count()===2,'Attachments lost');
  check(await balance()===before,'Opening draft changed stock');
  const matrix=draft.locator('.el-table').first();
  check(await matrix.getByRole('columnheader',{name:'小计',exact:true}).count()===0,'Subtotal column returned');
  check((await draft.getByRole('heading',{name:/订单总额/}).innerText()).includes('$162.00'),'Current price not used');
  await draft.getByRole('button',{name:'已按最新价格更新 2 项',exact:true}).click();
  const comparison=page.getByTestId('reorder-price-details');
  await comparison.waitFor();
  check((await comparison.innerText()).includes('$20.00 → $29.90'),'Price comparison incorrect');
  await draft.getByRole('button',{name:'已按最新价格更新 2 项',exact:true}).click();
  await matrix.getByRole('spinbutton').first().fill('3');
  await matrix.getByRole('spinbutton').first().press('Tab');
  await draft.getByTestId('inherited-attachments').getByRole('button',{name:'移除附件',exact:true}).last().click();
  const product=(await api('products/1')).product;
  product.title=product.name.zh||product.name.en; product.familyCode=product.colorGroup;
  product.sizePrices.find(s=>s.sizeCode==='M').price=31;
  await api('products/save-group','POST',{products:[product],versions:{[product.id]:product.version}});
  const submit=async () => {
    await draft.getByRole('button',{name:'创建待付款订单',exact:true}).click();
    const response=page.waitForResponse(r=>r.url().endsWith('/api/admin/orders')&&r.request().method()==='POST');
    await page.getByRole('button',{name:'确认',exact:true}).click();
    return response;
  };
  const conflict=await submit();
  check(conflict.status()===409,'Price change did not require confirmation');
  await draft.getByText('商品价格已变化，草稿已保留，请核对最新价格后重新确认创建。',{exact:true}).waitFor();
  check(await balance()===before,'Rejected draft changed stock');
  check((await draft.getByRole('heading',{name:/订单总额/}).innerText()).includes('$195.20'),'New price not applied to draft');
  const response=await submit(); check(response.status()===200,'Reconfirmed order failed');
  const created=(await response.json()).order;
  check(created.status==='pending_payment'&&created.id!==source.id,'Not a new pending order');
  check(created.labelImageUrls.length===1&&created.labelImageUrls[0]==='/uploads/fixture.jpg','Attachment choice not saved');
  check(await balance()===before-6,'New order inventory delta incorrect');
  const unchanged=(await api(`orders/${source.id}`)).order;
  check(unchanged.note===original.note&&unchanged.totalAmount===original.totalAmount&&
    JSON.stringify(unchanged.labelImageUrls)===JSON.stringify(original.labelImageUrls)&&unchanged.version===original.version,'Source order changed');
  const detail=page.getByRole('dialog',{name:`订单详情 · ${created.orderNo}`,exact:true});
  await detail.getByRole('button',{name:'再来一单',exact:true}).waitFor();
  await detail.getByRole('button',{name:'再来一单',exact:true}).click();
  const next=page.getByRole('dialog',{name:`再来一单 · 来源订单 ${created.orderNo}`,exact:true});
  await next.getByRole('textbox',{name:/收货人/}).waitFor();
  await next.getByRole('button',{name:'取消',exact:true}).click();
  await page.getByText('当前修改尚未保存，是否放弃修改？',{exact:true}).waitFor();
  await page.getByRole('button',{name:'确认',exact:true}).click();
  await next.waitFor({state:'hidden'});
  // Mobile layout and another draft must not inherit the last draft's changes.
  await page.setViewportSize({width:430,height:920});
  await page.goto(base+'/orders');
  await page.locator('.el-table__row').filter({has:page.getByText(source.orderNo,{exact:true})})
    .getByRole('button',{name:'再来一单',exact:true}).click();
  await draft.getByRole('textbox',{name:/收货人/}).waitFor();
  check(await draft.getByTestId('inherited-attachments').getByRole('link').count()===2,'Drafts shared attachment state');
  await draft.getByTestId('order-goods-summary').scrollIntoViewIfNeeded();
  await page.screenshot({path:'output/playwright/order-reorder-mobile.png'});
  await page.setViewportSize({width:1440,height:1000});
  await draft.getByTestId('order-goods-summary').scrollIntoViewIfNeeded();
  await page.screenshot({path:'output/playwright/order-reorder-desktop.png'});
  const savingDraft=page.waitForResponse(r=>r.url().endsWith('/api/admin/orders/drafts')&&r.request().method()==='POST');
  await draft.getByRole('button',{name:'保存草稿',exact:true}).click();
  const savedResponse=await savingDraft;
  check(savedResponse.status()===200,'Reorder draft save failed');
  const saved=await savedResponse.json();
  await draft.getByText(/已保存至服务器/).waitFor();
  await draft.getByRole('button',{name:'取消',exact:true}).click();
  await draft.waitFor({state:'hidden'});
  await page.getByRole('button',{name:'我的草稿',exact:true}).click();
  const manager=page.getByRole('dialog',{name:'订单草稿',exact:true});
  await manager.locator('.el-table__row').filter({has:page.getByText(source.orderNo,{exact:true})})
    .getByRole('button',{name:'继续编辑',exact:true}).click();
  await draft.getByRole('textbox',{name:/收货人/}).waitFor();
  check(await draft.getByTestId('inherited-attachments').getByRole('link').count()===2,'Saved reorder attachments lost');
  const restored=await submit();check(restored.status()===200,'Saved reorder submission failed');
  const restoredOrder=(await restored.json()).order;
  check(restoredOrder.labelImageUrls.length===2&&await balance()===before-11,'Saved reorder contents incorrect');
  check((await api('orders/drafts')).items.every(row=>row.id!==saved.id),'Submitted reorder draft still active');
  check((await api(`orders/${source.id}`)).order.version===original.version,'Saved reorder modified source');
  await page.getByRole('dialog',{name:`订单详情 · ${restoredOrder.orderNo}`,exact:true})
    .getByRole('button',{name:'关闭',exact:true}).click();
  return {reorder:true,listAndDetailEntries:true,sourceUnchanged:true,currentPriceConflict:true,
    inheritedAttachments:true,newOrderStock:true,unsavedPrompt:true,mobile:true,savedReorder:true};
}
