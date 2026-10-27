// Real UI acceptance on the existing guarded weights *_test fixture only.
async page => {
  const base = 'http://127.0.0.1:5360';
  if (!page.url().startsWith(base+'/')) throw Error('Isolated fixture required');
  const check = (value, message) => { if (!value) throw Error(message); };
  const api = (path, method='GET', body) => page.evaluate(async ({path, method, body}) => {
    const csrf = await fetch('/api/auth/csrf').then(r=>r.json());
    const response = await fetch('/api/admin/'+path, {method,
      headers:{'Content-Type':'application/json','X-CSRF-Token':csrf.csrfToken},
      ...(body ? {body:JSON.stringify(body)} : {})});
    if (!response.ok) throw Error(path+': '+response.status);
    return response.json();
  }, {path, method, body});
  const login = async role => {
    await page.goto(base+'/orders');
    await page.locator('.profile-button').click();
    await page.getByRole('menuitem', {name:'退出登录',exact:true}).click();
    await page.waitForURL(url=>url.pathname==='/login');
    await page.getByRole('textbox', {name:'账号 / 邮箱'}).fill(role+'@gingtto.test');
    await page.getByRole('textbox', {name:'密码',exact:true}).fill('Workbench-Test-2026');
    await page.getByRole('button', {name:'登录工作台',exact:true}).click();
    await page.waitForURL(url=>url.pathname!=='/login');
  };
  await page.setViewportSize({width:1440,height:1000});
  await login('admin');
  const body = {requestId:await page.evaluate(()=>crypto.randomUUID()),userId:1,
    contactName:'Partial allocation browser',phone:'123456',country:'Germany',address:'Fixture address',shippingFee:0,
    items:[{productId:1,sizeCode:'M',quantity:2,unitPrice:29.9}]};
  const made = await api('orders','POST',body), id=made.order.id;
  const order=(await api(`orders/${id}`)).order;
  const balance = async()=>{
    const p=(await api('inventory/1')).product;
    return JSON.stringify([p.stock,p.sizePrices.map(s=>[s.sizeCode,s.stock])]);
  };
  const stock=await balance();
  const query=async()=>{
    await page.goto(base+'/orders?status=all');
    await page.getByRole('textbox',{name:'订单查询关键词'}).fill(order.orderNo);
    const response=page.waitForResponse(r=>r.url().includes('/api/admin/orders?')&&new URL(r.url()).searchParams.get('keyword')===order.orderNo);
    await page.locator('main form.filters').getByRole('button',{name:'查询',exact:true}).click();
    check((await response).status()===200,'Search failed');
    await page.getByRole('button',{name:order.orderNo,exact:true}).waitFor();
  };
  await query();
  await page.getByRole('button',{name:`修改订单 ${order.orderNo} 状态`,exact:true}).click();
  await page.getByRole('menuitem',{name:'部分配货',exact:true}).click();
  const saved=page.waitForResponse(r=>r.url().endsWith(`/api/admin/orders/${id}`)&&r.request().method()==='PUT');
  await page.getByRole('dialog',{name:'修改订单状态',exact:true}).getByRole('button',{name:'确认',exact:true}).click();
  check((await saved).status()===200,'List status save failed');
  check((await api(`orders/${id}`)).order.status==='partially_allocated','List status not persisted');
  check(await balance()===stock,'Status change changed stock');
  const filtered=page.waitForResponse(r=>r.url().includes('/api/admin/orders?')&&new URL(r.url()).searchParams.get('status')==='partially_allocated');
  await page.getByRole('tab',{name:/^部分配货 /}).click();
  check((await filtered).status()===200,'Partial status filter failed');
  await page.getByRole('tab',{name:/^部分配货 /,selected:true}).waitFor();
  check(await page.getByRole('button',{name:'订单详情',exact:true}).count()===1,'Partial filter shows wrong orders');
  await page.screenshot({path:'output/playwright/partial-allocation-orders.png'});
  await page.getByRole('button',{name:'订单详情',exact:true}).click();
  const drawer=page.getByRole('dialog',{name:'订单详情 · '+order.orderNo,exact:true});
  await drawer.locator('.panel-title .el-tag').filter({hasText:'部分配货'}).waitFor();
  await drawer.getByRole('button',{name:'修改订单资料',exact:true}).click();
  await drawer.locator('.el-form-item').filter({has:page.getByRole('combobox',{name:'订单状态',exact:true})}).locator('.el-select').click();
  await page.getByRole('option',{name:'已配货',exact:true}).click();
  const details=page.waitForResponse(r=>r.url().endsWith(`/api/admin/orders/${id}/details`)&&r.request().method()==='PUT');
  await drawer.getByRole('button',{name:'保存修改',exact:true}).click();
  await page.getByRole('dialog',{name:'确认操作',exact:true}).getByRole('button',{name:'确认',exact:true}).click();
  check((await details).status()===200,'Detail status save failed');
  check((await api(`orders/${id}`)).order.status==='allocated','Detail selected wrong status');
  check(await balance()===stock,'Detail status change changed stock');
  await drawer.getByRole('button',{name:'关闭',exact:true}).click();
  // Warehouse uses its existing status-only form and sees no financial fields.
  await login('warehouse');
  await page.goto(base+'/orders?status=all');
  await query();
  await page.getByRole('button',{name:'订单详情',exact:true}).click();
  const warehouse=page.getByRole('dialog',{name:'订单详情 · '+order.orderNo,exact:true});
  check(await warehouse.getByText('应付总额（含运费）',{exact:true}).count()===0,'Warehouse exposed amounts');
  await warehouse.getByRole('button',{name:'修改订单状态',exact:true}).click();
  await warehouse.locator('.el-form-item').filter({has:page.getByRole('combobox',{name:/订单状态/})}).locator('.el-select').click();
  await page.getByRole('option',{name:'部分配货',exact:true}).click();
  const warehouseSaved=page.waitForResponse(r=>r.url().endsWith(`/api/admin/orders/${id}`)&&r.request().method()==='PUT');
  await warehouse.getByRole('button',{name:'保存修改',exact:true}).click();
  const response=await warehouseSaved; check(response.status()===200,'Warehouse save failed');
  const redacted=(await response.json()).order;
  check(!('totalAmount' in redacted)&&!('shippingFee' in redacted),'Warehouse response exposed amounts');
  check(redacted.status==='partially_allocated'&&await balance()===stock,'Warehouse status changed stock');
  await warehouse.getByRole('button',{name:'关闭',exact:true}).click();
  return {partialAllocation:true,listFilter:true,detailEdit:true,warehouseRedacted:true,statusOnlyStockUnchanged:true};
}
