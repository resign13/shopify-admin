async page => {
 const errors=[];page.on('pageerror',e=>errors.push(e.message));
 const drawer=page.getByRole('dialog',{name:'编辑尺码表 · CS2211'});
 await drawer.getByRole('textbox',{name:'商品标题',exact:true}).fill('修身长裤');
 await drawer.getByRole('textbox',{name:'英文标题',exact:true}).fill('Slim fit trousers');
 await drawer.getByRole('textbox',{name:'材质',exact:true}).fill('100% 聚酯纤维');
 await drawer.getByRole('textbox',{name:'英文材质',exact:true}).fill('100% Polyester');
 for(const [dim,base] of [['腰围松量',28],['腰围拉量',32],['臀围',94],['内长',76]]) {
  for(const [i,size] of ['28','30','32','S/28'].entries())await drawer.getByRole('textbox',{name:dim+' '+size,exact:true}).fill(String(base+i*2));
 }
 for(const dim of ['腰围拉量','腿围','膝围','脚口','前浪','后浪'])await drawer.getByRole('checkbox',{name:dim+' 英文展示',exact:true}).locator('..').click();
 await drawer.getByRole('textbox',{name:'脚口 28',exact:true}).fill('0');
 const response=page.waitForResponse(r=>r.url().endsWith('/size-charts/save'));
 await drawer.getByRole('button',{name:'保存尺码表',exact:true}).click();
 const saved=await response;if(saved.status()!==200)throw Error(await saved.text());
 await drawer.getByRole('button',{name:'保存尺码表',exact:true}).waitFor({state:'visible'});
 await drawer.locator('.el-drawer__body').evaluate(e=>e.scrollTop=0);
 await page.screenshot({path:'output/playwright/size-charts-editor.png'});
 const maintenance=page.waitForEvent('download');await drawer.getByRole('button',{name:'导出当前版本'}).click();
 await (await maintenance).saveAs('output/playwright/size-charts-maintenance.xlsx');
 await drawer.getByRole('radio',{name:'英文客户表',exact:true}).locator('..').click();
 const preview=drawer.locator('.chart-preview');
 if((await preview.innerText()).includes('Waist (Stretched)'))throw Error('hidden dimension leaked');
 if((await preview.innerText()).includes('修身'))throw Error('Chinese leaked into customer preview');
 if(await preview.locator('tbody tr').count()!==3)throw Error('expected three English measurements');
 await page.screenshot({path:'output/playwright/size-charts-english.png'});
 const english=page.waitForEvent('download');await drawer.getByRole('button',{name:'导出当前版本'}).click();
 await (await english).saveAs('output/playwright/size-charts-english.xlsx');
 await drawer.getByRole('button',{name:'关闭',exact:true}).click();
 if(errors.length)throw Error(errors.join('\n'));
 return {passed:true,checks:['save measurements','zero value','English visibility','maintenance download','English download'],pageErrors:errors};
}



