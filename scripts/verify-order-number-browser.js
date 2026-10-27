async (page) => {
  const base='http://127.0.0.1:5360';
  if(!page.url().startsWith(base+'/'))throw new Error('Isolated fixture required');
  await page.setViewportSize({width:1920,height:1000});
  const check=(ok,text)=>{if(!ok)throw new Error(text);};
  const api=(path,method='GET',body)=>page.evaluate(async({path,method,body})=>{
    const response=await fetch('/api/admin/'+path,{method,headers:{...(await fetch('/api/auth/csrf').then(r=>r.json()).then(d=>({'X-CSRF-Token':d.csrfToken}))),'Content-Type':'application/json'},...(body?{body:JSON.stringify(body)}:{})});
    if(!response.ok)throw new Error('Fixture API '+response.status);return response.json();
  },{path,method,body});
  const secondary='PO1013-Jonathan  Vargo Élodie 张三 Very Long Customer Name-000188';
  const before=(await api('inventory/1')).product.sizePrices.find(s=>s.sizeCode==='M').stock;
  const order=(await api('orders','POST',{requestId:crypto.randomUUID(),userId:1,contactName:'Jonathan Vargo',secondaryOrderNo:secondary,phone:'123456',country:'Germany',address:'18 Market Street',shippingFee:0,items:[{productId:1,sizeCode:'M',quantity:1,unitPrice:29.9}]})).order;
  check(/^LM-[0-9]{6,}$/.test(order.orderNo),'LM main number');check(order.secondaryOrderNo===secondary,'PO secondary');
  await page.goto(base+'/orders?keyword='+encodeURIComponent(secondary));
  const button=page.getByRole('button',{name:order.orderNo,exact:true});await button.waitFor();
  check(await button.innerText()===order.orderNo,'Main number intact');
  const numbers=button.locator('../..');
  const positions=await numbers.evaluate(el=>{const main=el.querySelector('.order-number-primary'),sub=el.querySelector('.order-number-secondary');return {main:main.getBoundingClientRect().y,sub:sub.getBoundingClientRect().y,mainSize:parseFloat(getComputedStyle(main).fontSize),subSize:parseFloat(getComputedStyle(sub).fontSize)};});
  check(positions.main<positions.sub&&positions.mainSize>positions.subSize,'Main above smaller secondary');
  check(await numbers.locator('.order-number-secondary').getAttribute('title')===secondary,'Full secondary tooltip');
  check(await numbers.getByRole('button',{name:/复制/}).count()===0,'No number copy buttons');
  await page.locator('main .el-scrollbar__wrap').evaluateAll(elements=>elements.forEach(el=>el.scrollLeft=0));
  await page.screenshot({path:'output/playwright/order-secondary-list.png',fullPage:true});
  await button.click();
  const detail=page.getByRole('dialog',{name:/^订单详情(?: · .+)?$/});await detail.waitFor();
  await detail.getByRole('button',{name:'修改副单号',exact:true}).waitFor();
  check((await detail.locator('.order-drawer-heading').innerText()).includes(secondary),'Full secondary in detail');
  await page.waitForFunction(()=>{const el=document.querySelector('.order-drawer-heading')?.closest('.el-drawer');const box=el?.getBoundingClientRect();return box&&Math.abs(box.right-innerWidth)<1;});
  await page.screenshot({path:'output/playwright/order-secondary-desktop.png',fullPage:true});
  await page.setViewportSize({width:390,height:844});
  await detail.locator('.m-detail-hero').getByText(order.orderNo,{exact:true}).waitFor();
  await detail.locator('summary').filter({hasText:'收货与订单资料'}).click();
  const mobileProfile=detail.locator('.m-detail-folds details[open]').filter({has:page.locator('summary').filter({hasText:'收货与订单资料'})});
  await mobileProfile.getByText(secondary,{exact:true}).waitFor();
  await page.waitForFunction(()=>{const el=document.querySelector('.m-detail-hero')?.closest('.el-drawer');const box=el?.getBoundingClientRect();return box&&box.x>=-1&&box.right<=innerWidth+1&&box.width<=innerWidth+1;});
  check(await detail.locator('.m-detail-hero').evaluate(el=>el.scrollWidth<=el.clientWidth+2),'Heading on mobile');
  check(await mobileProfile.evaluate(el=>el.scrollWidth<=el.clientWidth+2),'Full secondary profile overflows on mobile');
  await page.screenshot({path:'output/playwright/order-secondary-mobile.png',fullPage:true});
  await page.setViewportSize({width:1920,height:1000});
  async function edit(value){
    await detail.getByRole('button',{name:/^(修改|填写)副单号$/}).click();
    const input=detail.getByRole('textbox',{name:'副单号（选填）',exact:true});await input.waitFor();await input.fill(value);
    const saved=page.waitForResponse(r=>r.url().endsWith('/orders/'+order.id+'/details')&&r.request().method()==='PUT');
    await detail.getByRole('button',{name:'保存修改',exact:true}).click();await page.getByRole('button',{name:'确认',exact:true}).click();
    check((await saved).ok(),'Save secondary');
    await detail.getByRole('button',{name:'修改订单资料',exact:true}).waitFor();
  }
  await edit('-EDIT');let current=(await api('orders/'+order.id)).order;
  check(current.secondaryOrderNo==='PO-EDIT'&&current.orderNo===order.orderNo,'Fixed prefix and immutable main');
  await edit('');current=(await api('orders/'+order.id)).order;check(current.secondaryOrderNo==='','Optional clear');
  check((await api('inventory/1')).product.sizePrices.find(s=>s.sizeCode==='M').stock===before-1,'Only creation deducted inventory');
  await detail.getByRole('button',{name:'关闭',exact:true}).click();
  return {orderNumberUI:true,mainSecondary:true,optionalClear:true,noCopyButtons:true,tooltip:true,mobile:true,stockUnchangedOnEdit:true};
}
