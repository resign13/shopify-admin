// Read-only presentation checks except draft edits; only an isolated *_test fixture.
async (page) => {
  if (!page.url().startsWith('http://127.0.0.1:5359/')) throw new Error('Isolated fixture required');
  await page.setViewportSize({width:1920,height:1080});
  await page.getByRole('button',{name:'登记数量',exact:true}).first().click();
  const dialog = page.getByRole('dialog');
  const row = dialog.getByRole('row').filter({has:page.getByRole('spinbutton',{name:'次品 M',exact:true})});
  await row.waitFor();
  await dialog.evaluate(node => Promise.all(node.getAnimations({subtree:true}).map(animation => animation.finished.catch(()=>{}))));
  const layout = await row.evaluate(node => {
    const inputs=[...node.querySelectorAll('.el-input-number')].map(el=>el.getBoundingClientRect());
    return {height:node.getBoundingClientRect().height,widths:inputs.map(r=>r.width),tops:inputs.map(r=>r.top),controls:node.querySelectorAll('.el-input-number__increase').length};
  });
  if (layout.height > 96 || layout.controls!==6 || Math.max(...layout.tops)-Math.min(...layout.tops)>1 || new Set(layout.widths.map(Math.round)).size!==1) throw new Error(`Unaligned quantities: ${JSON.stringify(layout)}`);
  if (await page.locator('.allowance-card:visible').count()) throw new Error('Quota is not collapsed initially');
  if (await dialog.locator('.registration-table .el-scrollbar__wrap').evaluate(el=>el.scrollWidth>el.clientWidth+2)) throw new Error('Desktop table unexpectedly scrolls horizontally');
  for (const field of ['次品 M', '临时待入库 M']) {
    const input=row.getByRole('spinbutton',{name:field,exact:true});
    const controls=row.locator('.el-input-number').filter({has:page.getByRole('spinbutton',{name:field,exact:true})});
    await controls.getByRole('button',{name:'增加数值',exact:true}).click();
    if (await input.inputValue()!=='1') throw new Error(`Increase control failed: ${field}`);
    await controls.getByRole('button',{name:'减少数值',exact:true}).click();
    if (await input.inputValue()!=='0') throw new Error(`Decrease control failed: ${field}`);
  }

  const quota=row.getByRole('button',{name:'验货额度 M',exact:true});
  await quota.focus(); await quota.press('Enter');
  await page.locator('.allowance-card:visible').waitFor();
  if (!(await page.locator('.allowance-card:visible').innerText()).includes('100 件')) throw new Error('Original contract is missing');
  if (!(await page.locator('.allowance-card:visible .allowance-card__remaining').innerText()).includes('15')) throw new Error('Initial remaining allowance is missing');
  await quota.click();
  await row.getByRole('spinbutton',{name:'待验货 M',exact:true}).fill('115');
  await row.getByRole('spinbutton',{name:'待验货 M',exact:true}).press('Tab');
  await quota.click();
  if (!(await page.locator('.allowance-card:visible .allowance-card__details > div').filter({hasText:'累计已用'}).innerText()).includes('15 件')) throw new Error('Draft quota preview is stale');
  if (!(await page.locator('.allowance-card:visible .allowance-card__remaining').innerText()).includes('登记后剩余额度')) throw new Error('Draft is not labelled');
  await quota.click();
  if (!(await row.locator('.quantity-change__delta.increase').innerText()).includes('+115')) throw new Error('Increase marker missing');
  if (!(await row.locator('.quantity-change__delta.decrease').innerText()).includes('-100')) throw new Error('Decrease marker missing');
  await row.getByRole('spinbutton',{name:'待验货 M',exact:true}).fill('0');
  await row.getByRole('spinbutton',{name:'待验货 M',exact:true}).press('Tab');
  if (!(await dialog.locator('.registration-save-note').innerText()).includes('尚未修改')) throw new Error('Undo not reflected');

  await dialog.getByRole('button',{name:'规则说明',exact:true}).click();
  await page.locator('.registration-rules').waitFor({state:'visible'});
  await dialog.getByRole('button',{name:'规则说明',exact:true}).click();
  const zero=dialog.getByRole('button',{name:'验货额度 Tall XL',exact:true});
  await zero.click();
  await page.locator('.allowance-card:visible').waitFor();
  if (!(await page.locator('.allowance-card:visible').innerText()).includes('尚无采购合同额度')) throw new Error('No-contract explanation missing');
  await zero.click();
  await page.waitForFunction(() => [...document.querySelectorAll('.allowance-card')].every(el => !el.offsetWidth));
  await page.screenshot({path:'output/playwright/inventory-registration-desktop.png'});
  await quota.click();
  const quotaPopover=page.locator('.el-popper:visible').filter({has:page.locator('.allowance-card')});
  await quotaPopover.waitFor();
  // Vue starts the enter transition on the next frame; wait for the settled
  // popover, rather than capturing its initially transparent DOM.
  await page.waitForFunction(() => [...document.querySelectorAll('.el-popper')].some(el => el.querySelector('.allowance-card') && el.offsetWidth && getComputedStyle(el).opacity === '1' && !el.className.includes('enter-')));
  await page.screenshot({path:'output/playwright/inventory-registration-allowance.png'});
  await quota.click();
  await page.waitForFunction(() => [...document.querySelectorAll('.allowance-card')].every(el => !el.offsetWidth));

  await page.setViewportSize({width:390,height:844});
  await row.waitFor();
  await page.waitForFunction(() => document.querySelector('.inventory-registration').getBoundingClientRect().width <= window.innerWidth);
  if (await dialog.evaluate(el=>el.getBoundingClientRect().width>window.innerWidth)) throw new Error('Drawer exceeds narrow viewport');
  await quota.click();
  const popover=page.locator('.el-popper:visible').filter({has:page.locator('.allowance-card')});
  await popover.waitFor();
  if (await popover.evaluate(el=>{const r=el.getBoundingClientRect();return r.left < 0 || r.right>window.innerWidth+1;})) throw new Error('Narrow popover clipped');
  await quota.click();
  await page.waitForFunction(() => [...document.querySelectorAll('.allowance-card')].every(el => !el.offsetWidth));
  await page.screenshot({path:'output/playwright/inventory-registration-mobile.png'});
  await page.setViewportSize({width:1920,height:1080});
  await dialog.getByRole('button',{name:'取消',exact:true}).click();
  return {alignedInputs:true,compactRows:true,stepControls:true,clickAndKeyboardQuota:true,liveDraftPreview:true,changeMarkers:true,noContractExplanation:true,narrowScreen:true,layout};
}
