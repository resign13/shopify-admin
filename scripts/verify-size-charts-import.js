async page=>{
 await page.getByRole('button',{name:'导入覆盖',exact:true}).click();
 const dialog=page.getByRole('dialog',{name:'导入商品尺码表',exact:true});
 async function upload(){const response=page.waitForResponse(r=>r.url().endsWith('/size-charts/import/preview'));await dialog.locator('input[type=file]').setInputFiles('output/playwright/size-charts-import.xlsx');const res=await response;if(res.status()!==200)throw Error(await res.text());const data=await res.json();if(data.changedCount!==3||data.clearCount!==1)throw Error(JSON.stringify(data));}
 await upload();await page.screenshot({path:'output/playwright/size-charts-import.png'});
 await dialog.getByRole('button',{name:'取消',exact:true}).click();
 await page.getByRole('row').filter({hasText:'CS2211'}).getByRole('button',{name:'编辑',exact:true}).click();
 const drawer=page.getByRole('dialog',{name:'编辑尺码表 · CS2211'});
 if(await drawer.getByRole('textbox',{name:'腰围松量 28',exact:true}).inputValue()!=='28.00')throw Error('cancel wrote values');
 await drawer.getByRole('button',{name:'关闭',exact:true}).click();
 await page.getByRole('button',{name:'导入覆盖',exact:true}).click();await upload();
 await dialog.getByRole('button',{name:'确认覆盖',exact:true}).click();
 const response=page.waitForResponse(r=>r.url().endsWith('/size-charts/import/confirm'));
 await page.getByRole('dialog',{name:'确认导入覆盖',exact:true}).getByRole('button',{name:'确认',exact:true}).click();
 const res=await response;if(res.status()!==200)throw Error(await res.text());
 await dialog.waitFor({state:'hidden'});
 await page.getByRole('row').filter({hasText:'CS2211'}).getByRole('button',{name:'编辑',exact:true}).click();
 for(const [label,value] of [['腰围松量 28',''],['腰围松量 30','31.25'],['臀围 28','0.00']])if(await drawer.getByRole('textbox',{name:label,exact:true}).inputValue()!==value)throw Error(label+' mismatch');
 await drawer.getByRole('button',{name:'关闭',exact:true}).click();
 return {passed:true,checks:['preview differences','cancel preserves saved values','confirm overwrite','blank clears','explicit zero','unchanged cells preserved']};
}


