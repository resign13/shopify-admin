// Presentation acceptance on admin-mobile-browser-fixture.py only. No saves or reseeding.
// Retains the legacy full-calendar, cross-month, landscape footer and chart boundaries.
async (page) => {
  const base='http://127.0.0.1:5380';
  if(!page.url().startsWith(base+'/'))throw new Error('Isolated 5380 *_test mobile fixture required');
  const check=(value,message)=>{if(!value)throw new Error(message);};
  const errors=[],writes=[],calendarWidths=[];
  const onError=error=>errors.push(error.message);
  const onRequest=request=>{if(request.url().startsWith(base+'/api/admin/')&&!['GET','HEAD','OPTIONS'].includes(request.method())&&!request.url().endsWith('/finance/reports/query'))writes.push(request.url());};
  page.on('pageerror',onError);page.on('request',onRequest);
  const visit=async path=>{await page.goto(base+path);await page.waitForLoadState('networkidle');await page.evaluate(()=>document.fonts.ready);};
  const settle=async locator=>locator.evaluate(el=>Promise.all(el.getAnimations({subtree:true}).map(a=>a.finished.catch(()=>{}))));
  const close=async dialog=>{await dialog.getByRole('button',{name:'关闭此对话框',exact:true}).click();await dialog.waitFor({state:'hidden'});};
  try {
    for(const width of [360,393,430]){
      await page.setViewportSize({width,height:852});await visit('/orders');
      await page.getByRole('button',{name:'更多筛选',exact:true}).click();
      await page.getByPlaceholder('开始日期',{exact:true}).click();
      const calendar=page.locator('.el-date-range-picker:visible');await calendar.waitFor();
      await calendar.evaluate(el=>Promise.all((el.closest('.el-popper')||el).getAnimations({subtree:true}).map(a=>a.finished.catch(()=>{}))));
      const layout=await calendar.evaluate(el=>{
        const rect=el.getBoundingClientRect(),body=el.querySelector('.el-picker-panel__body').getBoundingClientRect();
        const panels=[...el.querySelectorAll('.el-date-range-picker__content')].map(p=>{const r=p.getBoundingClientRect();return {top:r.top,bottom:r.bottom};});
        const cell=el.querySelector('td.available').getBoundingClientRect();
        return {left:rect.left,right:rect.right,width:rect.width,bodyWidth:body.width,panels,cellWidth:cell.width,cellHeight:cell.height};
      });
      check(layout.left>=-1&&layout.right<=width+1,'Calendar exceeds phone width '+width);
      check(layout.bodyWidth<=layout.width+1,'Calendar retains desktop minimum width '+width);
      check(layout.panels.length===2&&layout.panels[1].top>=layout.panels[0].bottom-1,'Both month calendars must be fully stacked');
      check(layout.cellHeight>=43.9&&layout.cellWidth>=43.9,'Calendar cells must retain 44 px touch targets');
      if(width===393)await page.screenshot({path:'output/playwright/mobile-refined-date-range.png',animations:'disabled'});
      const firstMonth=calendar.locator('.el-date-range-picker__content.is-left');
      await firstMonth.locator('td.available:not(.prev-month):not(.next-month)').filter({hasText:/^10$/}).click();
      const endMonth=width===393?calendar.locator('.el-date-range-picker__content.is-right'):firstMonth;
      await endMonth.locator('td.available:not(.prev-month):not(.next-month)').filter({hasText:/^12$/}).click();
      await calendar.waitFor({state:'hidden'});
      const from=await page.getByPlaceholder('开始日期',{exact:true}).inputValue(),to=await page.getByPlaceholder('结束日期',{exact:true}).inputValue();
      check(from.endsWith('-10')&&to.endsWith('-12'),'Calendar selection not retained');
      if(width===393)check(from.slice(0,7)!==to.slice(0,7),'Cross-month selection collapsed into the same month');
      calendarWidths.push(width);
    }
    // The merged partially-allocated workflow remains reachable on the phone.
    await page.setViewportSize({width:393,height:852});await visit('/orders');
    await page.locator('.m-order-tabs .el-select__wrapper').click();
    await page.getByRole('option',{name:'部分配货',exact:true}).waitFor();
    await page.keyboard.press('Escape');
    // The common exchange-rate draft survives render-only phone/PC transitions.
    await visit('/finance');await page.locator('main').getByRole('button',{name:'更多',exact:true}).click();
    await page.getByRole('dialog',{name:'更多操作',exact:true}).getByRole('button',{name:'公共汇率',exact:true}).click();
    const rateDrawer=page.getByRole('dialog',{name:'公共核算汇率',exact:true});
    await rateDrawer.getByRole('spinbutton',{name:'核算汇率',exact:true}).fill('7.123456');
    await rateDrawer.getByRole('spinbutton',{name:'核算汇率',exact:true}).press('Tab');await close(rateDrawer);
    await page.setViewportSize({width:1440,height:1000});
    const desktopRate=page.getByRole('spinbutton',{name:'核算汇率',exact:true});await desktopRate.waitFor();
    check(await desktopRate.inputValue()==='7.123456','PC resize discarded exchange-rate draft');
    await page.setViewportSize({width:393,height:852});await page.locator('main').getByRole('button',{name:'更多',exact:true}).click();
    await page.getByRole('dialog',{name:'更多操作',exact:true}).getByRole('button',{name:'公共汇率',exact:true}).click();
    check(await rateDrawer.getByRole('spinbutton',{name:'核算汇率',exact:true}).inputValue()==='7.123456','Phone resize discarded exchange-rate draft');await close(rateDrawer);
    // Landscape is the unchanged tablet/PC editor; its actual save footer must fit.
    await page.setViewportSize({width:852,height:393});await visit('/orders');
    await page.getByRole('button',{name:'＋ 新增订单',exact:true}).click();
    const editor=page.getByRole('dialog',{name:'新增订单',exact:true});await editor.waitFor();await page.waitForLoadState('networkidle');await settle(editor);
    check(await editor.evaluate(el=>{const r=el.getBoundingClientRect();return r.left>=-1&&r.right<=innerWidth+1;}),'Landscape order drawer exceeds viewport');
    check(await editor.getByRole('button',{name:'创建待付款订单',exact:true}).evaluate(el=>{const r=el.getBoundingClientRect();return r.top>=0&&r.bottom<=innerHeight+1;}),'Landscape hides actual order save action');
    await editor.getByRole('button',{name:'取消',exact:true}).click();await editor.waitFor({state:'hidden'});
    // Progressive size editing replaces a wide phone edit matrix, while preview
    // still contains the horizontal matrix inside a bounded scrolling region.
    await page.setViewportSize({width:393,height:852});await visit('/size-charts');
    const dedicated=page.locator('.goods-card').filter({hasText:'MOBILEGOODS'});
    const chartCard=await dedicated.count()?dedicated.first():page.locator('.goods-card').first();
    await chartCard.locator('.goods-card-main').click();
    const chart=page.getByRole('dialog',{name:/^编辑尺码表/});await chart.waitFor();
    check(await chart.locator('.mobile-goods-chart-matrix').isVisible(),'Phone size editor did not expose progressive dimensions');
    await chart.getByRole('textbox',{name:'英文标题',exact:true}).fill('Mobile presentation draft only');
    check(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),'Size chart editor overflows phone');
    await chart.locator('.el-drawer__footer').getByRole('button',{name:'关闭',exact:true}).click();
    const leave=page.getByRole('dialog',{name:'未保存修改',exact:true});await leave.getByRole('button',{name:'确认',exact:true}).click();await chart.waitFor({state:'hidden'});
    await chartCard.getByRole('button',{name:'更多',exact:true}).click();await page.getByRole('button',{name:'预览尺码表',exact:true}).click();
    const preview=page.getByRole('dialog',{name:/^预览尺码表/});await preview.waitFor();await settle(preview);
    await preview.getByText('in',{exact:true}).click();
    check(await preview.evaluate(el=>{const r=el.getBoundingClientRect();return r.width<=innerWidth+1&&r.height<=innerHeight+1;}),'Size chart preview exceeds phone viewport');
    const matrix=preview.locator('.chart-matrix-scroll');
    check(await matrix.evaluate(el=>el.clientWidth<=innerWidth&&el.scrollWidth>=el.clientWidth),'Preview matrix scrolling is not bounded inside the phone');
    await preview.getByRole('button',{name:'关闭',exact:true}).last().click();await preview.waitFor({state:'hidden'});
    check(writes.length===0,'Presentation check performed business writes: '+writes.join(', '));
    check(errors.length===0,'Presentation browser errors: '+errors.join('; '));
    return {passed:true,mobileDateRanges:calendarWidths,fullCalendars:true,crossMonthSelection:true,touchTargets:true,partialAllocationFilter:true,financeResizeRetainsInput:true,landscapeOrderFooter:true,sizeChartMobile:true,businessWrites:0,errors};
  } finally {page.off('pageerror',onError);page.off('request',onRequest);}
}
