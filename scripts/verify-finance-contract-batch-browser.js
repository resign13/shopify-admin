// Dedicated *_test fixtures only. Creates its own contracts; never opens production.
async page=>{
  const base=new URL(page.url()).origin;
  if(!['http://127.0.0.1:5362','http://127.0.0.1:5398'].includes(base))throw Error('Isolated finance/contracts fixture required');
  let checks=0;const check=(ok,message)=>{if(!ok)throw Error(message);checks++;};
  const api=(path,method='GET',body)=>page.evaluate(async({path,method,body})=>{
    const csrf=(await fetch('/api/auth/csrf').then(r=>r.json())).csrfToken;
    const r=await fetch('/api/admin/'+path,{method,headers:{'Content-Type':'application/json','X-CSRF-Token':csrf},...(body?{body:JSON.stringify(body)}:{})});
    if(!r.ok)throw Error(path+': '+r.status);return r.json();
  },{path,method,body});
  await page.setViewportSize({width:1920,height:1080});await page.goto(base+'/finance');
  await page.waitForFunction(()=>location.pathname==='/login'||document.querySelector('.profile-button'));
  if(new URL(page.url()).pathname!=='/login'){await page.locator('.profile-button').click();await page.getByRole('menuitem',{name:'退出登录',exact:true}).click();}
  await page.waitForURL(u=>u.pathname==='/login');
  await page.getByRole('textbox',{name:'账号 / 邮箱'}).fill('admin@gingtto.test');await page.getByRole('textbox',{name:'密码',exact:true}).fill('Workbench-Test-2026');
  await page.getByRole('button',{name:'登录工作台',exact:true}).click();await page.waitForURL(u=>u.pathname!=='/login');await page.goto(base+'/finance');
  await page.getByRole('button',{name:'查询核算',exact:true}).waitFor();
  await page.getByRole('spinbutton',{name:'核算汇率',exact:true}).fill('7.123456');
  for(const [placeholder,value] of [['开始日期','2026-09-17'],['结束日期','2026-09-18']]){const input=page.getByPlaceholder(placeholder,{exact:true});await input.fill(value);await input.press('Enter');await input.press('Tab');}
  const [query]=await Promise.all([page.waitForResponse(r=>r.url().endsWith('/finance/reports/query')&&r.request().method()==='POST'),page.getByRole('button',{name:'查询核算',exact:true}).click()]);check(query.status()===200,'Finance query failed');
  await page.getByTestId('finance-order-count').waitFor();
  const countStyle=await page.getByTestId('finance-order-count').locator('strong').evaluate(el=>({size:parseFloat(getComputedStyle(el).fontSize),width:el.getBoundingClientRect().width}));
  check(countStyle.size>=32&&countStyle.width>0,'Order count is not visually prominent');
  check(await page.locator('.finance-summary>article').count()===3,'Monetary summaries changed');
  check(await page.getByTestId('finance-product-count').isVisible(),'Product count missing');
  await page.locator('.finance-overview').screenshot({path:'output/playwright/finance-summary-desktop.png',animations:'disabled'});
  await page.setViewportSize({width:1024,height:1000});check(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),'Finance summary overflows tablet desktop');
  await page.locator('.finance-overview').screenshot({path:'output/playwright/finance-summary-1024.png',animations:'disabled'});
  await page.setViewportSize({width:1440,height:1000});
  const marker='BATCH-'+Date.now();let month='';
  for(let i=0;i<30;i++){
    const item=(await api('contracts','POST',{requestId:crypto.randomUUID(),partyB:'批量验收工厂',contractNo:marker+'-'+String(i+1).padStart(2,'0'),items:[{productId:1,quantities:{M:i+1}}]})).item;
    month=new Date(new Date(item.createdAt).getTime()+8*3600000).toISOString().slice(0,7);
  }
  const before=(await api('inventory/1')).product;
  await page.goto(base+'/contracts?'+new URLSearchParams({keyword:marker,createdMonth:month}));
  await page.locator('.el-table__body-wrapper .el-table__row').first().waitFor();
  check(await page.locator('.el-table__body-wrapper .el-table__row').count()===25,'List pagination changed');
  const controls=await page.locator('.contract-filters').evaluate(el=>[...el.querySelectorAll(':scope>.el-input>.el-input__wrapper,:scope>.el-button')].map(node=>{const r=node.getBoundingClientRect();return {top:r.top,left:r.left,right:r.right,height:r.height};}));
  check(controls.length===4&&controls.every(r=>Math.abs(r.top-controls[0].top)<1&&Math.abs(r.height-32)<1),'Contract filter controls are not aligned');
  check(controls.slice(1).every((r,i)=>Math.abs(r.left-controls[i].right-10)<1),'Contract filter control spacing is uneven');
  await page.locator('.contract-filters').screenshot({path:'output/playwright/contracts-filter-aligned.png',animations:'disabled'});
  const scrollBody=page.locator('.contracts-list-panel .el-table__body-wrapper .el-scrollbar__wrap');
  const tableHeader=page.locator('.contracts-list-panel .el-table__header-wrapper');
  const footer=page.locator('.contracts-list-panel .table-footer');
  check(await scrollBody.evaluate(el=>el.scrollHeight>el.clientHeight&&el.clientHeight>100),'Contracts do not scroll inside the table');
  const headerTop=(await tableHeader.boundingBox()).y;
  await scrollBody.evaluate(el=>el.scrollTop=el.scrollHeight);
  check(Math.abs((await tableHeader.boundingBox()).y-headerTop)<1,'Table header scrolls away with rows');
  check(await footer.evaluate(el=>{const r=el.getBoundingClientRect();return r.top>0&&r.bottom<=innerHeight;}),'Pagination is below the viewport');
  check(await page.evaluate(()=>scrollY===0&&document.documentElement.scrollHeight<=innerHeight+1),'Contract rows still stretch the page');
  await scrollBody.evaluate(el=>el.scrollTop=0);
  await page.locator('.el-table__body-wrapper .el-table__row').first().locator('.el-checkbox').click();
  await Promise.all([page.waitForResponse(r=>r.url().includes('/api/admin/contracts?')&&new URL(r.url()).searchParams.get('page')==='2'),page.getByRole('button',{name:'下一页',exact:true}).click()]);
  await page.waitForFunction(()=>document.querySelectorAll('.el-table__body-wrapper .el-table__row').length===5);
  await page.locator('.el-table__body-wrapper .el-table__row').first().locator('.el-checkbox').click();
  await page.getByText('已选 2 份合同',{exact:true}).waitFor();checks++;
  const setMonth=async value=>{
    const response=page.waitForResponse(r=>r.url().includes('/api/admin/contracts?')&&new URL(r.url()).searchParams.get('createdMonth')===value);
    const picker=page.getByRole('combobox',{name:'合同创建月份',exact:true});await picker.fill(value.replace('-','年')+'月');await picker.press('Enter');await picker.press('Tab');
    check((await response).status()===200,'Month filter failed');
  };
  await setMonth('2000-01');await page.getByText('共 0 条',{exact:true}).waitFor();
  check(await page.getByText('已选 2 份合同',{exact:true}).count()===0,'Month change retained old selection');
  check(await page.getByRole('button',{name:'批量导出 ▾',exact:true}).isDisabled(),'Empty result export still enabled');
  await setMonth(month);await page.locator('.el-table__body-wrapper .el-table__row').first().waitFor();
  for(const i of [0,1])await page.locator('.el-table__body-wrapper .el-table__row').nth(i).locator('.el-checkbox').click();
  let download=page.waitForEvent('download');await page.getByRole('button',{name:'批量导出 ▾',exact:true}).click();await page.getByRole('menuitem',{name:'导出勾选合同（2）',exact:true}).click();
  await(await download).saveAs('output/playwright/contracts-selected.xlsx');checks++;
  download=page.waitForEvent('download');await page.getByRole('button',{name:'批量导出 ▾',exact:true}).click();await page.getByRole('menuitem',{name:'导出筛选全部（30）',exact:true}).click();
  await(await download).saveAs('output/playwright/contracts-filtered.xlsx');checks++;
  check(JSON.stringify((await api('inventory/1')).product)===JSON.stringify(before),'Exports changed inventory');
  check(await footer.evaluate(el=>el.getBoundingClientRect().bottom<=innerHeight),'Selection pushed pagination below viewport');
  await page.screenshot({path:'output/playwright/contracts-batch-desktop.png',animations:'disabled'});
  await page.setViewportSize({width:1440,height:720});
  check(await footer.evaluate(el=>el.getBoundingClientRect().bottom<=innerHeight),'Short desktop viewport hides pagination');
  check(await scrollBody.evaluate(el=>el.scrollHeight>el.clientHeight&&el.clientHeight>80),'Short desktop loses table scroll');
  await page.screenshot({path:'output/playwright/contracts-scroll-short-desktop.png',animations:'disabled'});
  await page.setViewportSize({width:390,height:844});await page.getByRole('combobox',{name:'合同创建月份',exact:true}).waitFor();
  check(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),'Contract month filter overflows mobile');
  await page.screenshot({path:'output/playwright/contracts-month-mobile.png',animations:'disabled',fullPage:true});
  return {passed:true,checks,financeCountsProminent:true,monthFilter:true,crossPageSelection:true,selectionClearedOnMonth:true,selectedExport:2,filteredExport:30,inventoryUnchanged:true,internalTableScroll:true,fixedTableHeader:true,visiblePagination:true,filterControlsAligned:true};
}
