async (page) => {
  if (!page.url().startsWith('http://127.0.0.1:5366/')) throw new Error('Isolated API browser fixture required');
  await page.getByRole('textbox',{name:'账号 / 邮箱'}).fill('admin@gingtto.test');
  await page.getByRole('textbox',{name:'密码',exact:true}).fill('Workbench-Test-2026');
  await page.getByRole('button',{name:'登录工作台'}).click();
  await page.getByRole('button',{name:'开启语音提醒',exact:true}).waitFor();
}
