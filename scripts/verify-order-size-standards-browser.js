// Independent real-size rows. Writes are drafts in the isolated *_test fixture.
async (page) => {
  const base='http://127.0.0.1:5360';
  if(!page.url().startsWith(base+'/'))throw new Error('Isolated fixture required');
  page.removeAllListeners('dialog');page.on('dialog',dialog=>dialog.accept());
  const check=(value,message)=>{if(!value)throw new Error(message);};
  const api=(path,method='GET',body)=>page.evaluate(async({path,method,body})=>{
    const csrf=await fetch('/api/auth/csrf').then(r=>r.json());
    const r=await fetch('/api/admin/'+path,{method,headers:{'Content-Type':'application/json','X-CSRF-Token':csrf.csrfToken},...(body?{body:JSON.stringify(body)}:{})});
    if(!r.ok)throw new Error('Fixture API '+path+': '+r.status);
    return r.json();
  },{path,method,body});
  const catalog=(await api('products?page=1&pageSize=25&keyword=DEMO-')).items;
  check(catalog.length===8,'Eight synthetic standard examples required');
  const baseline=JSON.stringify(catalog.map(p=>[p.id,p.sizePrices.map(s=>[s.sizeCode,s.stock])]));
  const orderCount=(await api('orders?page=1&pageSize=25')).total;
  await page.setViewportSize({width:1440,height:1080});
  await page.goto(base+'/orders');
  await page.getByRole('button',{name:'＋ 新增订单',exact:true}).click();
  let editor=page.getByRole('dialog',{name:'新增订单',exact:true});
  const contact='Independent size QA '+Date.now();
  await editor.getByRole('textbox',{name:/收货人/}).fill(contact);
  const openPicker=async()=>{
    await editor.getByRole('button',{name:'＋ 添加商品',exact:true}).click();
    const d=page.getByRole('dialog',{name:'选择商品',exact:true});
    await d.getByRole('textbox',{name:'选品关键词',exact:true}).fill('DEMO-');
    const query=page.waitForResponse(r=>r.url().includes('/api/admin/products?')&&new URL(r.url()).searchParams.get('keyword')==='DEMO-');
    await d.getByRole('button',{name:'查询',exact:true}).click();await query;
    await page.waitForFunction(()=>!document.querySelector('.order-quantity-picker .el-loading-mask'));
    return d;
  };
  let picker=await openPicker();
  const row=sku=>picker.locator('.picker-product-row').filter({has:page.getByText(sku,{exact:true})});
  const input=(sku,size)=>picker.getByRole('spinbutton',{name:`${sku} ${size} 数量`,exact:true});
  check(await picker.locator('.picker-product-row').count()===8,'Unexpected product rows');
  check(await picker.locator('.el-table').count()===0,'Shared size matrix remains');
  for(const product of catalog){
    const labels=await row(product.sku).locator('.picker-size-name').allTextContents();
    check(JSON.stringify(labels)===JSON.stringify(product.sizePrices.map(s=>s.sizeCode)),product.sku+': wrong sizes/order');
    check(await row(product.sku).getByRole('spinbutton').count()===product.sizePrices.length,product.sku+': extraneous inputs');
    check(!(await row(product.sku).innerText()).includes('—'),product.sku+': unrelated dash remains');
  }
  await row('DEMO-NOSIZE').getByText('未配置尺码',{exact:true}).waitFor();
  check(await row('DEMO-NOSIZE').getByRole('button',{name:'加入',exact:true}).isDisabled(),'Unconfigured product can be added');
  const numeric=row('DEMO-JN200-蓝');
  check(JSON.stringify(await numeric.locator('.picker-size-name').allTextContents())===JSON.stringify(['36','34','32','30','28']),'Numeric-looking codes were sorted instead of configured order');
  await input('DEMO-JN200-蓝','36').focus();await input('DEMO-JN200-蓝','36').press('Tab');
  check(await input('DEMO-JN200-蓝','34').evaluate(el=>el===document.activeElement),'Keyboard order differs from visible size order');
  const values=[['DEMO-TS100-黑','S',2],['DEMO-TS100-黑','M',3],['DEMO-JN200-蓝','30',4],
    ['DEMO-KD300-白','120',2],['DEMO-OS500-灰','均码',5],
    ['DEMO-MIX600-黑','S/28',3],['DEMO-MANY','CUSTOM-SIZE-EXTRA-LONG-LABEL',1]];
  for(const [sku,size,quantity] of values)await input(sku,size).fill(String(quantity));
  const many=row('DEMO-MANY');
  const longName=many.getByText('CUSTOM-SIZE-EXTRA-LONG-LABEL',{exact:true});
  const longLabel=await longName.evaluate(el=>({text:el.textContent,width:el.clientWidth,scroll:el.scrollWidth,height:el.clientHeight,ellipsis:getComputedStyle(el).textOverflow}));
  check(longLabel.text==='CUSTOM-SIZE-EXTRA-LONG-LABEL' && longLabel.scroll<=longLabel.width+1 && longLabel.height>16 && longLabel.ellipsis!=='ellipsis','Long size was truncated or escaped its cell');
  const wrapLines=await many.locator('.picker-size-unit').evaluateAll(els=>new Set(els.map(el=>Math.round(el.getBoundingClientRect().top))).size);
  check(wrapLines>1,'Many sizes did not wrap on desktop');
  await picker.locator('.el-drawer__body').evaluate(el=>{el.scrollTop=0;});
  await picker.screenshot({path:'output/playwright/order-independent-sizes-desktop.png',animations:'disabled'});
  await many.screenshot({path:'output/playwright/order-independent-many-sizes.png',animations:'disabled'});
  for(const width of [768,390,320]){
    await page.setViewportSize({width,height:844});
    await page.waitForFunction(w=>{
      const d=document.querySelector('.order-quantity-picker'), list=d?.querySelector('.quantity-list');
      return d?.getBoundingClientRect().width<=w+1 && list && list.scrollWidth<=list.clientWidth+1;
    },width);
    const geometry=await picker.evaluate(el=>{
      const list=el.querySelector('.quantity-list'), box=list.getBoundingClientRect();
      return {width:el.getBoundingClientRect().width,overflow:list.scrollWidth-list.clientWidth,
        fields:[...list.querySelectorAll('.picker-size-unit')].every(n=>{const r=n.getBoundingClientRect();return r.left>=box.left-1 && r.right<=box.right+1;}),
        detached:[...list.querySelectorAll('.picker-size-unit')].some(n=>{const r=n.getBoundingClientRect(), a=n.querySelector('.picker-size-name').getBoundingClientRect(), b=n.querySelector('input').getBoundingClientRect();return a.top<r.top-1 || b.bottom>r.bottom+1;}),
        rows:[...list.querySelectorAll('.picker-product-row')].map(n=>({sku:n.querySelector('.picker-sku').getBoundingClientRect().bottom,actions:n.querySelector('.picker-row-actions').getBoundingClientRect().bottom,sizes:n.querySelector('.picker-row-sizes').getBoundingClientRect().top}))};
    });
    check(geometry.width<=width+1 && geometry.overflow<=1 && geometry.fields && !geometry.detached,'Size blocks overflow/detach at width '+width);
    if(width<=600)check(geometry.rows.every(r=>r.sku<=r.sizes+1&&r.actions<=r.sizes+1),'Mobile header/actions not above sizes');
    await picker.locator('.el-drawer__body').evaluate(el=>{el.scrollTop=0;});
    await picker.screenshot({path:`output/playwright/order-independent-sizes-${width}.png`,animations:'disabled'});
  }
  await page.setViewportSize({width:1440,height:1080});
  for(const sku of [...new Set(values.map(v=>v[0]))])await row(sku).getByRole('button',{name:'加入',exact:true}).click();
  await row('DEMO-SH400-黑').getByRole('button',{name:'加入',exact:true}).click();
  await editor.getByTestId('order-product-'+catalog.find(p=>p.sku==='DEMO-SH400-黑').id).waitFor();
  await picker.getByRole('button',{name:'完成',exact:true}).click();await picker.waitFor({state:'hidden'});
  const main=editor.getByTestId('order-product-list');
  for(const product of catalog.filter(p=>values.some(v=>v[0]===p.sku))){
    const actual=await main.getByTestId('order-product-'+product.id).locator('.order-size-label').allTextContents();
    check(JSON.stringify(actual)===JSON.stringify(product.sizePrices.map(s=>s.sizeCode)),'Main editor uses unrelated sizes for '+product.sku);
  }
  check(await main.locator('.el-table').count()===0,'Main editor still has a shared size table');
  const mainMany=main.getByTestId('order-product-'+catalog.find(p=>p.sku==='DEMO-MANY').id);
  check(await mainMany.locator('.order-size-unit').evaluateAll(els=>new Set(els.map(el=>Math.round(el.getBoundingClientRect().top))).size)>1,'Main editor sizes do not wrap');
  await main.scrollIntoViewIfNeeded();
  await page.waitForFunction(()=>!document.querySelector('.el-message'));
  await editor.screenshot({path:'output/playwright/order-editor-independent-desktop.png',animations:'disabled'});
  for(const width of [768,390,320]){
    await page.setViewportSize({width,height:844});
    await page.waitForFunction(()=>{
      const el=document.querySelector('[data-testid=order-product-list]');
      return el && el.getBoundingClientRect().right<=innerWidth+1 && el.scrollWidth<=el.clientWidth+1 && [...el.querySelectorAll('.order-size-unit')].every(n=>{const a=n.getBoundingClientRect(),b=n.querySelector('.el-input-number').getBoundingClientRect();return a.left>=-1&&a.right<=innerWidth+1&&b.width<=73&&Math.abs(b.height-32)<1;});
    });
    check(await main.evaluate(el=>[...el.querySelectorAll('.order-size-unit')].every(n=>{const a=n.getBoundingClientRect(),b=n.querySelector('.el-input-number').getBoundingClientRect();return a.left>=-1&&a.right<=innerWidth+1&&b.width<=73&&Math.abs(b.height-32)<1;})),'Main quantity fields overflow/wrong height at '+width);
    await main.scrollIntoViewIfNeeded();
    await editor.screenshot({path:`output/playwright/order-editor-independent-${width}.png`,animations:'disabled'});
  }
  await page.setViewportSize({width:1440,height:1080});
  const draftWait=page.waitForResponse(r=>r.url().endsWith('/api/admin/orders/drafts')&&r.request().method()==='POST');
  await editor.getByRole('button',{name:'保存草稿',exact:true}).click();
  const response=await draftWait;check(response.status()===200,'Mixed real sizes could not save as draft');
  const saved=await response.json();
  await editor.getByRole('button',{name:'取消',exact:true}).click();await editor.waitFor({state:'hidden'});
  await page.getByRole('button',{name:'我的草稿',exact:true}).click();
  const manager=page.getByRole('dialog',{name:'订单草稿',exact:true}).filter({hasText:'草稿保存在服务器，不生成订单、不占库存。'});
  await manager.locator('.el-table__row').filter({has:page.getByText(contact,{exact:true})}).getByRole('button',{name:'继续编辑',exact:true}).click();
  editor=page.getByRole('dialog',{name:'订单草稿',exact:true}).filter({has:page.getByRole('textbox',{name:/收货人/})});
  picker=await openPicker();
  for(const [sku,size,quantity] of values)check(await input(sku,size).inputValue()===String(quantity),'Draft changed true size '+sku+'/'+size);
  check(await row('DEMO-SH400-黑').getByRole('button',{name:'加入',exact:true}).isDisabled(),'Zero-only joined SKU lost during draft restore');
  check(await input('DEMO-SH400-黑','40').inputValue()==='0','Restored zero SKU acquired a quantity');
  await picker.getByRole('button',{name:'取消',exact:true}).click();await picker.waitFor({state:'hidden'});
  await editor.getByRole('button',{name:'取消',exact:true}).click();await editor.waitFor({state:'hidden'});
  const latest=(await api('products?page=1&pageSize=25&keyword=DEMO-')).items;
  check(JSON.stringify(latest.map(p=>[p.id,p.sizePrices.map(s=>[s.sizeCode,s.stock])]))===baseline,'Draft/selection changed stock');
  check((await api('orders?page=1&pageSize=25')).total===orderCount,'Selection/draft created a formal order');
  const snapshot=await api('orders/drafts/'+saved.id);
  await api('orders/drafts/'+saved.id,'DELETE',{version:snapshot.version});
  return {independentSizeRows:true,sixStandards:true,configuredNumericOrder:true,longLabelsComplete:true,
    autoWrap:true,desktopTabletMobile:true,noHorizontalScroll:true,mixedDraftRestore:true,noStockWrite:true,mainEditorIndependentSizes:true,mainEditorWrapAndMobile:true,zeroOnlyDraftRestore:true};
}
