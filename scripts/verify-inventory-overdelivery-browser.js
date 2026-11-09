// Run against a freshly seeded isolated overdelivery fixture after signing in.
async (page) => {
  if (!page.url().startsWith('http://127.0.0.1:5359/')) throw new Error('Isolated overdelivery fixture required');
  await page.setViewportSize({width:1920,height:1080});
  const open = async () => {
    await page.getByRole('button',{name:'登记数量',exact:true}).first().click();
    // History rows also mention the size; target the editable registration row.
    return page.getByRole('dialog').getByRole('row').filter({hasText:'30/M'}).filter({has:page.getByRole('spinbutton',{name:'次品 M',exact:true})});
  };
  // Desktop and mobile must save the same final targets, including an
  // inspection balance that returns to zero within one edit.
  for (const mobile of [false, true]) {
    await page.setViewportSize(mobile ? {width:390,height:844} : {width:1920,height:1080});
    const edit = async () => {
      await page.getByRole('button',{name:mobile ? '登记' : '登记数量',exact:true}).first().click();
      const dialog=page.getByRole('dialog');
      if (!mobile) return dialog.getByRole('row').filter({has:page.getByRole('spinbutton',{name:'次品 M',exact:true})});
      const registration=dialog.getByTestId('mobile-inventory-registration');
      await registration.getByRole('navigation',{name:'登记真实尺码',exact:true}).getByRole('button',{name:/(^|\/)M$/}).click();
      return registration.locator('.m-registration-card').filter({has:page.getByRole('spinbutton',{name:'次品 M',exact:true})});
    };
    const quantity = (row, stage) => row.getByRole('spinbutton',{name:stage+' M',exact:true});
    const enter = async (row, stage, value) => {
      await quantity(row,stage).fill(value);
      await quantity(row,stage).press('Tab');
    };
    let draft=await edit();
    await enter(draft,'待验货','60');
    await enter(draft,'待验货','');
    if (await quantity(draft,'待验货').inputValue()!=='60' || await quantity(draft,'合同未送').inputValue()!=='40') throw new Error('Blank input changed accepted quantities');
    await enter(draft,'合格','60');
    if (await quantity(draft,'待验货').inputValue()!=='0') throw new Error('Qualification did not consume draft arrival');
    await page.getByRole('button',{name:'保存修改',exact:true}).click();
    draft=await edit();
    for (const [stage,value] of [['合同未送','40'],['待验货','0'],['合格','60']]) {
      if (await quantity(draft,stage).inputValue()!==value) throw new Error(`Saved ${stage} differs from preview, mobile=${mobile}`);
    }
    await enter(draft,'合格','0');
    await enter(draft,'待验货','0');
    await page.getByRole('button',{name:'保存修改',exact:true}).click();
    draft=await edit();
    for (const [stage,value] of [['合同未送','100'],['待验货','0'],['合格','0']]) {
      if (await quantity(draft,stage).inputValue()!==value) throw new Error(`Reversal did not restore ${stage}, mobile=${mobile}`);
    }
    await page.getByRole('dialog').getByRole('button',{name:'取消',exact:true}).click();
  }
  await page.setViewportSize({width:1920,height:1080});
  let row=await open();
  // Real typing (not fill alone) previously accepted each prefix, then rolled
  // back to 11 when 116 was rejected. No transfer occurs before committing.
  const inspection=row.getByRole('spinbutton',{name:'待验货 M',exact:true});
  await inspection.fill('');
  await inspection.pressSequentially('116',{delay:60});
  if (await row.getByRole('spinbutton',{name:'合同未送 M',exact:true}).inputValue()!=='100') throw new Error('Partial digits changed upstream balance');
  await inspection.press('Tab');
  if (await inspection.inputValue()!=='0') throw new Error('Rejected full input kept a partial prefix');
  for (const [amount,remaining] of [['60','40'],['68','32'],['59','41'],['0','100']]) {
    await inspection.fill('');
    await inspection.pressSequentially(amount,{delay:60});
    await inspection.press('Tab');
    if (await inspection.inputValue()!==amount || await row.getByRole('spinbutton',{name:'合同未送 M',exact:true}).inputValue()!==remaining) throw new Error('Complete quantity did not debit exactly');
  }
  await row.getByRole('spinbutton').nth(2).fill('116');
  await row.getByRole('spinbutton').nth(2).press('Tab');
  await page.getByText(/本次最多登记/).waitFor();
  if (await row.getByRole('spinbutton').nth(2).inputValue()!=='0') throw new Error('116 was not rejected');
  await row.getByRole('spinbutton').nth(2).fill('115');
  await row.getByRole('spinbutton').nth(2).press('Tab');
  await page.getByRole('button',{name:'保存修改',exact:true}).click();
  row=await open();
  await row.getByRole('spinbutton',{name:'次品 M',exact:true}).fill('20');
  await row.getByRole('spinbutton',{name:'次品 M',exact:true}).press('Tab');
  await page.getByRole('button',{name:'保存修改',exact:true}).click();
  await page.getByRole('checkbox',{name:'选择当前行',exact:true}).first().locator('..').click();
  await page.getByRole('button',{name:'一键打回',exact:true}).click();
  await page.getByText(/普通次品 5 件退回合同未送，超收次品 15 件不增加未送/).waitFor();
  await page.getByRole('button',{name:'确认打回',exact:true}).click();
  row=await open();
  if (await row.getByRole('spinbutton').nth(2).inputValue()!=='95') throw new Error('Expected saved return balance');
  await row.getByRole('spinbutton').nth(2).fill('101');
  await row.getByRole('spinbutton').nth(2).press('Tab');
  await page.getByText(/本次最多登记/).waitFor();
  if (await row.getByRole('spinbutton').nth(2).inputValue()!=='95') throw new Error('Rejected value was not restored');
  await row.getByRole('spinbutton').nth(2).fill('100');
  await row.getByRole('spinbutton').nth(2).press('Tab');
  if (await row.getByRole('spinbutton').nth(1).inputValue()!=='0') throw new Error('Normal replacement did not consume five remaining units');
  await page.getByRole('button',{name:'保存修改',exact:true}).click();
  row=await open();
  await row.getByRole('spinbutton').nth(4).fill('100');
  await row.getByRole('spinbutton').nth(4).press('Tab');
  await page.getByRole('button',{name:'保存修改',exact:true}).click();
  const selected=page.getByRole('checkbox',{name:'选择当前行',exact:true}).first();
  if (!(await selected.isChecked())) await selected.locator('..').click();
  await page.getByRole('button',{name:'一键入库',exact:true}).click();
  await page.getByRole('button',{name:'确认入库',exact:true}).click();
  row=await open();
  if (await row.getByRole('spinbutton').nth(0).inputValue()!=='110') throw new Error('Receipt stock mismatch');
  await row.getByRole('button',{name:'验货额度 M',exact:true}).click();
  const allowance = page.locator('.allowance-card:visible .allowance-card__remaining');
  await allowance.waitFor();
  if (!(await allowance.innerText()).includes('0')) throw new Error('Zero balance unexpectedly carried quota forward');
  await row.getByRole('button',{name:'验货额度 M',exact:true}).click();
  await page.screenshot({path:'output/overdelivery-browser-verified.png'});

  const pending = row.getByRole('spinbutton',{name:'合同未送 M',exact:true});
  await pending.fill('200'); await pending.press('Tab');
  await page.getByRole('button',{name:'保存修改',exact:true}).click();
  row=await open();
  const arriving=row.getByRole('spinbutton',{name:'待验货 M',exact:true});
  await arriving.fill('110'); await arriving.press('Tab');
  await row.getByRole('button',{name:'验货额度 M',exact:true}).click();
  const explicit = page.getByRole('spinbutton',{name:'本次超收 M',exact:true});
  await explicit.fill('10'); await explicit.press('Tab');
  if (await row.getByRole('spinbutton',{name:'合同未送 M',exact:true}).inputValue()!=='100') throw new Error('Explicit old-batch extra consumed new balance');
  await row.getByRole('button',{name:'验货额度 M',exact:true}).click();
  await page.getByRole('button',{name:'保存修改',exact:true}).click();
  row=await open();
  if (await row.getByRole('spinbutton',{name:'合同未送 M',exact:true}).inputValue()!=='100') throw new Error('Saved explicit extra differs from preview');
  return {desktopAndMobileFinalTargets:true,blankInputRestored:true,combinedTransferAndReversal:true,accepted115:true,rejected116:true,reopened:true,extraReturn:true,zeroBalanceNoCarry:true,explicitExtraPreservesNewPending:true,normalReplacement:true,qualifiedAndReceipt:true};
}
