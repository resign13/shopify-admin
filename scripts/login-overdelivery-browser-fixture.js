async (page) => {
  if (!page.url().startsWith('http://127.0.0.1:5359/')) throw new Error('Isolated browser fixture required');
  await page.getByRole('textbox',{name:'账号 / 邮箱'}).fill('admin@gingtto.test');
  await page.getByRole('textbox',{name:'密码',exact:true}).fill('Workbench-Test-2026');
  await page.getByRole('button',{name:'登录工作台',exact:true}).click();
  // Wait for the login redirect to settle before navigating again. Otherwise
  // its delayed router push can overwrite the inventory link navigation.
  await page.waitForURL(url => url.pathname === '/dashboard');
  await page.getByRole('link',{name:'库存管理',exact:true}).click();
  await page.waitForURL(url => url.pathname === '/inventory');
  await page.getByRole('button',{name:'登记数量',exact:true}).first().waitFor();
}
