// Read-only rendering acceptance on the independent 5380 *_test fixture.
// Reuse an authenticated fixture session: no login, seeding or business writes.
async (page) => {
  const base='http://127.0.0.1:5380';
  if(!page.url().startsWith(base+'/'))throw new Error('Isolated 5380 *_test fixture required');
  const check=(value,message)=>{if(!value)throw new Error(message);};
  const writes=[],errors=[],checks=[];
  const onRequest=request=>{if(request.url().startsWith(base+'/api/')&&!['GET','HEAD','OPTIONS'].includes(request.method()))writes.push(request.url());};
  const onError=error=>errors.push(error.message);
  const first=await page.evaluate(async()=>{const r=await fetch('/api/admin/orders?page=1&pageSize=25');if(!r.ok)throw new Error('Authenticated order fixture required');return (await r.json()).items[0];});
  check(first,'Order fixture must contain an existing order');
  const imagePath=base+'/__mobile-detail-probe/';
  const attachments=[imagePath+'first.png',imagePath+'document.PDF?fixture=1',imagePath+'second.png',imagePath+'reference.pdf#page=1'];
  const detailPattern=base+'/api/admin/orders/'+first.id;
  const detailHandler=async route=>{
    const response=await route.fetch();check(response.ok(),'Fixture detail GET failed');
    const data=await response.json();
    data.order={...data.order,labelImageUrls:attachments,totalAmount:'999999999.99',knownWeightGrams:'1000',totalWeightGrams:null,missingWeightQuantity:1,
      items:data.order.items.map((item,index)=>({...item,sku:'LONGSKU'+String(index)+'X'.repeat(90)}))};
    await route.fulfill({response,json:data});
  };
  const imageHandler=route=>route.fulfill({status:200,contentType:'image/svg+xml',body:'<svg xmlns="http://www.w3.org/2000/svg" width="80" height="95"><rect width="80" height="95" fill="#2f69eb"/></svg>'});
  page.on('request',onRequest);page.on('pageerror',onError);
  await page.route(detailPattern,detailHandler);await page.route(imagePath+'**',imageHandler);
  try {
    await page.setViewportSize({width:393,height:852});
    await page.goto(base+'/orders?orderId='+first.id);await page.waitForLoadState('networkidle');
    const drawer=page.getByRole('dialog',{name:'订单详情',exact:true});
    const detail=drawer.locator('[data-testid="mobile-order-detail"]');await detail.waitFor();
    for(const width of [360,393,430]){
      await page.setViewportSize({width,height:852});await page.evaluate(()=>document.fonts.ready);
      const geometry=await detail.locator('.m-detail-card>header>h3').first().evaluate(el=>({width:el.clientWidth,scroll:el.scrollWidth,right:el.getBoundingClientRect().right,cardRight:el.closest('.m-detail-card').getBoundingClientRect().right}));
      check(geometry.width>0&&geometry.scroll<=geometry.width+1&&geometry.right<=geometry.cardRight,'Long SKU escapes its card at '+width);
      check(await detail.locator('.m-detail-hero>strong').evaluate(el=>getComputedStyle(el).fontSize)==='18px','Phone total hierarchy differs at '+width);
      check(await detail.locator('.m-detail-weight').textContent().then(t=>t.includes('1.000 kg')&&t.includes('1 件未设置重量')),'Weight values or missing-weight status disappeared');
      check(!(await detail.textContent()).includes('刷新详情可读取最新重量'),'Removed standing tutorial returned');
      checks.push({width,longSkuWraps:true,total18px:true,weightPreserved:true});
    }
    await detail.locator('summary').filter({hasText:'备注与附件'}).click();
    const images=detail.locator('.image-grid .el-image');
    check(await images.count()===2,'PDF entries were rendered as image thumbnails');
    check(await detail.locator('.image-grid a').count()===2,'PDF links were lost');
    await images.nth(1).click();
    const viewer=page.locator('.el-image-viewer__wrapper');await viewer.waitFor();
    const shown=viewer.locator('.el-image-viewer__img:visible');await shown.waitFor();
    check((await shown.getAttribute('src'))===attachments[2],'Second thumbnail opened a different image');
    await viewer.locator('.el-image-viewer__next').click();
    await page.waitForFunction(expected=>[...document.querySelectorAll('.el-image-viewer__img')].some(el=>el.getClientRects().length&&el.getAttribute('src')===expected),attachments[0]);
    await viewer.locator('.el-image-viewer__next').click();
    await page.waitForFunction(expected=>[...document.querySelectorAll('.el-image-viewer__img')].some(el=>el.getClientRects().length&&el.getAttribute('src')===expected),attachments[2]);
    await viewer.locator('.el-image-viewer__close').click();await viewer.waitFor({state:'hidden'});
    await drawer.getByRole('button',{name:'关闭',exact:true}).click();await drawer.waitFor({state:'hidden'});
    check(writes.length===0,'Read-only detail check sent writes: '+writes.join(', '));
    check(errors.length===0,'Browser exceptions: '+errors.join('; '));
    return {passed:true,checks,secondThumbnailCorrect:true,pdfExcluded:true,businessWrites:0,errors};
  } finally {
    const remainingViewer=page.locator('.el-image-viewer__wrapper:visible');
    if(!page.isClosed()&&await remainingViewer.count()){
      await remainingViewer.locator('.el-image-viewer__close').click();
      await remainingViewer.waitFor({state:'hidden'});
    }
    await page.unroute(detailPattern,detailHandler);await page.unroute(imagePath+'**',imageHandler);
    page.off('request',onRequest);page.off('pageerror',onError);
  }
}
