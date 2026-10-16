// UI regressions run only against the guarded, synthetic *_test fixture.
async (page) => {
  const base = 'http://127.0.0.1:5360';
  if (!page.url().startsWith(base + '/')) throw new Error('Isolated fixture required');
  const check = (ok, message) => { if (!ok) throw new Error(message); };
  const api = (path, method = 'GET', body) => page.evaluate(async ({path, method, body}) => {
    const response = await fetch('/api/admin/' + path, {
      method, headers: {...(await fetch('/api/auth/csrf').then(r=>r.json()).then(d=>({'X-CSRF-Token':d.csrfToken}))),
        'Content-Type': 'application/json'}, ...(body ? {body: JSON.stringify(body)} : {}),
    });
    if (!response.ok) throw new Error('Fixture API ' + path + ': ' + response.status);
    return response.json();
  }, {path, method, body});
  const login = async role => {
    await page.goto(base + '/orders');
    await page.locator('.profile-button').click();
    await page.getByRole('menuitem', {name: '退出登录', exact: true}).click();
    await page.waitForURL(url => url.pathname === '/login');
    await page.getByRole('textbox', {name: '账号 / 邮箱'}).fill(role + '@gingtto.test');
    await page.getByRole('textbox', {name: '密码', exact: true}).fill('Workbench-Test-2026');
    await page.getByRole('button', {name: '登录工作台', exact: true}).click();
    await page.waitForURL(url => url.pathname !== '/login');
    await page.goto(base + '/orders');
    await page.getByRole('button', {name: '订单详情', exact: true}).first().waitFor();
  };
  const query = async keyword => {
    await page.getByRole('textbox', {name: '订单查询关键词'}).fill(keyword);
    const result = page.waitForResponse(r => r.url().includes('/api/admin/orders?') &&
      new URL(r.url()).searchParams.get('keyword') === keyword);
    await page.locator('main form.filters').getByRole('button', {name: '查询', exact: true}).click();
    check((await result).status() === 200, 'Order search failed');
  };
  const balance = async () => {
    const p = (await api('inventory/1')).product;
    return JSON.stringify({stock: p.stock, sizes: p.sizePrices.map(s => [s.sizeCode, s.stock])});
  };
  const transition = async (id, status) => {
    const order = (await api(`orders/${id}`)).order;
    await api(`orders/${id}`, 'PUT', {version: order.version, status,
      shippingFee: order.shippingFee, trackingNo: order.trackingNo, paymentLink: order.paymentLink});
  };
  const settleDrawer = () => page.waitForFunction(() => [...document.querySelectorAll('.el-drawer')]
    .some(el => el.offsetWidth && el.getBoundingClientRect().right <= window.innerWidth + 1));
  await page.setViewportSize({width: 1920, height: 1080});
  await login('admin');
  const assertDatePosition = async () => {
    const headers = (await page.locator('main > section.panel > .el-table').getByRole('columnheader')
      .allTextContents()).map(t => t.trim());
    check(headers.indexOf('下单时间') === headers.indexOf('订单号') + 1, 'Order date is not immediately after order number');
  };
  await assertDatePosition();
  // Even old saved column preferences must not undo the new column order.
  await page.evaluate(() => {
    const key = Object.keys(localStorage).find(k => k.startsWith('gingtto-table:') && k.endsWith(':orders'));
    if (!key) throw new Error('Order table preferences missing');
    const settings = JSON.parse(localStorage.getItem(key));
    settings.visible = [...settings.visible.filter(p => p !== 'createdAt'), 'createdAt'];
    localStorage.setItem(key, JSON.stringify(settings));
  });
  await page.reload();
  await page.getByRole('button', {name: '订单详情', exact: true}).first().waitFor();
  await assertDatePosition();
  check((await page.getByRole('textbox', {name: '订单查询关键词'}).getAttribute('placeholder'))
    .includes('客户名称'), 'Customer search hint missing');
  const updateDraftWeight = async (size, grams) => {
    const product = (await api('products/1')).product;
    product.title=product.name.zh || product.name.en;product.familyCode=product.colorGroup;
    product.sizePrices.find(s=>s.sizeCode===size).weightGrams=grams;
    await api('products/save-group','POST',{products:[product],versions:{[product.id]:product.version}});
  };
  await updateDraftWeight('M',350);await updateDraftWeight('L',null);
  await page.getByRole('button', {name: '＋ 新增订单', exact: true}).click();
  const editor = page.getByRole('dialog', {name: '新增订单', exact: true});
  check(await editor.getByText('尚未保存为草稿；可填写一部分后点击“保存草稿”，稍后从“我的草稿”继续。',{exact:true}).count()===0,'Initial draft help remains');
  check(await editor.locator('.customer-template-bar > small').count()===0,'Template help remains in the editor');
  await editor.getByRole('combobox', {name: /商城客户/}).click();
  await page.getByRole('option', {name: 'Alex Morgan · Northline Apparel', exact: true}).click();
  const contact = 'UI-QA Customer Name ' + Date.now();
  for (const [name, value] of [['收货人', contact], ['联系电话', '123456'],
    ['国家', 'Germany'], ['详细地址', 'Fixture address']]) {
    await editor.getByRole('textbox', {name: new RegExp(name)}).fill(value);
  }
  await editor.getByRole('button', {name: '＋ 添加商品', exact: true}).click();
  const picker = page.getByRole('dialog', {name: '选择商品', exact: true});
  const picked = picker.locator('.el-table__row').filter({has: page.getByText('GT-2026-1', {exact: true})});
  // Element Plus hides the native checkbox input; click its visible label.
  await picked.locator('.el-checkbox').click();
  await picker.getByRole('button', {name: '加入所选并完成', exact: true}).click();
  await picker.waitFor({state: 'hidden'});
  const matrix = editor.locator('.el-table').nth(0);
  await matrix.getByRole('spinbutton').first().waitFor();
  const sizes = (await matrix.getByRole('columnheader').allTextContents()).map(t => t.trim());
  for (const [size, count] of [['M', 2], ['L', 1]]) {
    const input = matrix.getByRole('spinbutton').nth(sizes.indexOf(size) - 1);
    await input.fill(String(count)); await input.press('Tab');
  }
  await editor.getByRole('spinbutton', {name: '运费（USD）', exact: true}).fill('12.5');
  await editor.getByRole('spinbutton', {name: '运费（USD）', exact: true}).press('Tab');
  check(await matrix.getByRole('columnheader', {name: '小计', exact: true}).count() === 0, 'Matrix subtotal remains');
  check(await matrix.locator('.order-size-price').count() === 0 && !(await matrix.innerText()).includes('/ 件'), 'Matrix unit prices remain');
  check((await matrix.innerText()).includes('3 件'), 'Per-product item count removed');
  const summary = editor.locator('[data-testid="order-goods-summary"]');
  const weightSummary = summary.locator('[data-testid="order-draft-weight"]');
  const quoteControls=summary.locator('.order-quote-controls');
  const quoteBoxes=await quoteControls.locator('.el-form-item').evaluateAll(items=>items.map(item=>{
    const box=item.querySelector('.el-select__wrapper,.el-input__wrapper').getBoundingClientRect();
    return {top:box.top,height:box.height};
  }));
  check(quoteBoxes.length===1&&quoteBoxes.every(box=>Math.abs(box.height-32)<1&&Math.abs(box.top-quoteBoxes[0].top)<1),'Freight control is not 32px');
  check(await editor.getByRole('combobox',{name:'订单币种',exact:true}).count()===0 && await editor.getByRole('spinbutton',{name:'本单汇率',exact:true}).count()===0,'Currency switch or per-order FX editor remains');
  check(await quoteControls.locator('.el-input-number__increase,.el-input-number__decrease').count()===0,'Freight stepper buttons remain');
  check(await weightSummary.locator('.order-weight-caption').count()===0,'Redundant weight caption remains');
  check((await summary.innerText()).includes('$89.70'), 'Goods amount calculated incorrectly');
  check(await summary.evaluate(el => el.previousElementSibling?.classList.contains('el-table')), 'Goods amount not below matrix');
  check(await editor.getByRole('columnheader',{name:'库存核对 / SKU',exact:true}).count()===0,'Separate stock table remains');
  const currentSizes=(await api('inventory/1')).product.sizePrices;
  for(const [size,qty] of [['M',2],['L',1]]) {
    const stock=currentSizes.find(item=>item.sizeCode===size).stock;
    check((await editor.getByTestId(`size-stock-1-${size}`).innerText()).includes(`库存 ${stock-qty}`),'Inline stock delta incorrect');
  }
  const firstStock=currentSizes.find(item=>item.sizeCode===sizes[1]).stock;
  const firstQuantity=matrix.getByRole('spinbutton').first();
  const oldQuantity=await firstQuantity.inputValue();
  await firstQuantity.fill(String(Math.max(0,firstStock)+3)); await firstQuantity.press('Tab');
  const shortage=editor.getByTestId(`size-stock-1-${sizes[1]}`);
  check((await shortage.innerText()).includes('欠货') && (await shortage.getAttribute('class')).includes('is-shortage'),'Shortage not highlighted');
  check(await editor.getByText('保存后存在欠货，仍可提交。入库时会抵减欠货余额。',{exact:true}).count()===0,'Redundant shortage banner remains');
  await firstQuantity.fill('0'); await firstQuantity.press('Tab');
  check((await shortage.innerText()).includes(`库存 ${firstStock}`),'Zero quantity did not restore preview');
  await firstQuantity.fill(oldQuantity); await firstQuantity.press('Tab');
  check((await editor.getByRole('heading', {name: /订单总额/}).innerText()).includes('$102.20'), 'Shipping or total changed');
  check(await editor.getByText('商品金额', {exact: true}).count() === 1, 'Duplicate goods amount remains at footer');
  check(await summary.getByRole('spinbutton', {name:'运费（USD）',exact:true}).count() === 1 &&
    await editor.getByRole('spinbutton', {name:'运费（USD）',exact:true}).count() === 1, 'Shipping is duplicated or outside goods summary');
  check(await summary.getByRole('heading', {name:/订单总额/}).count() === 1, 'Order total outside goods summary');
  await weightSummary.getByText('已知 0.700 kg',{exact:true}).waitFor();
  const missingHint = () => weightSummary.getByRole('button',{name:/查看\d+件未设置重量的商品/});
  const weightDetails = page.locator('[data-testid="order-weight-details"]');
  const settleWeightDetails = () => page.waitForFunction(() => [...document.querySelectorAll('[data-testid="order-weight-details"]')]
    .some(el=>el.offsetWidth && getComputedStyle(el.closest('.el-popper')).opacity==='1'));
  check((await missingHint().innerText()).includes('1 件未设置'), 'Missing quantity hint not next to total weight');
  check(await weightSummary.locator('.order-weight-total .order-weight-hint').count()===1, 'Missing hint not attached to total value');
  check(!(await weightSummary.innerText()).includes('GT-2026-1 · L') &&
    await weightSummary.locator('.order-weight-warning').count()===0, 'Large inline warning remains');
  check(!(await weightDetails.isVisible()), 'Missing details should be collapsed by default');
  await missingHint().click();
  await weightDetails.waitFor();
  check((await weightDetails.innerText()).includes('1 件商品未设置重量') &&
    (await weightDetails.innerText()).includes('GT-2026-1 · L'), 'Missing size not identified in popover');
  await summary.scrollIntoViewIfNeeded(); await settleDrawer();
  await settleWeightDetails();
  await page.waitForFunction(() => !document.querySelector('.el-message'));
  await page.screenshot({path: 'output/playwright/order-editor-weight-popover.png'});
  await missingHint().click();
  await weightDetails.waitFor({state:'hidden'});
  await updateDraftWeight('L',380);
  await weightSummary.getByRole('button',{name:'刷新重量',exact:true}).click();
  await weightSummary.getByText('1.080 kg',{exact:true}).waitFor();
  check(await missingHint().count()===0,'Complete weight still shows warning');
  await updateDraftWeight('L',null);
  await updateDraftWeight('M',null);
  await weightSummary.getByRole('button',{name:'刷新重量',exact:true}).click();
  await weightSummary.getByText('未设置',{exact:true}).waitFor();
  check(await weightSummary.locator('.order-weight-value').evaluate(el => {
    const style=getComputedStyle(el);
    return parseFloat(style.fontSize)<=13 && Number(style.fontWeight)<=400;
  }), 'Unset weight is oversized or bold');
  check((await missingHint().innerText()).includes('3 件未设置'), 'All-missing count incorrect');
  await page.setViewportSize({width:390,height:844});
  await weightSummary.scrollIntoViewIfNeeded(); await settleDrawer();
  // Drawer width transitions can still be running after a viewport resize.
  // Wait for the exact layout assertion rather than sampling one animation frame.
  await page.waitForFunction(() => {
    const el=document.querySelector('[data-testid="order-goods-summary"] .order-quote-controls');
    return el && [...el.querySelectorAll('.el-select__wrapper,.el-input-number')].every(input=>{
      const box=input.getBoundingClientRect();
      return box.left>=-1 && box.right<=innerWidth+1 && Math.abs(box.height-32)<1;
    });
  });
  check(await quoteControls.evaluate(el=>[...el.querySelectorAll('.el-select__wrapper,.el-input-number')].every(input=>{
    const box=input.getBoundingClientRect();return box.left>=-1&&box.right<=innerWidth+1&&Math.abs(box.height-32)<1;
  })),'Quote controls overflow or change height on mobile');
  await page.waitForFunction(() => { const el=document.querySelector('[data-testid=order-draft-weight]'); if(!el)return false; const box=el.getBoundingClientRect(); return box.left>=-1 && box.right<=innerWidth+1 && el.scrollWidth<=el.clientWidth+1; });
  check(await weightSummary.evaluate(el=>el.getBoundingClientRect().left>=-1 &&
    el.getBoundingClientRect().right<=window.innerWidth+1 && el.scrollWidth<=el.clientWidth+1), 'Weight area overflows narrow drawer');
  await missingHint().click(); await weightDetails.waitFor();
  await settleWeightDetails();
  check(await weightDetails.evaluate(el => {
    const box=el.closest('.el-popper').getBoundingClientRect();
    return box.left>=-1 && box.right<=window.innerWidth+1;
  }), 'Weight details popover overflows narrow viewport');
  await page.screenshot({path:'output/playwright/order-editor-weight-mobile.png'});
  await missingHint().click(); await weightDetails.waitFor({state:'hidden'});
  await page.setViewportSize({width:1920,height:1080});
  await updateDraftWeight('M',350);
  await weightSummary.getByRole('button',{name:'刷新重量',exact:true}).click();
  await weightSummary.getByText('已知 0.700 kg',{exact:true}).waitFor();
  await page.route('**/api/admin/orders/weights/preview',route=>route.abort('failed'));
  await weightSummary.getByRole('button',{name:'刷新重量',exact:true}).click();
  await weightSummary.getByText('暂未取得重量',{exact:true}).waitFor();
  await weightSummary.getByRole('button',{name:'查看重量计算异常',exact:true}).click();
  await weightDetails.waitFor();
  check((await weightDetails.innerText()).includes('不影响保存订单'), 'Weight network error details missing');
  await weightSummary.getByRole('button',{name:'查看重量计算异常',exact:true}).click();
  await weightDetails.waitFor({state:'hidden'});
  await page.unroute('**/api/admin/orders/weights/preview');
  await weightSummary.getByRole('button',{name:'刷新重量',exact:true}).click();
  await weightSummary.getByText('已知 0.700 kg',{exact:true}).waitFor();
  await summary.scrollIntoViewIfNeeded(); await settleDrawer();
  await page.waitForFunction(() => !document.querySelector('.el-message'));
  await page.screenshot({path: 'output/playwright/order-editor-amount-summary.png'});
  const createdResponse = page.waitForResponse(r => r.url().endsWith('/api/admin/orders') && r.request().method() === 'POST');
  await editor.getByRole('button', {name: '创建待付款订单', exact: true}).click();
  await page.getByRole('dialog', {name: '确认操作', exact: true}).getByRole('button', {name: '确认', exact: true}).click();
  const created = await createdResponse;
  check(created.status() === 200, 'UI order creation failed');
  const id = (await created.json()).order.id;
  const order = (await api(`orders/${id}`)).order;
  check(order.totalAmount === 102.2 && order.shippingFee === 12.5 && order.itemCount === 3, 'Saved order amount/count differs from UI');
  check(order.items.every(i => i.unitPrice === 29.9), 'Hidden unit prices were lost');
  await page.getByRole('dialog', {name: '订单详情 · ' + order.orderNo, exact: true})
    .getByRole('button', {name: '关闭', exact: true}).click();
  await query(contact);
  await page.getByRole('button', {name: order.orderNo, exact: true}).waitFor();
  check(await page.getByRole('button', {name: '订单详情', exact: true}).count() === 1, 'Customer name query did not isolate order');
  await page.screenshot({path: 'output/playwright/orders-customer-search-and-date.png'});
  const savedBalance = await balance();
  await transition(id, 'completed');
  await page.reload();
  const statusButton = page.getByRole('button', {name: `修改订单 ${order.orderNo} 状态`, exact: true});
  await statusButton.click();
  for (const name of ['待付款', '已配货', '已付款', '已发货', '已取消']) {
    check(await page.getByRole('menuitem', {name, exact: true}).isEnabled(), 'Completed status target disabled: ' + name);
  }
  const change = page.waitForResponse(r => r.url().endsWith(`/api/admin/orders/${id}`) && r.request().method() === 'PUT');
  await page.getByRole('menuitem', {name: '已付款', exact: true}).click();
  await page.getByRole('dialog', {name: '修改订单状态', exact: true}).getByRole('button', {name: '确认', exact: true}).click();
  check((await change).status() === 200, 'Completed list status update failed');
  check((await api(`orders/${id}`)).order.status === 'paid' && await balance() === savedBalance, 'Reopen unexpectedly changed stock');
  await transition(id, 'completed'); await page.reload();
  await page.getByRole('button', {name: '订单详情', exact: true}).click();
  const detail = page.getByRole('dialog', {name: '订单详情 · ' + order.orderNo, exact: true});
  await detail.getByRole('button', {name: '修改订单资料', exact: true}).click();
  await detail.locator('.el-form-item').filter({has: page.getByRole('combobox', {name: '订单状态', exact: true})})
    .locator('.el-select').click();
  for (const name of ['待付款', '已配货', '已付款', '已发货', '已取消']) {
    check(!(await page.getByRole('option', {name, exact: true}).getAttribute('class')).includes('is-disabled'), 'Completed editor option disabled');
  }
  await page.getByRole('option', {name: '已配货', exact: true}).click();
  check(await detail.getByRole('columnheader', {name: '小计', exact: true}).count() === 0, 'Edit matrix still has subtotal');
  check(await detail.locator('.order-size-price').count() === 0, 'Edit matrix still has unit prices');
  const editResponse = page.waitForResponse(r => r.url().endsWith(`/api/admin/orders/${id}/details`) && r.request().method() === 'PUT');
  await detail.getByRole('button', {name: '保存修改', exact: true}).click();
  await page.getByRole('dialog', {name: '确认操作', exact: true}).getByRole('button', {name: '确认', exact: true}).click();
  check((await editResponse).status() === 200, 'Completed details save failed');
  check((await api(`orders/${id}`)).order.status === 'allocated' && await balance() === savedBalance, 'Details reopening changed stock');
  await detail.getByRole('button', {name: '修改订单资料', exact: true}).waitFor();
  await detail.getByRole('button', {name: '关闭', exact: true}).click();
  const history = (await api(`orders/${id}/operations`)).items;
  check(history.some(h => h.changes.some(c => c.field === 'status' && c.before === 'completed' && c.after === 'allocated')), 'Reopen operation not recorded');
  await transition(id, 'cancelled');
  check(await balance() !== savedBalance, 'Cancellation did not restore inventory');
  await transition(id, 'paid');
  check(await balance() === savedBalance, 'Restoring cancelled order did not re-deduct inventory exactly');
  await transition(id, 'completed');
  await login('warehouse'); await query(contact);
  check(await page.getByRole('columnheader', {name: '商品金额', exact: true}).count() === 0, 'Warehouse list exposes money');
  await page.getByRole('button', {name: '订单详情', exact: true}).click();
  const warehouseDetail = page.getByRole('dialog', {name: '订单详情 · ' + order.orderNo, exact: true});
  await warehouseDetail.getByRole('button', {name: '修改订单状态', exact: true}).click();
  await warehouseDetail.locator('.el-form-item').filter({has: page.getByRole('combobox', {name: /订单状态/})})
    .locator('.el-select').click();
  check(!(await page.getByRole('option', {name: '已付款', exact: true}).getAttribute('class')).includes('is-disabled'), 'Warehouse completed status option disabled');
  await page.getByRole('option', {name: '已付款', exact: true}).click();
  const warehouseSave = page.waitForResponse(r => r.url().endsWith(`/api/admin/orders/${id}`) && r.request().method() === 'PUT');
  await warehouseDetail.getByRole('button', {name: '保存修改', exact: true}).click();
  const result = await warehouseSave;
  check(result.status() === 200, 'Warehouse completed reopen failed');
  const redacted = (await result.json()).order;
  check(!['totalAmount', 'shippingFee', 'paymentLink'].some(k => k in redacted), 'Warehouse update exposes money');
  check(redacted.items.every(i => !('unitPrice' in i) && !('totalPrice' in i)), 'Warehouse items expose money');
  check(await balance() === savedBalance, 'Warehouse reopening changed stock');
  await warehouseDetail.getByRole('button', {name: '修改订单状态', exact: true}).waitFor();
  await warehouseDetail.getByRole('button', {name: '关闭', exact: true}).click();
  return {dateAfterOrderNo: true,oldColumnPreferences: true,customerSearch: true,
    noSizeUnitPrice: true,noProductSubtotal: true,goodsSummaryPosition: true,
    usdOnlyEditor: true,shippingNoStepper: true,compactEditorHints: true,
    itemCountsPreserved: true,amountsAndShippingPreserved: true,draftWeightAndMissingWarning: true,
    compactWeightHint: true,missingDetailsPopover: true,unsetWeightSmallFont: true,narrowWeightSummary: true,
    currentWeightRefresh: true,weightFailureRecovery: true,completedListReopen: true,
    completedEditorReopen: true,cancelRestoreStock: true,operationRecorded: true,warehouseReopenWithoutMoney: true};
}
