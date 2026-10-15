async (page) => {
  if (!page.url().startsWith('http://127.0.0.1:5362/')) throw new Error('Isolated finance fixture required');
  const assert=(value,message)=>{if(!value)throw new Error(message);};
  // Rendering-only data exercises a full page and long identifiers. No fake
  // cost is ever submitted; real save/clear behavior has its own lifecycle test.
  const rows=Array.from({length:20},(_,i)=>({styleCode:i===19?'CS2209-LONG-STYLE-CODE-EXAMPLE':`CS${2209+i}`,
    costCny:i%4===0?null:i===1?'0.00':(28.5+i*2.75).toFixed(2),version:'0',updatedAt:null}));
  let writes=0;
  await page.route(/\/finance\/costs\/(preview|save)$/,async route=>{writes++;await route.abort('blockedbyclient');});
  const costRoute='**/api/admin/finance/costs?*';
  await page.route(costRoute,async route=>{
    assert(new URL(route.request().url()).searchParams.get('pageSize')==='20','Editor requests 20 styles per page');
    const result=await route.fetch();assert(result.ok(),'Server accepts 20-style pages');
    await route.fulfill({response:result,json:{items:rows,total:37,page:1,pageSize:20,costBasis:'style_at_order_time'}});
  });
  await page.setViewportSize({width:1440,height:1000});
  await page.goto('http://127.0.0.1:5362/finance');
  await page.getByRole('button',{name:'商品成本',exact:true}).click();
  const input=page.getByRole('spinbutton',{name:'CS2209 成本',exact:true});
  const next=page.getByRole('spinbutton',{name:'CS2210 成本',exact:true});
  await input.waitFor();await page.locator('.finance-panel .el-loading-mask').waitFor({state:'hidden'});
  assert((await page.locator('.cost-ledger-column').locator('tbody').evaluateAll(nodes=>nodes.map(n=>n.rows.length))).every(count=>count===10),'Ten styles in each desktop column');
  assert(await page.locator('.cost-ledger-column').count()===2,'Twenty styles are split into two ten-row ledgers');
  const columns=await page.locator('.cost-ledger-column').evaluateAll(nodes=>nodes.map(n=>n.getBoundingClientRect().toJSON()));
  assert(Math.abs(columns[0].top-columns[1].top)<1&&columns[1].left>columns[0].right-1,'Desktop ledgers align side by side');
  assert(await page.locator('.style-cost-table tbody tr').count()===20,'No styles lost in compact layout');
  assert(await page.locator('.cost-history-button').count()===20,'One history action per style');
  assert(await page.locator('.cost-sheet-bottom .btn-next').evaluate(node=>{const r=node.getBoundingClientRect(),target=document.elementFromPoint(r.left+r.width/2,r.top+r.height/2);return target===node||node.contains(target);}), 'Twenty-style pagination is not covered by the save bar');
  assert(await page.getByRole('spinbutton',{name:'批量成本金额',exact:true}).count()===0,'Idle state hides unused batch controls');
  assert(await page.getByRole('button',{name:'保存成本（0）',exact:true}).isDisabled(),'No accidental empty save');
  assert(await input.inputValue()===''&&await next.inputValue()==='0.00','Blank and explicit zero stay distinct');
  assert(await next.evaluate(node=>getComputedStyle(node).textAlign)==='right','Costs align like a financial ledger');
  await page.locator('.cost-result-count').click();
  await page.screenshot({path:'output/playwright/finance-cost-ui-desktop.png',fullPage:true});
  await input.fill('38.5');await input.press('Enter');
  assert(await next.evaluate(node=>node===document.activeElement),'Enter focuses the next style cost');
  assert(await input.inputValue()==='38.50','Leaving input retains two-decimal amount');
  await next.press('Shift+Enter');assert(await input.evaluate(node=>node===document.activeElement),'Shift+Enter focuses previous style');
  assert(await page.locator('.cost-save-state').textContent()==='1 款未保存','Unsaved count is explicit');
  await page.getByText('当前页全选',{exact:true}).click();
  await page.getByRole('spinbutton',{name:'批量成本金额',exact:true}).fill('35');
  await page.getByRole('button',{name:'批量应用',exact:true}).click();
  await page.getByRole('button',{name:'取消',exact:true}).click();
  assert(await input.inputValue()==='38.50','Cancel overwrite keeps typed draft');
  await page.getByRole('button',{name:'批量应用',exact:true}).click();
  await page.getByRole('button',{name:'确认',exact:true}).click();
  assert(await page.locator('.style-cost-table .cost-changed').count()===20,'Batch applies to both ledger columns');
  await page.locator('.cost-result-count').click();
  await page.screenshot({path:'output/playwright/finance-cost-ui-selected.png',fullPage:true});
  await page.getByRole('button',{name:'成本填写说明',exact:true}).click();
  await page.getByText('每个款号一个人民币单件成本，全部颜色和尺码共用。空白表示未设置，0 为明确零成本。',{exact:false}).waitFor();
  await page.getByRole('button',{name:'成本填写说明',exact:true}).click();
  await page.getByText('每个款号一个人民币单件成本，全部颜色和尺码共用。空白表示未设置，0 为明确零成本。',{exact:false}).waitFor({state:'hidden'});
  await page.setViewportSize({width:1024,height:1000});
  const tablet=await page.locator('.cost-ledger-column').evaluateAll(nodes=>nodes.map(n=>n.getBoundingClientRect().toJSON()));
  assert(tablet[1].top>=tablet[0].bottom,'Tablet uses one continuous ledger');
  assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),'Tablet page does not overflow');
  await page.screenshot({path:'output/playwright/finance-cost-ui-tablet.png',fullPage:true});
  await page.setViewportSize({width:390,height:844});
  await page.getByRole('spinbutton',{name:'CS2209-LONG-STYLE-CODE-EXAMPLE 成本',exact:true}).scrollIntoViewIfNeeded();
  assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),'Mobile page does not overflow with long style codes');
  const footer=page.locator('.cost-actionbar');await footer.scrollIntoViewIfNeeded();
  assert(await footer.getByRole('button',{name:'保存成本（20）',exact:true}).isEnabled(),'Mobile save remains reachable');
  await page.evaluate(()=>window.scrollTo(0,0));
  await page.screenshot({path:'output/playwright/finance-cost-ui-mobile.png',fullPage:true});
  await page.getByRole('button',{name:'清空',exact:true}).click();await page.getByRole('button',{name:'取消',exact:true}).click();
  assert(await input.inputValue()==='35.00','Mobile clear cancellation retains drafts');
  assert(writes===0,'Rendering test never posts synthetic costs');
  // Discard only the browser draft before removing the visual response fixture.
  await page.getByRole('button',{name:'成本统计',exact:true}).click();await page.getByRole('button',{name:'确认',exact:true}).click();
  await page.unroute(costRoute);await page.unroute(/\/finance\/costs\/(preview|save)$/);
  return {costUi:true,twoColumnLedger:true,responsiveSingleColumn:true,contextualBatch:true,unsavedCount:true,
    currencyAlignment:true,enterNavigation:true,zeroVsBlank:true,mobileSaveReachable:true,longStyleCode:true,renderOnlyNoWrites:true};
}
