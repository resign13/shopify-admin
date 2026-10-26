async page => {
  if (!page.url().startsWith('http://127.0.0.1:5366/')) throw Error('Isolated fixture required');
  await page.getByRole('row').filter({hasText:'CS2211'}).getByRole('button',{name:'编辑',exact:true}).click();
  const d=page.getByRole('dialog',{name:'编辑尺码表 · CS2211'});
  async function switchUnit(label, accept=true) {
    await d.getByRole('combobox',{name:'整款单位'}).locator('xpath=ancestor::div[contains(@class,"el-select__wrapper")]').click();
    await page.getByRole('option',{name:label,exact:true}).click();
    await page.getByRole('dialog',{name:'换算整款单位',exact:true}).getByRole('button',{name:accept?'确认':'取消',exact:true}).click();
  }
  async function assertValue(label,value) {
    if(await d.getByRole('textbox',{name:label,exact:true}).inputValue()!==value)throw Error(label+' mismatch');
  }
  async function exportBoth(unit) {
    for(const [label,mode] of [['中文完整表','maintenance'],['英文客户表','english']]) {
      await d.getByRole('radio',{name:label,exact:true}).locator('..').click();
      if(mode==='english') {
        const units=await d.locator('.preview-matrix tbody tr td:nth-child(2)').allTextContents();
        if(!units.length||units.some(v=>v.trim()!==unit))throw Error('mixed preview units');
      }
      const download=page.waitForEvent('download');await d.getByRole('button',{name:'导出当前版本'}).click();
      await (await download).saveAs(`output/playwright/size-charts-${unit}-${mode}.xlsx`);
    }
    await d.getByRole('radio',{name:'中文完整表',exact:true}).locator('..').click();
  }
  await d.getByRole('combobox',{name:'整款单位'}).waitFor();
  if(await d.getByRole('combobox').count()!==1)throw Error('per-dimension unit selector returned');
  await assertValue('外长 28','39.57');
  await exportBoth('in');
  await switchUnit('厘米 cm',false);await assertValue('外长 28','39.57');
  await switchUnit('厘米 cm');await assertValue('外长 28','100.51');
  await assertValue('腰围松量 28','');await assertValue('脚口 28','0.00');
  await switchUnit('英寸 in');await assertValue('外长 28','39.57');
  await switchUnit('厘米 cm');
  const response=page.waitForResponse(r=>r.url().endsWith('/size-charts/save'));
  await d.getByRole('button',{name:'保存尺码表'}).click();
  const r=await response;const result=await r.json();
  if(r.status()!==200||result.items[0].unit!=='cm'||result.items[0].dimensions.some(x=>x.unit!=='cm'))throw Error('unit save mismatch');
  await exportBoth('cm');
  await page.screenshot({path:'output/playwright/size-charts-unified-units.png',animations:'disabled'});
  await d.getByRole('button',{name:'关闭',exact:true}).click();
  return {passed:true,checks:['one selector per style','cancel conversion','cm/in formula','blank and zero','round-trip precision','saved uniform units','English preview','four unit-specific Excel downloads']};
}

