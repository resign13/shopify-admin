async (page) => {
  const base='http://127.0.0.1:5360';
  if(!page.url().startsWith(base+'/'))throw new Error('Isolated *_test fixture required');
  const check=(v,m)=>{if(!v)throw new Error(m);};
  await page.setViewportSize({width:390,height:844});await page.goto(base+'/orders');
  await page.getByRole('button',{name:'展开导航',exact:true}).click();
  await page.getByRole('link',{name:'库存管理',exact:true}).click();
  await page.getByRole('button',{name:'登记数量',exact:true}).first().click();
  const d=page.getByRole('dialog',{name:'登记库存与到货进度',exact:true});
  const quantity=d.getByRole('spinbutton').first();const old=Number(await quantity.inputValue());
  await quantity.fill(String(old+1));await quantity.press('Tab');
  const back=page.goBack();
  const prompt=page.getByRole('dialog',{name:'未保存修改',exact:true});await prompt.waitFor();
  await prompt.getByRole('button',{name:'取消',exact:true}).click();await back;
  check(await quantity.inputValue()===String(old+1),'Browser back discarded draft');
  // A reduced visual viewport leaves the active field and footer reachable.
  await page.setViewportSize({width:390,height:430});await quantity.focus();await quantity.scrollIntoViewIfNeeded();
  await page.waitForFunction(()=>document.querySelector('.inventory-registration').getBoundingClientRect().height<=431);
  check(await d.getByRole('button',{name:'保存修改',exact:true}).evaluate(el=>{const r=el.getBoundingClientRect();return r.top>=0&&r.bottom<=innerHeight;}),'Short viewport hides save');
  await d.getByRole('button',{name:'取消',exact:true}).click();await prompt.getByRole('button',{name:'确认',exact:true}).click();
  await page.setViewportSize({width:390,height:844});await page.goto(base+'/orders');
  await page.getByRole('button',{name:'＋ 新增订单',exact:true}).click();
  const editor=page.getByRole('dialog',{name:'新增订单',exact:true});
  await editor.getByRole('textbox',{name:/收货人/}).fill('Mobile draft '+Date.now());
  await editor.getByRole('button',{name:'更多',exact:true}).click();
  const response=page.waitForResponse(r=>r.url().endsWith('/api/admin/orders/drafts')&&r.request().method()==='POST');
  await page.getByRole('button',{name:'保存草稿',exact:true}).click();check((await response).ok(),'Mobile draft save failed');
  await editor.getByRole('button',{name:'取消',exact:true}).click();
  return {browserBackGuard:true,draftRetained:true,reducedViewportFooter:true,mobileMoreSavesDraft:true};
}
