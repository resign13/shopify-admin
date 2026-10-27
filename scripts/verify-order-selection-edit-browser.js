// Negotiated order and stock-delta acceptance, isolated local fixture only.
async (page) => {
  const base='http://127.0.0.1:5360';
  if(!page.url().startsWith(base+'/'))throw new Error('Isolated fixture required');
  page.removeAllListeners('dialog');page.on('dialog',dialog=>dialog.accept());
  const check=(value,message)=>{if(!value)throw new Error(message);};
  const api=(path,method='GET',body)=>page.evaluate(async({path,method,body})=>{
    const csrf=await fetch('/api/auth/csrf').then(r=>r.json());
    const response=await fetch('/api/admin/'+path,{method,headers:{'Content-Type':'application/json','X-CSRF-Token':csrf.csrfToken},...(body?{body:JSON.stringify(body)}:{})});
    if(!response.ok)throw new Error('Fixture API '+path+': '+response.status);
    return response.json();
  },{path,method,body});
  const made=(await api('orders','POST',{requestId:crypto.randomUUID(),userId:1,ownerAdminId:2,
    contactName:'Picker negotiated edit',phone:'123456',country:'Germany',address:'Fixture Street',shippingFee:2,
    items:[{productId:1,sizeCode:'M',quantity:3,unitPrice:11,priceSource:'manual'},
      {productId:1,sizeCode:'L',quantity:2,unitPrice:12,priceSource:'manual'}]})).order;
  const before=(await api('inventory/1')).product;
  const stocks=product=>Object.fromEntries(product.sizePrices.map(size=>[size.sizeCode,size.stock]));
  const balances=stocks(before);
  const open=async()=>{
    await page.goto(base+'/orders?page=1&pageSize=25&keyword='+encodeURIComponent(made.orderNo));
    await page.getByRole('button',{name:'订单详情',exact:true}).click();
    const detail=page.getByRole('dialog',{name:/^订单详情(?: · .+)?$/});
    await detail.getByRole('button',{name:'修改订单资料',exact:true}).click();
    await detail.getByRole('button',{name:'＋ 添加商品',exact:true}).waitFor();
    return detail;
  };
  await page.setViewportSize({width:1440,height:1000});
  let detail=await open();
  await detail.getByRole('button',{name:'＋ 添加商品',exact:true}).click();
  const picker=page.getByRole('dialog',{name:'选择商品',exact:true});
  await picker.getByRole('textbox',{name:'选品关键词',exact:true}).fill('GT-2026-1');
  await picker.getByRole('button',{name:'查询',exact:true}).click();
  const input=size=>picker.getByRole('spinbutton',{name:`GT-2026-1 ${size} 数量`,exact:true});
  await input('M').waitFor();
  check(await input('M').inputValue()==='3' && await input('L').inputValue()==='2','Saved order quantities did not prefill');
  await input('M').fill('1');await input('L').fill('0');await input('Tall XL').fill('1');
  await picker.getByRole('button',{name:'完成',exact:true}).click();
  const confirmation=page.getByRole('dialog',{name:'确认商品调整',exact:true});
  await confirmation.getByText('3 → 1',{exact:true}).waitFor();
  await confirmation.getByRole('button',{name:'确认应用',exact:true}).click();
  await picker.waitFor({state:'hidden'});
  await detail.getByTestId('size-stock-1-M').waitFor();
  check(await detail.getByTestId('size-stock-1-M').textContent()===`库存 ${balances.M+2}`,'Editing deducted full quantity instead of difference');
  check(await detail.getByTestId('size-stock-1-L').textContent()===`库存 ${balances.L+2}`,'Clearing did not preview returned stock');
  check(await detail.getByTestId('size-stock-1-Tall XL').textContent()===`库存 ${balances['Tall XL']-1}`,'New size stock preview incorrect');
  check(JSON.stringify(stocks((await api('inventory/1')).product))===JSON.stringify(balances),'Applying selection prematurely changed stored inventory');
  const responseWait=page.waitForResponse(r=>r.url().endsWith('/api/admin/orders/'+made.id+'/details')&&r.request().method()==='PUT');
  await detail.getByRole('button',{name:'保存修改',exact:true}).click();
  const savePrompt=page.getByRole('dialog',{name:'确认操作',exact:true});
  await savePrompt.getByRole('button',{name:'确认',exact:true}).click();
  const response=await responseWait;check(response.status()===200,'Saving adjusted order failed');
  const changed=(await response.json()).order;
  check(changed.items.find(i=>i.sizeCode==='M').unitPrice===11,'Manual quote was overwritten');
  check(changed.items.find(i=>i.sizeCode==='M').quantity===1,'Edited quantity accumulated');
  check(changed.items.find(i=>i.sizeCode==='Tall XL').unitPrice===29.9,'New size did not use directory price');
  check(!changed.items.some(i=>i.sizeCode==='L'),'Zero size was saved');
  check(changed.totalAmount===42.9,'Negotiated total is incorrect');
  const after=stocks((await api('inventory/1')).product);
  check(after.M===balances.M+2 && after.L===balances.L+2 && after['Tall XL']===balances['Tall XL']-1,'Saved stock deltas are incorrect');
  await detail.getByRole('button',{name:'关闭',exact:true}).click();await detail.waitFor({state:'hidden'});
  for(const status of ['shipped','completed','cancelled']){
    const current=(await api('orders/'+made.id)).order;
    await api('orders/'+made.id,'PUT',{version:current.version,status,
      ...(status==='shipped'?{trackingNo:'PICKER-QA-TRACK'}:{}),
      ...(status==='cancelled'?{cancelNote:'Fixture locked selection'}:{})});
    detail=await open();
    const add=detail.getByRole('button',{name:'＋ 添加商品',exact:true});
    const quantity=detail.getByRole('spinbutton',{name:'GT-2026-1 M 数量',exact:true});
    const pricing=detail.getByRole('button',{name:'统一改价',exact:true});
    if(status==='cancelled'){
      await detail.getByText('已取消订单保留原商品明细；可修改客户与收货资料。',{exact:true}).waitFor();
      check(await add.isDisabled() && await quantity.isDisabled() && await pricing.isDisabled(),'Cancelled product details unlocked');
      await detail.getByRole('button',{name:'取消修改',exact:true}).click();
    }else{
      await add.click({trial:true});
      check(await add.isEnabled() && await quantity.isEnabled() && await pricing.isEnabled(),`${status} product details remain locked`);
      await add.click();
      await picker.getByRole('textbox',{name:'选品关键词',exact:true}).fill('GT-2026-1');
      await picker.getByRole('button',{name:'查询',exact:true}).click();
      await input('M').waitFor();
      check(await input('M').inputValue()===String(current.items.find(i=>i.productId===1&&i.sizeCode==='M').quantity),'Fulfilled picker quantity mismatch');
      await picker.getByRole('button',{name:'完成',exact:true}).click();await picker.waitFor({state:'hidden'});
      const beforeStock=stocks((await api('inventory/1')).product);
      const next=Number(await quantity.inputValue())+1;
      await quantity.fill(String(next));await quantity.press('Tab');
      check(await detail.getByTestId('size-stock-1-M').textContent()===`库存 ${beforeStock.M-1}`,'Fulfilled preview deducted original quantity again');
      await pricing.click();
      const priceDialog=page.getByRole('dialog',{name:'统一改价 · USD',exact:true});
      const nextPrice=status==='shipped'?12:13;
      await priceDialog.getByRole('spinbutton',{name:'GT-2026-1 统一单价',exact:true}).fill(String(nextPrice));
      await priceDialog.getByRole('button',{name:'确认应用',exact:true}).click();
      await priceDialog.waitFor({state:'hidden'});
      await page.setViewportSize({width:390,height:844});
      await detail.getByRole('navigation',{name:'订单填写进度'}).getByRole('button',{name:/商品$/}).click();
      await quantity.scrollIntoViewIfNeeded();
      check(await quantity.isEnabled(),'Mobile fulfilled quantity locked');
      await page.screenshot({path:`output/playwright/order-edit-${status}-mobile.png`});
      await page.setViewportSize({width:1440,height:1000});
      const savedWait=page.waitForResponse(r=>r.url().endsWith('/api/admin/orders/'+made.id+'/details')&&r.request().method()==='PUT');
      await detail.getByRole('button',{name:'保存修改',exact:true}).click();
      await page.getByRole('dialog',{name:'确认操作',exact:true}).getByRole('button',{name:'确认',exact:true}).click();
      const savedResponse=await savedWait;check(savedResponse.status()===200,`${status} edit save failed`);
      const saved=(await savedResponse.json()).order;
      check(saved.status===status && saved.trackingNo==='PICKER-QA-TRACK','Fulfilled edit changed status or tracking');
      check(saved.items.find(i=>i.productId===1&&i.sizeCode==='M').quantity===next,'Fulfilled quantity was not saved');
      check(saved.items.every(i=>i.unitPrice===nextPrice&&i.priceSource==='manual'),'Fulfilled pricing was not saved');
      check(saved.totalAmount===saved.items.reduce((sum,i)=>sum+i.quantity*nextPrice,2),'Fulfilled total was not recalculated');
      check(stocks((await api('inventory/1')).product).M===beforeStock.M-1,'Fulfilled edit stock difference incorrect');
      await detail.getByRole('button',{name:'修改订单资料',exact:true}).waitFor();
      await page.screenshot({path:`output/playwright/order-edit-${status}-saved.png`});
    }
    await detail.getByRole('button',{name:'关闭',exact:true}).click();await detail.waitFor({state:'hidden'});
  }
  return {orderSelectionEdit:true,manualQuoteRetained:true,exactStockDelta:true,zeroReturnsStock:true,
    newSizeCurrentPrice:true,fulfilledEdits:true,fulfilledPrices:true,cancelledLocked:true,mobileFulfilledEdits:true};
}
