// Run against a freshly seeded isolated overdelivery fixture after signing in.
async (page) => {
  if (!page.url().startsWith('http://127.0.0.1:5359/')) throw new Error('Isolated overdelivery fixture required');
  const open = async () => {
    await page.getByRole('button',{name:'登记数量',exact:true}).first().click();
    // History rows also mention the size; target the editable registration row.
    return page.getByRole('dialog').getByRole('row').filter({hasText:'30/M'}).filter({has:page.getByRole('spinbutton',{name:'次品 M',exact:true})});
  };
  let row=await open();
  await row.getByRole('spinbutton').nth(2).fill('116');
  await row.getByRole('spinbutton').nth(2).press('Tab');
  await page.getByText(/超出原合同数量累计15%额度/).waitFor();
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
  await page.getByRole('button',{name:'确认打回',exact:true}).click();
  row=await open();
  if (await row.getByRole('spinbutton').nth(2).inputValue()!=='95') throw new Error('Expected saved return balance');
  await row.getByRole('spinbutton').nth(2).fill('101');
  await row.getByRole('spinbutton').nth(2).press('Tab');
  await page.getByText(/超出原合同数量累计15%额度/).waitFor();
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
  const spent = page.locator('.allowance-card:visible .allowance-card__details > div').filter({hasText:'累计已用'});
  await spent.waitFor();
  if (!(await spent.innerText()).includes('15 件')) throw new Error('Receipt reset spent allowance');
  await row.getByRole('button',{name:'验货额度 M',exact:true}).click();
  await page.getByRole('dialog').evaluate(node => Promise.all(node.getAnimations({subtree:true}).map(animation => animation.finished.catch(()=>{}))));
  await page.screenshot({path:'output/overdelivery-browser-verified.png'});
  return {accepted115:true,rejected116:true,reopened:true,extraReturn:true,spentQuotaNotRenewed:true,normalReplacement:true,qualifiedAndReceipt:true};
}
