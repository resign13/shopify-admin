async (page) => {
  if (!page.url().startsWith('http://127.0.0.1:5362/')) throw new Error('Isolated finance fixture required');
  await page.getByRole('textbox',{name:'账号 / 邮箱'}).fill('finance@gingtto.test');
  await page.getByRole('textbox',{name:'密码',exact:true}).fill('Workbench-Test-2026');
  await page.getByRole('button',{name:'登录工作台',exact:true}).click();
  await page.waitForURL(url => url.pathname === '/finance');
  await page.getByRole('button',{name:'查询核算',exact:true}).waitFor();
}
