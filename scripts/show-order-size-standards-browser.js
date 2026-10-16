// Read-only UI preview against the synthetic fixture; quantities stay in memory.
async (page) => {
  if (!page.url().startsWith('http://127.0.0.1:5360/')) throw new Error('Isolated fixture required');
  page.removeAllListeners('dialog');page.on('dialog',dialog=>dialog.accept());
  await page.setViewportSize({width:1440,height:760});
  await page.goto('http://127.0.0.1:5360/orders');
  await page.getByRole('button',{name:'＋ 新增订单',exact:true}).click();
  await page.getByRole('dialog',{name:'新增订单',exact:true}).getByRole('button',{name:'＋ 添加商品',exact:true}).click();
  const picker=page.getByRole('dialog',{name:'选择商品',exact:true});
  await picker.getByRole('textbox',{name:'选品关键词',exact:true}).fill('DEMO-');
  const query=page.waitForResponse(r=>r.url().includes('/api/admin/products?')&&new URL(r.url()).searchParams.get('keyword')==='DEMO-');
  await picker.getByRole('button',{name:'查询',exact:true}).click();
  await query;await page.waitForFunction(()=>!document.querySelector('.order-quantity-picker .el-loading-mask'));
  const values=[['DEMO-TS100-黑','S',2],['DEMO-TS100-黑','M',3],['DEMO-JN200-蓝','30',4],
    ['DEMO-KD300-白','120',2],['DEMO-SH400-黑','40',1],['DEMO-OS500-灰','均码',5],['DEMO-MIX600-黑','S/28',3]];
  for(const [sku,size,quantity] of values)await picker.getByRole('spinbutton',{name:`${sku} ${size} 数量`,exact:true}).fill(String(quantity));
  await picker.locator('.el-drawer__body').evaluate(el=>{el.scrollTop=0;});
  await picker.screenshot({path:'output/playwright/order-size-standards-independent.png',animations:'disabled'});
  for(const [sku,size] of values) {
    const value=await picker.getByRole('spinbutton',{name:`${sku} ${size} 数量`,exact:true}).inputValue();
    if(value!==String(values.find(v=>v[0]===sku&&v[1]===size)[2]))throw new Error('Real sizes collided');
  }
  return {sixSizeStandards:true,independentRows:true,inputsIsolated:true,previewOnly:true};
}
