async (page) => {
  const base = 'http://127.0.0.1:5380';
  if (!page.url().startsWith(base + '/')) throw new Error('Isolated mobile fixture required');
  await page.getByRole('textbox', { name: '账号 / 邮箱' }).fill('admin@gingtto.test');
  await page.getByRole('textbox', { name: '密码', exact: true }).fill('Workbench-Test-2026');
  await page.getByRole('button', { name: '登录工作台', exact: true }).click();
  await page.waitForURL(url => url.pathname === '/dashboard');
  await page.goto(base + '/orders');
  await page.getByRole('button', { name: '＋ 新增订单', exact: true }).waitFor();
}
