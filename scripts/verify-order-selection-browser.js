// Synthetic local *_test fixture only. Never run against a manual/production page.
async (page) => {
  const base='http://127.0.0.1:5360';
  if(!page.url().startsWith(base+'/'))throw new Error('Isolated fixture required');
  page.removeAllListeners('dialog');page.on('dialog',d=>d.accept());
  const check=(v,m)=>{if(!v)throw new Error(m);};
  const api=(path,method='GET',body)=>page.evaluate(async({path,method,body})=>{
    const csrf=await fetch('/api/auth/csrf').then(r=>r.json());
    const r=await fetch('/api/admin/'+path,{method,headers:{'Content-Type':'application/json','X-CSRF-Token':csrf.csrfToken},...(body?{body:JSON.stringify(body)}:{})});
    if(!r.ok)throw new Error('Fixture API '+path+': '+r.status);return r.json();
  },{path,method,body});
  const picker=()=>page.getByRole('dialog',{name:'选择商品',exact:true});
  const input=(sku,size)=>picker().getByRole('spinbutton',{name:`${sku} ${size} 数量`,exact:true});
  const row=sku=>picker().locator('.picker-product-row').filter({has:page.getByText(sku,{exact:true})});
  const join=sku=>row(sku).getByRole('button',{name:'加入',exact:true}).click();
  const finish=()=>picker().getByRole('button',{name:'完成',exact:true}).click();
  const pending=n=>picker().getByRole('status').filter({hasText:`待处理 ${n} 个颜色 SKU`}).waitFor();
  const confirmation=()=>page.getByRole('dialog',{name:'确认商品调整',exact:true});
  const approve=async()=>{await confirmation().getByRole('button',{name:'确认应用',exact:true}).click();await confirmation().waitFor({state:'hidden'});};
  const settled=()=>page.waitForFunction(()=>!document.querySelector('.order-quantity-picker .el-loading-mask'));
  const query=async keyword=>{
    await picker().getByRole('textbox',{name:'选品关键词',exact:true}).fill(keyword);
    const response=page.waitForResponse(r=>r.url().includes('/api/admin/products?')&&new URL(r.url()).searchParams.get('keyword')===keyword&&!new URL(r.url()).searchParams.has('ids'));
    await picker().getByRole('button',{name:'查询',exact:true}).click();check((await response).status()===200,'Search failed');await settled();
  };
  let orderWrites=0;
  const count=r=>{if(/\/api\/admin\/orders(?:\/\d+)?$/.test(r.url())&&['POST','PUT'].includes(r.method()))orderWrites++;};
  page.on('request',count);
  await page.setViewportSize({width:1440,height:1000});await page.goto(base+'/orders');
  await page.getByRole('button',{name:'＋ 新增订单',exact:true}).click();
  const editor=page.getByRole('dialog',{name:'新增订单',exact:true});
  const main=()=>editor.getByTestId('order-product-list');
  const mainInput=(sku,size)=>main().getByRole('spinbutton',{name:`${sku} ${size} 数量`,exact:true});
  const open=async()=>{await editor.getByRole('button',{name:'＋ 添加商品',exact:true}).click();await picker().locator('.picker-product-row').first().waitFor();await settled();};
  await open();
  check(await picker().getByRole('checkbox').count()===0,'Selection requires checkboxes');
  check(JSON.stringify(await picker().locator('.picker-list-header > span').allTextContents())===JSON.stringify(['颜色 SKU','尺码及数量','操作']),'Shared size headers remain');
  check(!(await picker().innerText()).includes('库存'),'Picker shows stock');
  check(await picker().getByText('总件数',{exact:true}).count()===0,'Picker shows totals');
  check(await picker().getByRole('button',{name:'撤销',exact:true}).count()===0,'Extra row action remains');
  check(await picker().locator('input[type=number]').count()===0,'Spinner controls remain');
  await query('GT-2026');
  await input('GT-2026-1','M').fill('1.5');await join('GT-2026-1');
  await picker().getByRole('alert').filter({hasText:'数量须为非负整数'}).waitFor();
  check(await main().locator('.order-product-row').count()===0,'Invalid selection partially applied');
  await input('GT-2026-1','M').fill('2');await input('GT-2026-1','M').press('Tab');
  check(await input('GT-2026-1','L').evaluate(el=>el===document.activeElement),'Tab order incorrect');
  await input('GT-2026-1','L').fill('1');
  check(await input('GT-2026-1','M').evaluate(el=>el.getBoundingClientRect().height)===32,'Input not 32px');
  await join('GT-2026-1');await pending(0);
  check(await row('GT-2026-1').getByRole('button',{name:'加入',exact:true}).isDisabled(),'Unchanged joined row can duplicate');
  // Explicit zero-only join must create an editable row in the page, without inventory writes.
  await join('GT-2026-2');await mainInput('GT-2026-2','M').waitFor();await pending(0);
  check(await main().locator('.order-product-row').count()===2,'Zero-only SKU not joined');
  check(await mainInput('GT-2026-2','M').inputValue()==='0','Zero-only row contains nonzero quantity');
  await finish();await picker().waitFor({state:'hidden'});
  await mainInput('GT-2026-2','M').fill('3');await mainInput('GT-2026-2','M').press('Tab');
  await open();await query('GT-2026');
  check(await input('GT-2026-2','M').inputValue()==='3','Main quantities do not prefill picker');
  // New staged SKUs stay across search/page changes but never auto-join on Finish.
  await input('GT-2026-3','M').fill('4');await query('PICK-');
  const first=(await picker().locator('.picker-sku').first().innerText()).trim();await input(first,'M').fill('2');
  const next=page.waitForResponse(r=>r.url().includes('/api/admin/products?')&&new URL(r.url()).searchParams.get('page')==='2');
  await picker().getByRole('button',{name:'下一页',exact:true}).click();await next;await settled();
  const second=(await picker().locator('.picker-sku').first().innerText()).trim();check(first!==second,'Pagination unchanged');
  await input(second,'M').fill('1');await pending(3);
  await picker().getByRole('button',{name:'查看待处理',exact:true}).click();
  check(await input('GT-2026-3','M').inputValue()==='4'&&await input(first,'M').inputValue()==='2','Cross-page staging lost');
  await input(first,'M').fill('');check(await input(first,'M').isVisible(),'Temporary blank removed editing row');await input(first,'M').fill('2');
  const productsPattern='**/api/admin/products?*';
  await page.route(productsPattern,async route=>{
    if(!new URL(route.request().url()).searchParams.has('ids'))return route.continue();
    const response=await route.fetch(),data=await response.json();
    for(const p of data.items)if(p.sku===second)p.sizePrices.find(s=>s.sizeCode==='M').price=8.5;
    await route.fulfill({response,json:data});
  });
  await join(second);await confirmation().getByText('目录参考价 USD 7.5 → 8.5',{exact:true}).waitFor();
  await confirmation().getByRole('button',{name:'返回修改',exact:true}).click();await confirmation().waitFor({state:'hidden'});await pending(3);
  await page.unroute(productsPattern);await join(second);await pending(2);
  check(await main().locator('.order-product-row').count()===3,'Explicit row join failed');
  await query('GT-2026');await input('GT-2026-1','L').fill('2');
  await picker().getByRole('button',{name:'查看待处理',exact:true}).click();
  await finish();let unjoined=page.getByRole('dialog',{name:'新商品尚未加入',exact:true});
  await unjoined.getByRole('button',{name:'取消',exact:true}).click();await unjoined.waitFor({state:'hidden'});
  check(await input(first,'M').inputValue()==='2','Cancelled Finish discarded staging');
  await finish();await unjoined.getByRole('button',{name:'确认',exact:true}).click();await approve();await picker().waitFor({state:'hidden'});
  check(await mainInput('GT-2026-1','L').inputValue()==='2','Finish with unjoined SKUs lost an existing-SKU edit');
  check(await main().locator('.order-product-row').count()===3,'Finish automatically added new SKUs');
  const stateBefore=(await api('inventory/1')).product.stock;
  // Existing SKU changes use Finish atomically. Failed validation retains both edits and old order.
  await open();await query('GT-2026');
  await input('GT-2026-1','M').fill('1');await input('GT-2026-1','L').fill('0');await input('GT-2026-2','M').fill('2');
  await page.route(productsPattern,route=>new URL(route.request().url()).searchParams.has('ids')?route.fulfill({status:503,contentType:'application/json',body:JSON.stringify({message:'Picker fixture unavailable'})}):route.continue());
  await finish();await picker().getByRole('alert').filter({hasText:'Picker fixture unavailable'}).waitFor();await pending(2);
  check(await mainInput('GT-2026-1','M').inputValue()==='2','Failed Finish partially applied');await page.unroute(productsPattern);
  for(const fault of ['product','size']){
    await page.route(productsPattern,async route=>{
      if(!new URL(route.request().url()).searchParams.has('ids'))return route.continue();
      const response=await route.fetch(),data=await response.json();
      if(fault==='product')data.items=data.items.filter(p=>p.id!==2);
      else for(const p of data.items)if(p.id===2)p.sizePrices=p.sizePrices.filter(s=>s.sizeCode!=='M');
      await route.fulfill({response,json:data});
    });
    await finish();await picker().getByRole('alert').filter({hasText:fault==='product'?'商品已下架或删除':'尺码已移除'}).waitFor();await pending(2);
    check(await mainInput('GT-2026-1','M').inputValue()==='2'&&await mainInput('GT-2026-2','M').inputValue()==='3','Invalid batch partially applied');
    await page.unroute(productsPattern);
  }
  await finish();await confirmation().getByText('2 → 1',{exact:true}).waitFor();
  check((await confirmation().innerText()).includes('清零'),'Clear not identified');
  await confirmation().getByRole('button',{name:'返回修改',exact:true}).click();await confirmation().waitFor({state:'hidden'});
  check(await mainInput('GT-2026-1','M').inputValue()==='2','Cancelled confirmation changed main quantity');
  await finish();await approve();await picker().waitFor({state:'hidden'});
  check(await mainInput('GT-2026-1','M').inputValue()==='1'&&await mainInput('GT-2026-1','L').inputValue()==='0'&&await mainInput('GT-2026-2','M').inputValue()==='2','Finish did not overwrite exact quantities');
  // Joined existing zero can be applied and then restored using the one row action.
  await open();await query('GT-2026');await input('GT-2026-1','M').fill('0');await join('GT-2026-1');await approve();await pending(0);
  check(await mainInput('GT-2026-1','M').inputValue()==='0','Existing all-zero clear failed');
  await input('GT-2026-1','M').fill('1');await join('GT-2026-1');await approve();await pending(0);
  // All close paths warn and preserve pending input when cancelled.
  await input('GT-2026-3','M').fill('5');
  const warning=()=>page.getByRole('dialog',{name:'未应用的商品数量',exact:true});
  for(const action of [()=>picker().getByRole('button',{name:'取消',exact:true}).click(),()=>page.keyboard.press('Escape'),()=>page.mouse.click(20,100)]){
    await action();await warning().getByRole('button',{name:'取消',exact:true}).click();await warning().waitFor({state:'hidden'});
    check(await input('GT-2026-3','M').inputValue()==='5','Cancelled close lost inputs');
  }
  await picker().getByRole('button',{name:'关闭此对话框',exact:true}).click();await warning().getByRole('button',{name:'确认',exact:true}).click();await picker().waitFor({state:'hidden'});
  await open();await query('GT-2026');check(await input('GT-2026-3','M').inputValue()==='0','Discarded input survived reopen');
  check(await input('GT-2026-1','M').inputValue()==='1','Joined quantity lost');
  check(await input('GT-2026-3','L').count()===0,'Unrelated size rendered');
  await picker().screenshot({path:'output/playwright/order-selection-desktop.png',animations:'disabled'});
  await page.setViewportSize({width:390,height:844});await page.waitForFunction(()=>{const e=document.querySelector('.order-quantity-picker .quantity-list');return e&&e.scrollWidth<=e.clientWidth+1;});
  await picker().screenshot({path:'output/playwright/order-selection-mobile.png',animations:'disabled'});
  await finish();await picker().waitFor({state:'hidden'});await page.setViewportSize({width:1440,height:1000});
  check(orderWrites===0,'Picker saved formal order');check((await api('inventory/1')).product.stock===stateBefore,'Picker changed stored stock');
  await editor.getByRole('combobox',{name:/商城客户/}).click();await page.getByRole('option',{name:'Alex Morgan · Northline Apparel',exact:true}).click();
  for(const [name,value]of[['收货人','Selection QA'],['联系电话','123456'],['国家','Germany'],['详细地址','Fixture address']])await editor.getByRole('textbox',{name:new RegExp(name)}).fill(value);
  const create=page.waitForResponse(r=>r.url().endsWith('/api/admin/orders')&&r.request().method()==='POST');
  await editor.getByRole('button',{name:'创建待付款订单',exact:true}).click();await page.getByRole('dialog',{name:'确认操作',exact:true}).getByRole('button',{name:'确认',exact:true}).click();
  const response=await create;check(response.status()===200,'Formal order failed');const made=(await response.json()).order;
  check(made.items.length===3&&!made.items.some(i=>i.productId===1&&i.sizeCode==='L'),'Zero or duplicate lines submitted');
  check(made.items.find(i=>i.productId===1).quantity===1&&made.items.find(i=>i.productId===2).quantity===2,'Saved quantities wrong');
  check((await api('inventory/1')).product.stock===stateBefore-1&&orderWrites===1,'Order did not deduct stock once');page.off('request',count);
  return {orderSelection:true,zeroOnlyExplicitJoin:true,singleJoinAction:true,finishExistingOnly:true,finishNeverAddsNewSku:true,
    quantityOverwrite:true,zeroClears:true,crossPageStaging:true,atomicFailure:true,referencePriceConfirmation:true,
    discardGuard:true,noPickerStockOrTotals:true,keyboardAnd32px:true,narrowScreen:true,stockNeutralUntilSave:true,createDeductsOnce:true};
}
