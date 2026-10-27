// Run only with the shared authenticated cookie state from the isolated
// gingtto_mobile_refined_test fixture. Never log in or reseed from this check.
async (page) => {
  const base = 'http://127.0.0.1:5380';
  const fixtureDatabase = 'gingtto_mobile_refined_test';
  if (!page.url().startsWith(base + '/') || !fixtureDatabase.endsWith('_test'))
    throw new Error('Explicit local *_test fixture on port 5380 required');
  const checks = [], errors = [], shots = [], cleanup = [];
  const check = (value, name) => { if (!value) throw new Error(name); checks.push(name); };
  const errorListener = error => errors.push(error.message);
  page.on('pageerror', errorListener);
  const api = (path, method = 'GET', body) => page.evaluate(async ({path, method, body, base}) => {
    if (location.origin !== base) throw new Error('Fixture origin changed');
    const csrf = await fetch('/api/auth/csrf').then(r => r.json());
    const response = await fetch('/api/admin/' + path, {method,
      headers: {'Content-Type': 'application/json', 'X-CSRF-Token': csrf.csrfToken},
      ...(body ? {body: JSON.stringify(body)} : {})});
    const result = await response.json();
    if (!response.ok) throw new Error(path + ' [' + response.status + '] ' + (result.message || ''));
    return result;
  }, {path, method, body, base});
  const screenshot = async name => {const path = 'output/playwright/mobile-real-' + name + '.png';
    await page.screenshot({path, fullPage: false}); shots.push(path);};
  const mainEditor = () => page.locator('[data-testid="mobile-order-editor"]:visible');
  const step = async index => mainEditor().locator('.m-editor-steps button').nth(index - 1).click();
  const activeDrawer = name => page.getByRole('dialog', {name, exact: true});
  const waitCleanDrawer = async drawer => drawer.waitFor({state:'hidden'});
  const values = product => product.sizePrices.map(row => Object.fromEntries(
    ['sizeCode','stock','contractPending','pendingInspection','defectivePending','pendingInbound','temporaryInbound'].map(key=>[key,row[key] || 0])));
  const original = (await api('inventory/1')).product;
  check(original.sku === 'GT-2026-1', 'isolated fixture identity verified before writes');
  const baseline = structuredClone(original), size = original.sizePrices[0].sizeCode;
  let createdId, draftId, inventoryTouched = false, exported;
  const marker = 'Mobile Refined QA ' + Date.now();
  try {
    await page.setViewportSize({width:393,height:852});
    await page.goto(base + '/orders');
    await page.getByTestId('mobile-order-create').waitFor();
    await page.getByTestId('mobile-order-create').click();
    await mainEditor().waitFor();
    check(await mainEditor().locator('.m-editor-steps button').count() === 3, 'real order editor exposes three mobile sections');
    await page.getByTestId('mobile-order-recipient').click();
    const recipient = activeDrawer('编辑收货资料');
    await recipient.waitFor();
    const customers = (await api('orders/customers?page=1&pageSize=100')).items;
    check(customers.length > 0, 'real enabled customer options loaded');
    await recipient.getByRole('combobox').first().click();
    await page.locator('.el-select-dropdown:visible .el-select-dropdown__item').filter({hasText:customers[0].name}).first().click();
    for (const [label, value] of [['收货人',marker],['联系电话','+44 7700 900123'],['国家','United Kingdom'],['详细地址','18 Mobile Refined Road'],['邮编','SW1A 1AA']])
      await recipient.getByRole('textbox',{name:label,exact:false}).fill(value);
    await recipient.getByRole('button',{name:'应用收货资料',exact:true}).click();
    await waitCleanDrawer(recipient);
    check((await mainEditor().innerText()).includes(marker), 'secondary recipient draft applies to the real order form');
    await screenshot('order-customer');
    await step(2);
    await mainEditor().getByRole('button',{name:'＋ 添加商品',exact:true}).click();
    const picker = page.getByTestId('order-quantity-picker');
    await picker.getByTestId('picker-row-1').waitFor();
    await picker.getByTestId('picker-row-1').getByRole('button',{name:'加入',exact:true}).click();
    await picker.getByRole('button',{name:'完成',exact:true}).click();
    await picker.waitFor({state:'hidden'});
    check(await mainEditor().getByRole('spinbutton',{name:original.sku + ' ' + size + ' 数量',exact:true}).inputValue() === '0', 'zero quantity explicit join preserves a real SKU draft anchor');
    await mainEditor().getByRole('button',{name:'＋ 添加商品',exact:true}).click();
    await picker.getByTestId('picker-row-1').waitFor();
    await picker.getByRole('spinbutton',{name:original.sku + ' ' + size + ' 数量',exact:true}).fill('3');
    await picker.getByRole('button',{name:'完成',exact:true}).click();
    const quantityConfirm = activeDrawer('确认商品调整');
    await quantityConfirm.getByRole('button',{name:'确认应用',exact:true}).click();
    await picker.waitFor({state:'hidden'});
    check(await mainEditor().getByRole('spinbutton',{name:original.sku + ' ' + size + ' 数量',exact:true}).inputValue() === '3', 'picker complete synchronizes existing real-size quantity by overwrite');
    await mainEditor().getByTestId('order-unified-pricing').click();
    const pricing = page.getByRole('dialog',{name:'统一改价 · USD',exact:true});
    await pricing.getByRole('spinbutton',{name:original.sku+' 统一单价',exact:true}).fill('22.00');
    await pricing.getByRole('button',{name:'确认应用',exact:true}).click();
    await step(1); await step(2);
    check(await mainEditor().getByRole('spinbutton',{name:original.sku + ' ' + size + ' 数量',exact:true}).inputValue() === '3', 'step navigation retains applied quantities and quotes');
    await screenshot('order-products');
    await step(3);
    await mainEditor().getByRole('spinbutton').filter({hasNot:page.locator('[disabled]')}).first().fill('5.00');
    await mainEditor().getByRole('textbox',{name:'备注',exact:true}).fill(marker);
    await mainEditor().getByRole('textbox',{name:'备注',exact:true}).press('Tab');
    const editorDrawer = page.getByRole('dialog',{name:'新增订单',exact:true});
    await editorDrawer.getByRole('button',{name:'更多',exact:true}).click();
    const draftSaved = page.waitForResponse(r=>r.url().includes('/api/admin/orders/drafts')&&['POST','PUT'].includes(r.request().method()));
    await page.getByRole('button',{name:'保存草稿',exact:true}).click();
    const draftResponse=await draftSaved;check(draftResponse.ok(),'real server draft saves without creating an order');draftId=(await draftResponse.json()).id;
    const actionSheet=activeDrawer('更多操作');await actionSheet.waitFor({state:'hidden'});
    await screenshot('order-finish');
    const created = page.waitForResponse(r=>r.url().endsWith('/api/admin/orders')&&r.request().method()==='POST');
    await editorDrawer.getByRole('button',{name:'创建待付款订单',exact:true}).click();
    await page.getByRole('dialog').filter({has:page.getByRole('button',{name:'确认',exact:true})}).getByRole('button',{name:'确认',exact:true}).click();
    const creation = await created;
    check(creation.ok(),'three-section order commits through existing real endpoint');
    createdId = (await creation.json()).order.id;
    const order = (await api('orders/'+createdId)).order;
    check(order.itemCount===3 && Number(order.totalAmount)===71,'real phone amount and item count use confirmed per-order quote');
    const afterCreate = (await api('inventory/1')).product;
    check(afterCreate.sizePrices.find(r=>r.sizeCode===size).stock===baseline.sizePrices.find(r=>r.sizeCode===size).stock-3,'creating the dedicated test order deducts the exact inventory delta');
    await page.getByTestId('mobile-order-detail').waitFor();
    await screenshot('order-detail');
    await page.getByRole('button',{name:'修改订单资料',exact:true}).click();
    await mainEditor().waitFor(); await step(2);
    await mainEditor().getByRole('spinbutton',{name:original.sku+' '+size+' 数量',exact:true}).fill('4');
    await page.getByRole('button',{name:'上一步',exact:true}).last().click();
    await page.getByRole('button',{name:'取消修改',exact:true}).click();
    const leave = activeDrawer('未保存修改');
    await leave.getByRole('button',{name:'取消',exact:true}).click();
    await step(2);
    check(await mainEditor().getByRole('spinbutton',{name:original.sku+' '+size+' 数量',exact:true}).inputValue()==='4','canceling leave preserves the real edit draft');
    await step(1); await page.getByRole('button',{name:'取消修改',exact:true}).click();
    await leave.getByRole('button',{name:'确认',exact:true}).click();await leave.waitFor({state:'hidden'});await page.getByTestId('mobile-order-detail').waitFor();
    await page.setViewportSize({width:1440,height:1000});
    await page.locator('.detail-section .el-table').waitFor();
    check(await page.getByTestId('mobile-order-detail').count()===0,'desktop switches back to the original detail template');
    await page.locator('.detail-grid strong').filter({hasText:'$71.00'}).waitFor();check((await page.locator('.detail-grid strong').allTextContents()).includes('$71.00'),'desktop displays the same confirmed amount as phone');
    check((await api('orders/'+createdId)).order.itemCount===3,'discarded edit leaves committed PC item count unchanged');
    await page.getByRole('button',{name:'关闭',exact:true}).last().click();
    await page.setViewportSize({width:393,height:852});
    await page.goto(base+'/inventory?keyword='+encodeURIComponent(original.sku));
    await page.locator('.m-stock-card').first().waitFor();
    await page.locator('.m-stock-card').first().getByRole('button',{name:'登记',exact:true}).click();
    const registration = activeDrawer('登记库存');
    await page.getByTestId('mobile-inventory-registration').waitFor();
    check(await registration.getByRole('spinbutton').count()===6,'single real-size registration exposes exactly six stage controls');
    await registration.getByRole('spinbutton',{name:'待验货 '+size,exact:true}).fill(String(baseline.sizePrices[0].pendingInspection+1));
    await registration.getByRole('spinbutton',{name:'待验货 '+size,exact:true}).press('Tab');
    check(Number(await registration.getByRole('spinbutton',{name:'合同未送 '+size,exact:true}).inputValue())===baseline.sizePrices[0].contractPending-1,'real inspection-stage increase deducts contract-pending quantity');
    await registration.getByRole('spinbutton',{name:'合格 '+size,exact:true}).fill(String(baseline.sizePrices[0].pendingInbound+1));
    await registration.getByRole('spinbutton',{name:'合格 '+size,exact:true}).press('Tab');
    check(Number(await registration.getByRole('spinbutton',{name:'待验货 '+size,exact:true}).inputValue())===baseline.sizePrices[0].pendingInspection,'qualified increase consumes the transferable inspection quantity');
    if(baseline.sizePrices.length>1){await registration.locator('.m-registration-sizes button').nth(1).click();await registration.locator('.m-registration-sizes button').first().click();}
    await registration.getByRole('spinbutton',{name:'临时待入库 '+size,exact:true}).fill(String(baseline.sizePrices[0].temporaryInbound+2));
    await screenshot('inventory-registration');
    const saved = page.waitForResponse(r=>r.url().endsWith('/api/admin/inventory/1')&&r.request().method()==='PUT');
    inventoryTouched=true;
    await registration.getByRole('button',{name:'保存修改',exact:true}).click();
    const savedResponse=await saved;check(savedResponse.ok(),'first save click commits net-canceling inspection +1 then qualified +1 through real API');const savedRow=(await api('inventory/1')).product.sizePrices.find(r=>r.sizeCode===size);check(savedRow.pendingInspection===baseline.sizePrices[0].pendingInspection && savedRow.pendingInbound===baseline.sizePrices[0].pendingInbound+1,'unchanged final inspection is explicitly retained while qualified quantity increases');
    await waitCleanDrawer(registration);
    await page.getByRole('button',{name:'库存操作',exact:true}).click();
    await page.getByRole('button',{name:'批量入库 / 打回',exact:true}).click();
    await page.locator('.m-stock-card').first().locator('.m-stock-head').click();
    await page.getByRole('button',{name:'批量处理',exact:true}).click();
    await page.getByRole('button',{name:'临时入库',exact:true}).click();
    const batch = page.getByRole('dialog').filter({has:page.getByRole('button',{name:'确认入库',exact:true})});
    const received = page.waitForResponse(r=>r.url().includes('/api/admin/inventory/batch/temporary/receive')&&r.request().method()==='POST');
    await batch.getByRole('button',{name:'确认入库',exact:true}).click();
    check((await received).ok(),'mobile selected-product temporary inbound uses the existing atomic endpoint');
    const afterBatch = (await api('inventory/1')).product;
    check(afterBatch.sizePrices[0].temporaryInbound===0,'temporary inbound clears only its saved source stage');
    await page.getByRole('button',{name:'库存操作',exact:true}).click();
    const download=page.waitForEvent('download');await page.getByRole('button',{name:'导出库存',exact:true}).click();
    exported=await download;check(exported.suggestedFilename().endsWith('.xlsx')&&!(await exported.failure()),'real inventory export downloads the original XLSX format');
    await exported.saveAs('output/playwright/mobile-real-inventory.xlsx');
    await page.goto(base+'/orders?orderId='+createdId);
    await page.getByTestId('mobile-order-detail').waitFor();
    await page.getByRole('button',{name:'刷新',exact:true}).click();
    const refreshed=(await api('orders/'+createdId)).order;
    check(refreshed.items[0].quantity===3&&refreshed.items[0].currentStock===afterBatch.sizePrices[0].stock,'order refresh shows latest real inventory without changing purchased quantity');
    check(errors.length===0,'no JavaScript errors in real mobile order and stock flows');
  } finally {
    // Only this test's dedicated order is canceled. Original fixture orders stay intact.
    if(createdId){try{const current=(await api('orders/'+createdId)).order;
      if(current.status!=='cancelled')await api('orders/'+createdId,'PUT',{status:'cancelled',cancelNote:marker+' cleanup',version:current.version});
      cleanup.push('dedicated test order canceled');
    }catch(error){cleanup.push('ORDER CLEANUP FAILED: '+error.message);}}
    if(draftId && !createdId){try{await api('orders/drafts/'+draftId,'DELETE',{version:(await api('orders/drafts/'+draftId)).version});cleanup.push('dedicated draft removed');}catch(error){cleanup.push('DRAFT CLEANUP FAILED: '+error.message);}}
    if(inventoryTouched){try{const current=(await api('inventory/1')).product;
      const fields={stock:'sizeStocks',contractPending:'contractPendingBySize',pendingInspection:'pendingInspectionBySize',defectivePending:'defectivePendingBySize',pendingInbound:'pendingInboundBySize',temporaryInbound:'temporaryInboundBySize'};
      const body={version:current.version};for(const [field,key]of Object.entries(fields))body[key]=Object.fromEntries(baseline.sizePrices.map(row=>[row.sizeCode,row[field]||0]));
      await api('inventory/1','PUT',body);const restored=(await api('inventory/1')).product;
      check(JSON.stringify(values(restored))===JSON.stringify(values(baseline)),'base product six-stage values restored after isolated checks');cleanup.push('base product quantities restored');
    }catch(error){cleanup.push('INVENTORY CLEANUP FAILED: '+error.message);}}
    page.off('pageerror',errorListener);
  }
  check(!cleanup.some(value=>value.includes('FAILED')),'test fixture cleanup completed');
  return {passed:true,fixtureDatabase,checkCount:checks.length,checks,errors,createdId,cleanup,screenshots:shots};
}
