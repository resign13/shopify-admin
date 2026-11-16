// Local *_test only. Works in CI's order fixture and the paired local fixture.
async page=>{
  const base=new URL(page.url()).origin;
  if(!['http://127.0.0.1:5360','http://127.0.0.1:5396'].includes(base))throw new Error('Isolated cancellation fixture required');
  let checks=0;const check=(ok,message)=>{if(!ok)throw new Error(message);checks++;};
  const api=(path,method='GET',body)=>page.evaluate(async({path,method,body})=>{
    const csrf=(await fetch('/api/auth/csrf').then(r=>r.json())).csrfToken;
    const r=await fetch('/api/admin/'+path,{method,headers:{'Content-Type':'application/json','X-CSRF-Token':csrf},...(body?{body:JSON.stringify(body)}:{})});
    if(!r.ok)throw new Error(path+': '+r.status);return r.json();
  },{path,method,body});
  await page.setViewportSize({width:1440,height:1000});await page.goto(base+'/orders');
  await page.waitForFunction(()=>location.pathname==='/login'||document.querySelector('.profile-button'));
  if(new URL(page.url()).pathname!=='/login'){await page.locator('.profile-button').click();await page.getByRole('menuitem',{name:'退出登录',exact:true}).click();}
  await page.waitForURL(url=>url.pathname==='/login');
  await page.getByRole('textbox',{name:'账号 / 邮箱'}).fill('admin@gingtto.test');
  await page.getByRole('textbox',{name:'密码',exact:true}).fill('Workbench-Test-2026');
  await page.getByRole('button',{name:'登录工作台',exact:true}).click();await page.waitForURL(url=>url.pathname!=='/login');
  const created=(await api('orders','POST',{requestId:crypto.randomUUID(),userId:1,contactName:'Cancellation workflow browser',phone:'123',country:'DE',address:'Fixture',shippingFee:1,
    items:[{productId:1,sizeCode:'M',quantity:2,unitPrice:17}]})).order;
  const initial=(await api(`orders/${created.id}`)).order;
  await api(`orders/${created.id}`,'PUT',{version:initial.version,status:'allocated'});
  const before=(await api('inventory/1')).product.stock;
  await page.goto(base+'/orders?status=all');
  await page.getByRole('textbox',{name:'订单查询关键词'}).fill(created.orderNo);
  const query=page.waitForResponse(r=>r.url().includes('/api/admin/orders?')&&new URL(r.url()).searchParams.get('keyword')===created.orderNo);
  await page.locator('main form.filters').getByRole('button',{name:'查询',exact:true}).click();await query;
  await page.getByRole('button',{name:'订单详情',exact:true}).click();
  const detail=page.getByRole('dialog',{name:'订单详情 · '+created.orderNo,exact:true});
  await detail.getByRole('button',{name:'申请取消',exact:true}).click();
  const requestDialog=page.getByRole('dialog',{name:'申请取消订单',exact:true});
  await requestDialog.getByRole('button',{name:'提交取消申请',exact:true}).click();
  await requestDialog.getByText('请填写申请原因',{exact:true}).waitFor();checks++;
  await requestDialog.getByRole('textbox',{name:'申请原因（必填）',exact:true}).fill('Workflow browser cancel reason');
  const submitting=page.waitForResponse(r=>r.url().endsWith(`/orders/${created.id}/cancellation-requests`)&&r.request().method()==='POST');
  await requestDialog.getByRole('button',{name:'提交取消申请',exact:true}).click();check((await submitting).status()===200,'Request UI failed');
  await requestDialog.waitFor({state:'hidden'});
  await detail.getByText('取消待审核',{exact:true}).waitFor();
  check(await detail.getByRole('button',{name:'修改订单资料',exact:true}).isDisabled(),'Pending order editor is not frozen');
  check((await api('inventory/1')).product.stock===before,'Request returned stock early');
  await detail.getByRole('button',{name:'撤回申请',exact:true}).click();
  await page.getByRole('dialog',{name:'确认操作',exact:true}).getByRole('button',{name:'确认',exact:true}).click();
  await detail.getByText('已撤回',{exact:true}).waitFor();
  check(await detail.getByRole('button',{name:'修改订单资料',exact:true}).isEnabled(),'Withdrawal did not unlock editor');
  await detail.getByRole('button',{name:'申请取消',exact:true}).click();
  await requestDialog.getByRole('textbox',{name:'申请原因（必填）',exact:true}).fill('Workflow browser cancel reason approved');
  await requestDialog.getByRole('button',{name:'提交取消申请',exact:true}).click();await requestDialog.waitFor({state:'hidden'});
  await detail.getByRole('button',{name:'关闭',exact:true}).click();
  const review=async item=>{
    await page.getByRole('button',{name:/^取消审批/}).click();
    const list=page.getByRole('dialog',{name:'取消审批',exact:true});
    await list.locator('.review-row').filter({hasText:item.orderNo}).getByRole('button',{name:'查看并审核',exact:true}).click();
    const dialog=page.getByRole('dialog',{name:'取消申请详情',exact:true});
    await dialog.getByRole('textbox',{name:'审核意见',exact:true}).fill('Cancellation reviewed in browser');
    const saving=page.waitForResponse(r=>r.url().endsWith(`/cancellation-requests/${item.id}/approve`)&&r.request().method()==='POST');
    await dialog.getByRole('button',{name:'审核通过并取消',exact:true}).click();
    await page.getByRole('dialog',{name:'确认操作',exact:true}).getByRole('button',{name:'确认',exact:true}).click();
    check((await saving).status()===200,'Approval UI failed');await dialog.waitFor({state:'hidden'});
    await page.screenshot({path:'output/playwright/cancellation-reviews-desktop.png',animations:'disabled'});
    await list.locator('.el-drawer__close-btn').click();
  };
  await review((await api(`orders/${created.id}`)).order.cancelRequest);
  const cancelled=(await api(`orders/${created.id}`)).order;
  check(cancelled.status==='cancelled'&&cancelled.cancelledFromStatus==='allocated','Self approval did not cancel from recorded state');
  check((await api('inventory/1')).product.stock===before+2,'Approval did not return stock exactly once');
  let customerApproved=false;
  const customer=(await api('orders/cancellation-requests')).items.find(item=>item.requesterKind==='store'&&item.reason==='Customer cancellation browser review');
  if(customer){await review(customer);check((await api(`orders/${customer.orderId}`)).order.status==='cancelled','Customer request did not reach cancelled state');customerApproved=true;}
  await page.reload();await page.setViewportSize({width:390,height:844});
  await page.getByRole('button',{name:'订单操作',exact:true}).click();
  check(await page.getByRole('button',{name:/^取消审批/}).isVisible(),'Mobile approval action unavailable');
  check(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),'Approval UI caused horizontal overflow');
  await page.screenshot({path:'output/playwright/cancellation-mobile-action.png',animations:'disabled'});
  return {passed:true,checks,request:true,withdraw:true,freeze:true,selfApproval:true,stockOnce:true,customerApproved,mobile:true};
}
