// Use admin-mobile-browser-fixture.py with an explicit local *_test database.
async (page) => {
  const base = 'http://127.0.0.1:5380';
  if (!page.url().startsWith(base + '/')) throw new Error('Isolated iPhone UI fixture required');
  const check = (value, message) => { if (!value) throw new Error(message); };
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  const visit = async path => { await page.goto(base + path); await page.waitForLoadState('networkidle'); };
  await page.setViewportSize({width:393,height:852});
  await visit('/orders');
  await page.getByRole('button', {name:'更多',exact:true}).click();
  await page.getByRole('button',{name:'客户模板',exact:true}).waitFor();
  check(await page.getByRole('button',{name:'客户模板',exact:true}).isVisible(), 'Customer templates inaccessible');
  check(await page.getByRole('button',{name:'我的草稿',exact:true}).isVisible(), 'Drafts inaccessible');
  await page.getByRole('button',{name:'导出订单 ▾',exact:true}).click();
  const orderDownload = page.waitForEvent('download');
  await page.getByRole('menuitem').filter({hasText:'合并表格'}).click();
  check(!(await (await orderDownload).failure()), 'Order export in More failed');
  await page.keyboard.press('Escape');
  await page.locator('.mobile-record-select').first().click();
  let reads = 0;
  const listener = request => { if(request.url().includes('/api/admin/orders?')) reads++; };
  page.on('request',listener);
  await page.setViewportSize({width:1440,height:1000});
  await page.waitForFunction(() => document.querySelectorAll('main .el-table__row .el-checkbox.is-checked').length === 1);
  await page.setViewportSize({width:393,height:852});
  check(await page.getByRole('checkbox',{name:'选择第 1 项',exact:true}).isChecked(), 'Selection lost');
  check(reads === 0, 'Resize issued a query'); page.off('request',listener);
  await page.getByRole('button',{name:'清空选择',exact:true}).click();
  await page.getByRole('button',{name:'＋ 新增订单',exact:true}).click();
  const editor = page.getByRole('dialog',{name:'新增订单',exact:true});
  await editor.getByRole('button',{name:'＋ 添加商品',exact:true}).click();
  const picker = page.getByRole('dialog',{name:'选择商品',exact:true});
  await picker.locator('.picker-product-row').first().waitFor();
  check(await picker.evaluate(el => el.getBoundingClientRect().width <= innerWidth), 'Picker exceeds phone width');
  await picker.getByRole('button',{name:'加入',exact:true}).first().click();
  await picker.getByRole('button',{name:'完成',exact:true}).click();
  await picker.waitFor({state:'hidden'});
  check(await editor.locator('.order-product-row').count() === 1, 'Zero quantity join missing');
  const quantity = editor.locator('.order-product-row').getByRole('spinbutton').first();
  await quantity.fill('2'); await quantity.press('Tab');
  check(await quantity.inputValue() === '2', 'Quantity input not editable');
  await editor.getByRole('button',{name:'取消',exact:true}).click();
  const dirty = page.getByRole('dialog',{name:'未保存修改',exact:true});
  await dirty.getByRole('button',{name:'取消',exact:true}).click();
  check(await quantity.inputValue() === '2','Cancelled dismissal lost quantity');
  await editor.getByRole('button',{name:'取消',exact:true}).click();
  await dirty.getByRole('button',{name:'确认',exact:true}).click();
  await visit('/inventory');
  check(await page.locator('.inventory-overview .metric:visible').count() === 2,'Initial inventory overview too large');
  await page.getByRole('button',{name:'查看全部库存阶段',exact:false}).click();
  await page.locator('.inventory-overview .metric').last().waitFor();
  check(await page.locator('.inventory-overview .metric:visible').count() === 10,'Inventory stages hidden');
  await page.getByRole('button',{name:'收起库存概览',exact:false}).click();
  await page.getByRole('button',{name:'列表操作',exact:true}).click();
  await page.getByRole('button',{name:'全部勾选',exact:true}).click();
  check(await page.locator('.mobile-record-select.is-checked').count() === 3,'Page selection not preserved');
  await page.getByRole('button',{name:'列表操作',exact:true}).click();
  await page.getByRole('button',{name:'清空勾选',exact:true}).click();
  await page.getByRole('button',{name:'登记数量',exact:true}).first().click();
  const registration = page.getByRole('dialog',{name:'登记库存与到货进度',exact:true});
  await registration.getByRole('spinbutton',{name:'现货余额 M',exact:true}).waitFor();
  for(const label of ['现货余额','合同未送','待验货','次品','合格','临时待入库'])
    check(await registration.getByRole('spinbutton',{name:label+' M',exact:true}).isVisible(),'Missing stage '+label);
  await registration.getByRole('button',{name:'取消',exact:true}).click();
  await visit('/finance');
  await page.getByRole('button',{name:'商品成本',exact:true}).click();
  await page.getByText('汇率与导入导出',{exact:false}).click();
  const costDownload = page.waitForEvent('download');
  await page.getByRole('button',{name:'导出成本表',exact:true}).click();
  check(!(await (await costDownload).failure()), 'Finance download inaccessible');
  await page.getByRole('button',{name:'导入成本表',exact:true}).click();
  const importer = page.getByRole('dialog');
  await importer.getByRole('button',{name:'关闭此对话框',exact:true}).click();
  const routes=['/dashboard','/orders','/inventory','/finance','/products','/contracts','/presale','/categories','/admin-users','/store-accounts','/audit-logs','/api-integrations','/products/1/edit'];
  let layoutChecks = 0;
  for(const width of [360,393,430,768,1024,1440]) {
    await page.setViewportSize({width,height:852});
    for(const path of routes) {
      await visit(path);
      check(await page.evaluate(()=>document.documentElement.scrollWidth <= innerWidth+1),`Overflow ${path} at ${width}`);
      layoutChecks++;
    }
  }
  check(!errors.length,'Browser errors: '+errors.join('; '));
  await page.setViewportSize({width:393,height:852});
  for(const name of ['dashboard','orders','inventory','finance']) {
    await visit('/'+name);
    if(name==='finance') {
      await page.getByRole('button',{name:'商品成本',exact:true}).click();
      await page.locator('.style-cost-table tbody tr').first().waitFor();
      await page.locator('.finance-panel .el-loading-mask').waitFor({state:'hidden'});
    }
    await page.screenshot({path:`output/playwright/iphone16-${name}.png`,animations:'disabled'});
  }
  return {iphone16:true, layoutChecks, orderExport:true, selectionAndResize:true, pickerAndDirtyConfirmation:true,
    inventorySummaryAndBatchTools:true, allSixInventoryInputs:true, financeToolsAndDownload:true, uncaughtErrors:errors};
}
