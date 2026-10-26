async page => {
  const errors=[];page.on('pageerror',e=>errors.push(e.message));
  await page.setViewportSize({width:1920,height:1080});
  await page.context().clearCookies();
  await page.goto('http://127.0.0.1:5367/login');
  await page.getByRole('textbox',{name:'账号 / 邮箱'}).fill('admin@gingtto.test');
  await page.getByRole('textbox',{name:'密码'}).fill('Workbench-Test-2026');
  await page.getByRole('button',{name:'登录工作台'}).click();
  await page.waitForURL(url=>!url.pathname.endsWith('/login'));
  await page.goto('http://127.0.0.1:5367/size-charts');
  await page.getByRole('textbox',{name:'款号或商品标题'}).fill('CS2209');
  const loaded=page.waitForResponse(r=>r.url().includes('/api/admin/size-charts?'));
  await page.getByRole('button',{name:'查询',exact:true}).click();await loaded;
  await page.getByRole('row').filter({hasText:'CS2209'}).first().getByRole('button',{name:'预览',exact:true}).click();
  const drawer=page.getByRole('dialog',{name:'预览尺码表 · CS2209'});
  const results=[];
  for(const width of [1920,1366]) {
    await page.setViewportSize({width,height:width===1920?1080:768});
    for(const mode of ['zh','en']) {
      await drawer.getByRole('radio',{name:mode==='zh'?'中文完整表':'英文客户表',exact:true}).locator('..').click();
      await page.waitForFunction(()=>{const e=document.querySelector('.chart-preview-image img');return e?.complete&&e.naturalWidth>0});
      await page.screenshot({path:`D:/dulizhan/output/playwright/size-chart-preview-window-${width}-${mode}.png`,animations:'disabled'});
      const geometry=await drawer.locator('.chart-preview').evaluate(e=>{
        const summary=e.querySelector('.chart-preview-summary').getBoundingClientRect(),table=e.querySelector('.chart-matrix-scroll').getBoundingClientRect(),image=e.querySelector('.chart-preview-image').getBoundingClientRect();
        return {height:e.getBoundingClientRect().height,verticalGap:table.top-summary.bottom,imageWidth:image.width,imageHeight:image.height,overflow:e.scrollWidth-e.clientWidth};
      });
      if(geometry.verticalGap<0||geometry.verticalGap>17||geometry.overflow>1||geometry.height>530||Math.abs(geometry.imageWidth-geometry.imageHeight)>1)throw Error(JSON.stringify(geometry));
      const label=mode==='en'?'Measurement':'测量维度';
      if(!(await drawer.locator('.preview-matrix').innerText()).includes(label))throw Error('Language switch failed');
      const popup=await drawer.locator(".chart-preview-window").boundingBox();if(popup.height>=700||Math.abs(popup.x-(width-popup.width)/2)>2)throw Error('Preview must be centered and content-sized');
      results.push({width,mode,popupHeight:popup.height,...geometry});
      if(width===1920){const download=page.waitForEvent('download');await drawer.getByRole('button',{name:'导出当前版本'}).click();await(await download).saveAs(`D:/dulizhan/output/playwright/size-chart-preview-window-${mode}.xlsx`);}
    }
  }
  await drawer.getByRole('button',{name:'关闭',exact:true}).click();
  await page.getByRole('row').filter({hasText:'CS2209'}).first().getByRole('button',{name:'编辑',exact:true}).click();
  const editor=page.getByRole('dialog',{name:'编辑尺码表 · CS2209'});
  await editor.getByRole('textbox',{name:'商品标题',exact:true}).waitFor();
  if(await editor.evaluate(e=>!e.classList.contains('el-drawer')))throw Error('Editing drawer changed');
  await editor.getByRole('radio',{name:'英文客户表',exact:true}).locator('..').click();
  await editor.locator('.chart-preview-image img').waitFor();
  await editor.getByRole('button',{name:'关闭',exact:true}).click();
  if(errors.length)throw Error(errors.join('\n'));
  return {passed:true,results,pageErrors:errors};
}
