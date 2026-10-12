async (page) => {
  if (!page.url().startsWith('http://127.0.0.1:5360/')) throw new Error('Isolated fixture required');
  await page.getByRole('textbox',{name:'账号 / 邮箱'}).fill('admin@gingtto.test');
  await page.getByRole('textbox',{name:'密码',exact:true}).fill('Workbench-Test-2026');
  await page.getByRole('button',{name:'登录工作台',exact:true}).click();
  await page.waitForURL(url => url.pathname === '/dashboard');
  // A fresh navigation avoids carrying the dashboard's in-flight query sync
  // into the product fixture page.
  await page.goto('http://127.0.0.1:5360/products');
  await page.getByRole('button',{name:'编辑',exact:true}).first().waitFor();
}
