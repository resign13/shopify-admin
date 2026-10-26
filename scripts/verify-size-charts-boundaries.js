async page=>{
 await page.getByRole('row').filter({hasText:'CS2211'}).getByRole('button',{name:'编辑',exact:true}).click();
 const d=page.getByRole('dialog',{name:'编辑尺码表 · CS2211'});
 await d.getByRole('button',{name:'＋ 添加维度'}).click();
 await d.getByRole('textbox',{name:'维度 10 中文名称',exact:true}).fill('外长');
 await d.getByRole('textbox',{name:'维度 10 英文名称',exact:true}).fill('Outseam');
 await d.getByRole('textbox',{name:'外长 28',exact:true}).fill('100.5');
 await d.getByRole('combobox',{name:'整款单位'}).locator('xpath=ancestor::div[contains(@class,"el-select__wrapper")]').click();await page.getByRole('option',{name:'英寸 in'}).click();
 const unit=page.getByRole('dialog',{name:'换算整款单位',exact:true});await unit.getByRole('button',{name:'确认',exact:true}).click();
 if(await d.getByRole('textbox',{name:'外长 28',exact:true}).inputValue()!=='39.57')throw Error('standard conversion failed');
 const response=page.waitForResponse(r=>r.url().endsWith('/size-charts/save'));await d.getByRole('button',{name:'保存尺码表'}).click();if((await response).status()!==200)throw Error('custom save failed');
 await d.getByRole('textbox',{name:'外长 28',exact:true}).fill('101');
 await d.getByRole('button',{name:'关闭',exact:true}).click();await page.getByRole('dialog',{name:'未保存修改',exact:true}).getByRole('button',{name:'取消',exact:true}).click();
 if(await d.getByRole('textbox',{name:'外长 28',exact:true}).inputValue()!=='101')throw Error('draft lost');
 await d.getByRole('button',{name:'关闭',exact:true}).click();await page.getByRole('dialog',{name:'未保存修改',exact:true}).getByRole('button',{name:'确认',exact:true}).click();
 await page.getByRole('row').filter({hasText:'CS2211'}).getByRole('button',{name:'编辑',exact:true}).click();
 if(await d.getByRole('textbox',{name:'外长 28',exact:true}).inputValue()!=='39.57')throw Error('unsaved leaked');
 await d.getByRole('textbox',{name:'外长 28',exact:true}).locator('xpath=ancestor::tr').getByRole('button',{name:'删除',exact:true}).click();
 await page.getByRole('dialog',{name:'删除维度',exact:true}).getByRole('button',{name:'取消',exact:true}).click();
 await d.getByRole('button',{name:'关闭',exact:true}).click();
 await page.getByRole('button',{name:'导入覆盖',exact:true}).click();
 const upload=page.getByRole('dialog',{name:'导入商品尺码表',exact:true});
 const preview=page.waitForResponse(r=>r.url().endsWith('/size-charts/import/preview'));
 await upload.locator('input[type=file]').setInputFiles('output/playwright/size-charts-import.xlsx');
 const result=await (await preview).json();if(!result.errors.length)throw Error('stale template not rejected');
 if(!(await upload.getByRole('button',{name:'确认覆盖',exact:true}).isDisabled()))throw Error('conflict confirmation enabled');
 await upload.getByRole('button',{name:'取消',exact:true}).click();
 return {passed:true,checks:['custom dimension','whole-style cm to in conversion','cancel deletion','unsaved cancel/discard','stale workbook blocked']};
}


