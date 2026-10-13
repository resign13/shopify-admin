async (page) => {
  const base='http://127.0.0.1:5360';
  if(!page.url().startsWith(base+'/'))throw new Error('Isolated fixture required');
  await page.setViewportSize({width:1440,height:1000});
  const check=(ok,text)=>{if(!ok)throw new Error(text);};
  const order=await page.evaluate(async()=>{
    const response=await fetch('/api/admin/orders',{method:'POST',headers:{Authorization:'Bearer '+localStorage.getItem('lumiere-admin-token'),'Content-Type':'application/json'},body:JSON.stringify({requestId:crypto.randomUUID(),userId:1,contactName:'Jonathan  Vargo Élodie 张三 Very Long Customer Name',phone:'123456',country:'Germany',address:'18 Market Street',shippingFee:0,items:[{productId:1,sizeCode:'M',quantity:1,unitPrice:29.9}]})});
    if(!response.ok)throw new Error('Fixture creation failed');return (await response.json()).order;
  });
  await page.goto(base+'/orders?keyword='+encodeURIComponent(order.orderNo));
  const button=page.getByRole('button',{name:order.orderNo,exact:true});await button.waitFor();
  const shown=await button.innerText();
  check(shown.includes('...'),'Name not shortened');
  check(shown.startsWith(order.orderNo.slice(0,7))&&shown.endsWith(order.orderNo.slice(-7)),'Prefix or sequence lost');
  check(await button.locator('..').getAttribute('title')===order.orderNo,'Full tooltip missing');
  const header=page.getByRole('columnheader',{name:'订单号',exact:true});
  check(Math.abs((await header.boundingBox()).width-260)<2,'Order column width');
  await page.context().grantPermissions(['clipboard-read','clipboard-write']);
  await page.getByRole('button',{name:'复制完整订单号 '+order.orderNo,exact:true}).click();
  check(await page.evaluate(()=>navigator.clipboard.readText())===order.orderNo,'Copy shortened identifier');
  await button.click();
  const detail=page.getByRole('dialog',{name:'订单详情 · '+order.orderNo,exact:true});await detail.waitFor();
  await page.waitForFunction(() => { const el=[...document.querySelectorAll('.el-drawer')].find(el=>el.getAttribute('aria-label')?.startsWith('订单详情 · ')); return el && Math.abs(el.getBoundingClientRect().right-innerWidth)<1; });
  check(await detail.locator('.el-drawer__title').innerText()==='订单详情 · '+order.orderNo,'Full title missing');
  await page.screenshot({path:'output/playwright/order-number-desktop.png',fullPage:true});
  await page.setViewportSize({width:390,height:844});
  await page.waitForFunction(() => { const el=[...document.querySelectorAll('.el-drawer')].find(el=>el.getAttribute('aria-label')?.startsWith('订单详情 · ')); const box=el?.getBoundingClientRect(); return box && box.x>=-1 && box.right<=innerWidth+1; });
  const dimensions=await detail.locator('.el-drawer__header').evaluate(el=>({width:el.clientWidth,scroll:el.scrollWidth}));
  check(dimensions.scroll<=dimensions.width+2,'Drawer heading overflows on mobile');
  check((await detail.boundingBox()).x>=-1,'Drawer offscreen on mobile');
  await page.screenshot({path:'output/playwright/order-number-mobile.png',fullPage:true});
  await detail.getByRole('button',{name:'关闭',exact:true}).click();
  await page.setViewportSize({width:1440,height:1000});
  return {orderNumberUI:true,fullCopy:true,tooltip:true,mobile:true};
}
