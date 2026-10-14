async (page) => {
  if (!page.url().startsWith('http://127.0.0.1:5364/')) throw new Error('Isolated department fixture required');
  const assert=(value,message)=>{if(!value)throw new Error(message);};
  if(new URL(page.url()).pathname==='/login'){
    await page.getByRole('textbox',{name:'账号 / 邮箱',exact:true}).fill('admin@gingtto.test');
    await page.getByRole('textbox',{name:'密码',exact:true}).fill('Workbench-Test-2026');
    await page.getByRole('img',{name:'图形验证码图片',exact:true}).waitFor();
    await page.getByRole('textbox',{name:'图形验证码',exact:true}).fill('AB7CD');
    await page.getByRole('button',{name:'登录工作台',exact:true}).click();
    await page.waitForURL(url=>url.pathname==='/dashboard');
    await page.getByRole('link',{name:'后台账号',exact:true}).click();
    await page.getByRole('row').filter({hasText:'finance@gingtto.test'}).getByRole('button',{name:'编辑',exact:true}).click();
  }
  const dialog=page.getByRole('dialog',{name:'编辑账号',exact:true});
  if(await dialog.count()===0)await page.getByRole('row').filter({hasText:'finance@gingtto.test'}).getByRole('button',{name:'编辑',exact:true}).click();
  const labels=['财务管理','经营工作台','商品管理','库存管理','商品分类','订单管理','合同管理','预售管理','商城账号','后台账号','操作日志'];
  for(const label of labels)assert(await dialog.getByRole('checkbox',{name:label,exact:true}).isEnabled(),'Disabled staff module: '+label);
  for(const label of labels)assert(await dialog.getByRole('checkbox',{name:label,exact:true}).isChecked()===['财务管理','合同管理'].includes(label),'Finance default: '+label);
  await dialog.getByText('库存管理',{exact:true}).click();
  await dialog.getByRole('button',{name:'恢复部门默认',exact:true}).click();
  assert(!(await dialog.getByRole('checkbox',{name:'库存管理',exact:true}).isChecked()),'Restore defaults');
  await dialog.getByText('库存管理',{exact:true}).click();
  const [saved]=await Promise.all([
    page.waitForResponse(r=>r.url().includes('/api/admin/admin-users/')&&r.request().method()==='PUT'),
    dialog.getByRole('button',{name:'保存账号',exact:true}).click(),
  ]);
  assert(saved.ok(),'Explicit extra grant save');
  const data=await saved.json();
  assert(data.user.role==='finance'&&data.user.permissions.includes('inventory')&&data.user.permissions.includes('contracts'),'Role preserved and extras saved');
  await dialog.waitFor({state:'hidden'});
  await page.getByRole('row').filter({hasText:'finance@gingtto.test'}).getByRole('button',{name:'编辑',exact:true}).click();
  assert(await dialog.getByRole('checkbox',{name:'库存管理',exact:true}).isChecked(),'Extra grant persisted');
  await page.setViewportSize({width:1100,height:850});
  // Pointer actions wait for the drawer transition before its visual capture.
  await dialog.getByRole('textbox',{name:'*姓名',exact:true}).click();
  await page.screenshot({path:'output/playwright/department-finance-permissions.png'});
  await dialog.getByRole('button',{name:'取消',exact:true}).click();
  return {staffModuleCheckboxesEnabled:true,financeDefaultsOnly:true,restoreDefaults:true,extraGrantSavedAndPersisted:true,roleUnchanged:true};
}
