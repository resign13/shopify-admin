async page => {
  if (!page.url().startsWith('http://127.0.0.1:5366/')) throw Error('Isolated fixture required');
  await page.getByRole('row').filter({hasText:'CS2211'}).getByRole('button',{name:'编辑',exact:true}).click();
  const editor=page.getByRole('dialog',{name:'编辑尺码表 · CS2211'});
  for (const [size,value] of [['28','2.54'],['30','100.50'],['32','0'],['S/28','']]) {
    await editor.getByRole('textbox',{name:`臀围 ${size}`,exact:true}).fill(value);
  }
  const saved=page.waitForResponse(r=>r.url().endsWith('/size-charts/save'));
  await editor.getByRole('button',{name:'保存尺码表',exact:true}).click();
  if ((await saved).status()!==200) throw Error('Setup save failed');
  await editor.getByRole('button',{name:'关闭',exact:true}).click();
  async function detail() {
    return page.evaluate(async()=>{
      const r=await fetch('/api/admin/size-charts/detail?styleCode=CS2211');
      if (!r.ok) throw Error('Detail failed');return r.json();
    });
  }
  const original=await detail(), writes=[];
  const record=r=>{if(r.method()==='POST' && /\/size-charts\/(save|import\/confirm)$/.test(r.url()))writes.push(r.url());};
  page.on('request',record);
  await page.getByRole('row').filter({hasText:'CS2211'}).getByRole('button',{name:'预览',exact:true}).click();
  const dialog=page.getByRole('dialog',{name:'预览尺码表 · CS2211'});
  if (!(await dialog.getByRole('radio',{name:'cm',exact:true}).isChecked())) throw Error('Saved cm not selected');
  const results=[];
  for (const unit of ['in','cm']) {
    await dialog.getByRole('radio',{name:unit,exact:true}).locator('..').click();
    for (const [language,mode,hip] of [['中文完整表','maintenance','臀围'],['英文客户表','english','Hip']]) {
      await dialog.getByRole('radio',{name:language,exact:true}).locator('..').click();
      const row=dialog.locator('.preview-matrix tbody tr').filter({hasText:hip});
      const cells=(await row.locator('td').allTextContents()).map(t=>t.trim());
      const expected=[hip,unit,...(unit==='in'?['1.00','39.57','0.00','—']:['2.54','100.50','0.00','—'])];
      if(JSON.stringify(cells)!==JSON.stringify(expected))throw Error(JSON.stringify(cells));
      if(await dialog.getByText('有未保存修改',{exact:true}).count())throw Error('Preview dirtied editor');
      const response=page.waitForResponse(r=>r.url().endsWith('/size-charts/export'));
      const downloaded=page.waitForEvent('download');
      await dialog.getByRole('button',{name:'导出当前版本'}).click();
      const exported=await response;
      if(exported.status()!==200 || exported.request().postDataJSON().unit!==unit)throw Error('Export unit mismatch');
      await(await downloaded).saveAs(`output/playwright/size-charts-preview-${unit}-${mode}.xlsx`);
      results.push({unit,mode,values:cells.slice(2)});
    }
  }
  for(const width of [1920,1366]) {
    await page.setViewportSize({width,height:width===1920?1080:768});
    await dialog.getByRole('radio',{name:'in',exact:true}).locator('..').click();
    const box=await dialog.locator('.chart-preview-window').boundingBox();
    const actions=await dialog.locator('.chart-preview-actions').boundingBox();
    if(actions.x<box.x || actions.x+actions.width>box.x+box.width || box.height>=page.viewportSize().height)throw Error('Preview controls overflow');
    await page.screenshot({path:`output/playwright/size-charts-preview-unit-${width}.png`,animations:'disabled'});
  }
  await page.keyboard.press('Escape');await dialog.waitFor({state:'hidden'});
  if(await page.getByRole('dialog',{name:'未保存修改',exact:true}).count())throw Error('Preview requested save');
  if(JSON.stringify(await detail())!==JSON.stringify(original)||writes.length)throw Error('Preview or export changed saved chart');
  await page.getByRole('row').filter({hasText:'CS2211'}).getByRole('button',{name:'预览',exact:true}).click();
  if(!(await dialog.getByRole('radio',{name:'cm',exact:true}).isChecked()))throw Error('Reopening did not restore saved unit');
  await dialog.getByRole('button',{name:'关闭',exact:true}).click();
  for(const unit of ['in','cm']) {
    await page.getByRole('button',{name:'导入覆盖',exact:true}).click();
    const importer=page.getByRole('dialog',{name:'导入商品尺码表',exact:true});
    const response=page.waitForResponse(r=>r.url().endsWith('/size-charts/import/preview'));
    await importer.locator('input[type=file]').setInputFiles(`output/playwright/size-charts-preview-${unit}-maintenance.xlsx`);
    const result=await(await response).json();
    if(result.errors.length || result.changedCount!==0)throw Error('Untouched converted workbook changed data');
    await importer.getByRole('button',{name:'取消',exact:true}).click();
  }
  if(JSON.stringify(await detail())!==JSON.stringify(original)||writes.length)throw Error('Import preview changed saved chart');
  page.off('request',record);
  return {passed:true,checks:['readonly cm/in switch','formula and two decimals','blank and zero','no round-trip drift','language switch retains unit','exports match preview','no writes or unsaved prompt','reopen resets to saved unit','1920/1366 layout','converted maintenance import is unchanged'],exports:results};
}
