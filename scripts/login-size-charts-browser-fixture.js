async page => {
  if (!page.url().startsWith('http://127.0.0.1:5366/')) throw Error('Isolated size chart fixture required');
  await page.getByRole('textbox',{name:'账号 / 邮箱'}).fill('admin@gingtto.test');
  await page.getByRole('textbox',{name:'密码',exact:true}).fill('Workbench-Test-2026');
  await page.getByRole('button',{name:'登录工作台'}).click();
  await page.waitForURL(url=>!url.pathname.endsWith('/login'));
  await page.goto('http://127.0.0.1:5366/size-charts');
  await page.setViewportSize({width:1920,height:1080});
  await page.getByRole('row').filter({hasText:'CS2211'}).getByRole('button',{name:'编辑',exact:true}).click();
  return {passed:true};
}
