async page => {
  const errors=[];page.on('pageerror',e=>errors.push(e.message));
  await page.getByRole('row').filter({hasText:'CS2211'}).getByRole('button',{name:'预览',exact:true}).click();
  const dialog=page.getByRole('dialog',{name:'预览尺码表 · CS2211'});
  for(const width of [1920,1366]) {
    await page.setViewportSize({width,height:width===1920?1080:768});
    for(const mode of ['zh','en']) {
      await dialog.getByRole('radio',{name:mode==='zh'?'中文完整表':'英文客户表',exact:true}).locator('..').click();
      await page.waitForFunction(()=>{const e=document.querySelector('.chart-preview-image img');return e?.complete&&e.naturalWidth>0});
      await page.screenshot({path:`output/playwright/size-chart-release-preview-${width}-${mode}.png`,animations:'disabled'});
      const box=await dialog.locator('.chart-preview-window').boundingBox();
      if(box.height>=page.viewportSize().height||Math.abs(box.x-(width-box.width)/2)>2)throw Error('Preview layout overflow');
      if((await dialog.innerText()).includes('独立尺码资料 · 不影响商品库存与售价'))throw Error('Removed footer returned');
      const text=await dialog.locator('.preview-matrix').innerText();
      if(mode==='en'&&(!text.includes('Inseam')||text.includes('Knee')))throw Error('English visibility changed');
    }
  }
  await dialog.getByRole('button',{name:'关闭',exact:true}).click();
  await page.getByRole('row').filter({hasText:'CS2211'}).getByRole('button',{name:'编辑',exact:true}).click();
  const editor=page.getByRole('dialog',{name:'编辑尺码表 · CS2211'});
  await editor.getByRole('textbox',{name:'商品标题',exact:true}).waitFor();
  if(await editor.evaluate(e=>!e.classList.contains('el-drawer')))throw Error('Editor must remain a drawer');
  await editor.getByRole('button',{name:'关闭',exact:true}).click();
  if(errors.length)throw Error(errors.join('\n'));
  return {passed:true,checks:['centered content-sized preview','Chinese and English','real image element','no removed footer','editor remains drawer']};
}
