// Rendering-only fixtures for the queried report. Never submits costs or inventory.
async page => {
  const base=new URL(page.url()).origin;
  if(base!=='http://127.0.0.1:5362')throw Error('Isolated finance *_test fixture required');
  let checks=0,writes=0,mode='partial';
  const check=(value,message)=>{if(!value)throw Error(message);checks++;};
  const writePattern=/\/finance\/costs\/(preview|save)$/;
  const denyWrite=async route=>{writes++;await route.abort('blockedbyclient');};
  const reportRoute='**/api/admin/finance/reports/query';
  const render=async route=>{
    const response=await route.fetch();check(response.ok(),'Real report query failed');
    const original=await response.json(),rate=Number(original.filters.exchangeRate);
    const codes=['CS5402','CS5401-HEI','CS5101-200G','CS2209','CS2211','CS6105'];
    const quantities=[2497,2094,1016,1260,868,1018];
    const sales=[38021.33,35325.90,20127.46,30165,21349,15560];
    const items=codes.map((code,i)=>{
      const missing=mode==='partial'?(i===4?200:i===5?116:0):0;
      const salesCny=Number((sales[i]*rate).toFixed(2)),cost=(quantities[i]-missing)*35;
      return {...original.items[0],rowKey:'visual-'+i,styleCode:code,sku:code+'-'+['黑色','藏青','米杏'][i%3],sizeCode:['M','L','XL'][i%3],quantity:quantities[i],salesUsd:sales[i].toFixed(2),nativeSalesCny:'0.00',salesCny:salesCny.toFixed(2),totalCostCny:missing?null:cost.toFixed(2),knownCostCny:cost.toFixed(2),profitCny:missing?null:(salesCny-cost).toFixed(2),missingQuantity:missing};
    });
    const salesCny=items.reduce((sum,row)=>sum+Number(row.salesCny),0);
    const knownCost=items.reduce((sum,row)=>sum+Number(row.knownCostCny),0);
    const knownSales=items.reduce((sum,row)=>sum+Number(row.salesCny)*(row.quantity-row.missingQuantity)/row.quantity,0);
    const summary={...original.summary,orderCount:410,quantity:8753,salesUsd:'160548.69',nativeSalesCny:'0.00',salesCny:salesCny.toFixed(2),totalCostCny:mode==='partial'?null:mode==='loss'?(salesCny+100000).toFixed(2):knownCost.toFixed(2),knownCostCny:knownCost.toFixed(2),profitCny:mode==='partial'?null:mode==='loss'?'-100000.00':(salesCny-knownCost).toFixed(2),knownProfitCny:(knownSales-knownCost).toFixed(2),missingQuantity:mode==='partial'?316:0};
    const missingStyles=mode==='partial'?[{styleCode:'CS2211',missingQuantity:200},{styleCode:'CS6105',missingQuantity:116}]:[];
    await route.fulfill({response,json:{...original,summary,items,missingStyles,total:items.length,page:1}});
  };
  await page.route(writePattern,denyWrite);await page.route(reportRoute,render);
  const screenshotResults=async path=>{
    await page.evaluate(async()=>{
      await Promise.all(document.getAnimations().filter(a=>a.effect?.getComputedTiming().iterations!==Infinity).map(a=>a.finished.catch(()=>{})));
    });
    await page.evaluate(()=>window.scrollTo(0,0));
    const clip=await page.getByTestId('finance-report-results').boundingBox();
    await page.screenshot({path,fullPage:true,clip,animations:'disabled'});
  };
  try{
    await page.setViewportSize({width:1440,height:1000});await page.goto(base+'/finance');
    await page.getByRole('button',{name:'查询核算',exact:true}).waitFor();
    await page.getByRole('spinbutton',{name:'核算汇率',exact:true}).fill('7.123456');
    for(const [name,value] of [['开始日期','2026-09-01'],['结束日期','2026-09-30']]){const input=page.getByPlaceholder(name,{exact:true});await input.fill(value);await input.press('Enter');await input.press('Tab');}
    const query=async()=>{
      const [response]=await Promise.all([page.waitForResponse(r=>r.url().endsWith('/finance/reports/query')&&r.request().method()==='POST'),page.getByRole('button',{name:'查询核算',exact:true}).click()]);
      check(response.ok(),'Query failed');await page.locator('.finance-detail-heading').waitFor();
    };
    await query();
    check(await page.locator('.finance-sales-metric strong').textContent()==='$160,548.69 USD','Grouped sales amount lost digits');
    check((await page.getByTestId('finance-product-count').textContent()).includes('8,753'),'Grouped product count missing');
    const rects=await page.locator('.finance-summary>article').evaluateAll(nodes=>nodes.map(node=>node.getBoundingClientRect().toJSON()));
    check(rects.length===3&&rects.every(r=>Math.abs(r.top-rects[0].top)<1),'Monetary metrics do not align');
    check(await page.locator('.finance-summary strong').first().evaluate(el=>el.getBoundingClientRect().height<=parseFloat(getComputedStyle(el).lineHeight)+1),'Sales amount wraps at standard desktop width');
    check(await page.getByRole('button',{name:'查看缺失成本款号',exact:true}).isVisible(),'Missing-style help lost');
    await page.getByRole('button',{name:'查看缺失成本款号',exact:true}).hover();
    const missingTooltip=page.getByRole('tooltip',{name:/CS2211.*200.*CS6105.*116/});await missingTooltip.waitFor();
    await page.locator('.finance-overview-heading').hover();
    await missingTooltip.waitFor({state:'hidden'});
    check(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),'Desktop report overflows page');
    check(await page.getByTestId('finance-product-count').locator('strong').evaluate(el=>el.getBoundingClientRect().height<=parseFloat(getComputedStyle(el).lineHeight)+1),'Product count or its unit wraps at desktop width');
    await screenshotResults('output/playwright/finance-report-redesign-desktop.png');
    await page.screenshot({path:'output/playwright/finance-report-redesign-page.png',animations:'disabled'});
    await page.setViewportSize({width:1024,height:1000});
    check(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),'Narrow desktop report overflows page');
    check(await page.getByTestId('finance-order-count').locator('strong').evaluate(el=>parseFloat(getComputedStyle(el).fontSize)>=32),'Order count is no longer prominent');
    await screenshotResults('output/playwright/finance-report-redesign-1024.png');
    await page.setViewportSize({width:1440,height:1000});mode='complete';await query();
    await page.getByText('成本已完整',{exact:true}).waitFor();
    check(await page.locator('.report-missing').count()===0&&await page.locator('.finance-summary strong.summary-incomplete').count()===0,'Complete report retains missing-cost placeholders');
    check(await page.locator('.finance-summary strong.finance-positive').count()===1,'Completed profit is not distinguished');
    await screenshotResults('output/playwright/finance-report-redesign-complete.png');
    mode='loss';await query();
    check(await page.locator('.finance-summary strong.finance-negative').textContent()==='¥-100,000.00','Negative profit is hidden or displayed as positive');
    check(writes===0,'Presentation test submitted a cost change');
    return {reportUi:true,checks,queriedResultOnly:true,threeMonetaryMetrics:true,largeCounts:true,decimalPrecisionPreserved:true,missingStyleHelp:true,completeAndLossStates:true,narrowDesktop:true,renderOnlyNoWrites:true};
  }finally{
    await page.unroute(reportRoute,render);await page.unroute(writePattern,denyWrite);
    await page.goto(base+'/finance');
  }
}
