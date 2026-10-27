// Run-code entry for the local admin-mobile-browser-fixture.py server only.
// That launcher refuses non-local or non-*_test databases. Reuse root's saved
// test session; this script never logs in, seeds, or edits base products 1/2.
async (page) => {
  const base = 'http://127.0.0.1:5380';
  if (new URL(page.url()).origin !== base || page.url().includes('/login')) throw Error('Logged-in isolated 5380 *_test fixture required');
  const check = (condition, text) => { if (!condition) throw Error(text); };
  const results = [], errors = [], run = Date.now().toString(36), style = `MOBILEGOODS${run}`, sku = `${style}-BLUE`;
  page.on('pageerror', error => errors.push(error.message));
  const api = (path, method = 'GET', body) => page.evaluate(async ({ path, method, body }) => {
    if (location.origin !== 'http://127.0.0.1:5380') throw Error('Test origin changed');
    const csrf = await fetch('/api/auth/csrf').then(response => response.json());
    const response = await fetch('/api/admin/' + path, { method, headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': csrf.csrfToken }, ...(body ? { body: JSON.stringify(body) } : {}) });
    if (!response.ok) throw Error(`${path}: ${response.status} ${await response.text()}`);
    return response.json();
  }, { path, method, body });
  const originalPresale = (await api('presale')).config;
  const originalBase = await Promise.all([api('products/1'), api('products/2')]);
  const template = originalBase[0].product;
  const createdCategory = await api('categories', 'POST', { key: `mobile-goods-${run}`, labels: { zh: `手机验收分类 ${run}`, en: 'Mobile Goods QA' }, sortOrder: 999 });
  const category = createdCategory.item || createdCategory.category || createdCategory;
  const gallery = [...(template.gallery || []), template.image, template.image, template.image].filter(Boolean).slice(0, 3);
  const created = await api('products/save-group', 'POST', { versions: {}, products: [{ categoryKey: `mobile-goods-${run}`, familyCode: style, colorGroup: style, title: `手机商品验收 ${run}`, origin: 'China', colorName: '验收蓝', colorHex: '#40638f', productCode: style, sku, slug: style.toLowerCase(), sizes: ['S', 'M', 'L', 'XL', 'XXL'], sizePrices: ['S', 'M', 'L', 'XL', 'XXL'].map(sizeCode => ({ sizeCode, price: 29.9, stock: 20, weightGrams: 420 })), image: gallery[0], gallery, sizeChartImage: template.sizeChartImage, descriptionImage: template.descriptionImage || template.sizeChartImage }] });
  const productId = created.items[0].id;
  check(productId > 2, 'Dedicated product must not replace the base fixtures');
  await page.setViewportSize({ width: 393, height: 852 });
  await page.goto(base + '/products');
  await page.locator('.goods-card').first().waitFor();
  const picture = await page.screenshot({ path: 'output/playwright/refined-goods-products.png', animations: 'disabled' });
  await page.getByRole('button', { name: '商品操作', exact: true }).click();
  await page.getByRole('button', { name: '选择商品 · 批量调整分类', exact: true }).click();
  await page.locator('.goods-card-main').first().click();
  check(await page.locator('.goods-card.is-selected').count() === 1, 'Custom mobile card did not update real table selection');
  await page.locator('.mobile-goods-selection').getByRole('button', { name: '完成', exact: true }).click();
  check(await page.locator('.goods-card.is-selected').count() === 0, 'Leaving selection mode retained selection');
  results.push({ operation: 'real DataTable selection via whole mobile card' });

  // Same real form and route-leave guard; only the presentation is progressive.
  await page.goto(`${base}/products/${productId}/edit`);
  await page.locator('.mobile-editor-tabs').waitFor();
  await page.getByLabel('商品标题', { exact: true }).fill(`手机商品验收已编辑 ${run}`);
  await page.locator('.save-bar').getByRole('button', { name: '取消', exact: true }).click();
  const leave = page.getByRole('dialog', { name: '未保存修改', exact: true });
  await leave.getByRole('button', { name: '取消', exact: true }).click();
  check((await page.getByLabel('商品标题', { exact: true }).inputValue()).includes('已编辑'), 'Cancelled leave discarded product draft');
  await page.locator('.save-bar').getByRole('button', { name: '下一步', exact: true }).click();
  check(await page.locator('#colors').isVisible() && !await page.locator('#basic').isVisible(), 'Phone color step did not activate');
  await page.locator('.save-bar').getByRole('button', { name: '下一步', exact: true }).click();
  check(await page.locator('#sizes').isVisible(), 'Phone size step missing');
  await page.locator('.save-bar').getByRole('button', { name: '下一步', exact: true }).click();
  check(await page.locator('#assets').isVisible(), 'Phone image step missing');
  const saveProduct = page.waitForResponse(response => response.url().endsWith('/api/admin/products/save-group') && response.request().method() === 'POST');
  await page.getByRole('button', { name: '保存商品', exact: true }).click();
  check((await saveProduct).ok(), 'Real product save failed');
  await page.waitForURL(/\/products(?:\?|$)/);
  results.push({ operation: 'product progressive steps, dirty retention, real save', productId });

  await page.goto(base + '/size-charts');
  const chartCard = page.locator('.goods-card').filter({ hasText: style });
  await chartCard.getByRole('button').first().click();
  const chart = page.getByRole('dialog', { name: `编辑尺码表 · ${style}`, exact: true });
  await chart.getByLabel('英文标题', { exact: true }).fill('Mobile Goods Size Chart');
  await chart.locator('.mobile-goods-measurements input').first().fill('72');
  const saveChart = page.waitForResponse(response => response.url().endsWith('/api/admin/size-charts/save') && response.request().method() === 'POST');
  await chart.getByRole('button', { name: '保存尺码表', exact: true }).click();
  check((await saveChart).ok(), 'Real size chart save failed');
  await chart.locator('.el-drawer__footer').getByRole('button', { name: '关闭', exact: true }).click();
  await chartCard.getByRole('button', { name: '更多', exact: true }).click();
  await page.getByRole('button', { name: '预览尺码表', exact: true }).click();
  await page.getByRole('dialog', { name: `预览尺码表 · ${style}`, exact: true }).waitFor();
  await page.screenshot({ path: 'output/playwright/refined-goods-chart-preview.png', animations: 'disabled' });
  await page.getByRole('dialog', { name: `预览尺码表 · ${style}`, exact: true }).getByRole('button', { name: '关闭', exact: true }).last().click();
  results.push({ operation: 'size chart mobile dimension editor, save and preview', style });

  await page.goto(base + '/categories');
  const categoryCard = page.locator('.goods-card').filter({ hasText: `手机验收分类 ${run}` });
  await categoryCard.getByRole('button').first().click();
  const categoryEditor = page.getByRole('dialog', { name: '编辑分类', exact: true });
  await categoryEditor.getByLabel('英文名称', { exact: true }).fill('Mobile Goods QA Updated');
  const saveCategory = page.waitForResponse(response => response.url().includes('/api/admin/categories/') && response.request().method() === 'PUT');
  await categoryEditor.getByRole('button', { name: '保存分类', exact: true }).click();
  check((await saveCategory).ok(), 'Dedicated category edit failed');
  results.push({ operation: 'real category edit', categoryId: category.id });

  // Upload a real PNG through purpose=contract, without touching source fixtures.
  await page.goto(base + '/contracts');
  await page.getByRole('button', { name: '合同操作', exact: true }).click();
  await page.getByRole('button', { name: '新建采购合同', exact: true }).click();
  const contract = page.getByRole('dialog', { name: '新建采购合同', exact: true });
  await contract.getByLabel('甲方（必填）', { exact: true }).fill('手机流程验收甲方');
  await contract.getByLabel('乙方 / 工厂名称（必填）', { exact: true }).fill(`手机验收工厂 ${run}`);
  await contract.getByLabel('合同号（必填）', { exact: true }).fill(`MOBILE-CONTRACT-${run}`);
  await contract.getByPlaceholder('选择交货日期').fill('2026-12-20');
  await contract.getByPlaceholder('选择交货日期').press('Tab');
  const upload = input => input.setInputFiles({ name: 'mobile-goods-proof.png', mimeType: 'image/png', buffer: picture });
  await upload(contract.locator('input[type=file]').first());
  await contract.locator('.image-tile').first().waitFor();
  await contract.getByRole('button', { name: '下一步', exact: true }).click();
  await contract.getByRole('button', { name: '选择已有商品', exact: true }).click();
  const picker = page.getByRole('dialog', { name: '选择商品', exact: true });
  await picker.getByPlaceholder('标题、款式或 SKU').fill(sku);
  await picker.getByRole('button', { name: '查询', exact: true }).click();
  await picker.getByRole('button', { name: '加入', exact: true }).first().click();
  await picker.locator('.el-drawer__close-btn').click();
  await contract.locator('.size-grid input').nth(1).fill('10');
  await contract.locator('.size-grid input').nth(1).press('Tab');
  await upload(contract.locator('.contract-images input[type=file]').nth(0));
  await contract.locator('.contract-images .image-tile').first().waitFor();
  await upload(contract.locator('.contract-images input[type=file]').nth(1));
  await contract.locator('.contract-images .image-tile').nth(1).waitFor();
  await contract.getByRole('button', { name: '下一步', exact: true }).click();
  await page.screenshot({ path: 'output/playwright/refined-goods-contract-confirm.png', animations: 'disabled' });
  const createContract = page.waitForResponse(response => response.url().endsWith('/api/admin/contracts') && response.request().method() === 'POST');
  await contract.getByRole('button', { name: /^确认创建/ }).click();
  const createdContract = await createContract;
  check(createdContract.ok(), 'Contract creation failed');
  const contractRecord = (await createdContract.json()).item;
  const detail = page.getByRole('dialog', { name: `${contractRecord.contractNo} · 合同详情`, exact: true });
  const downloadContract = page.waitForEvent('download');
  await detail.getByRole('button', { name: '导出合同 Excel', exact: true }).click();
  const contractFile = await downloadContract;
  check(!await contractFile.failure(), 'Contract workbook download failed');
  await contractFile.saveAs(`output/playwright/refined-goods-contract-${run}.xlsx`);
  await detail.getByRole('button', { name: '取消合同', exact: true }).click();
  const cancelContract = page.getByRole('dialog', { name: '取消合同', exact: true });
  const cancellation = page.waitForResponse(response => response.url().endsWith(`/api/admin/contracts/${contractRecord.id}/cancel`) && response.request().method() === 'POST');
  await cancelContract.getByRole('button', { name: '确认', exact: true }).click();
  check((await cancellation).ok(), 'Dedicated contract cancellation failed');
  check((await api(`inventory/${productId}`)).product.sizePrices.find(row => row.sizeCode === 'M').contractPending === 0, 'Dedicated contract pending did not roll back');
  results.push({ operation: 'real contract three steps, PNG attachments, Excel export, cancel', contractId: contractRecord.id });

  try {
    await page.goto(base + '/presale');
    await page.getByRole('button', { name: '选品操作', exact: true }).click();
    await page.getByRole('button', { name: '添加完整款号', exact: true }).click();
    const presalePicker = page.getByRole('dialog', { name: '添加完整款号（全部颜色）', exact: true });
    await presalePicker.getByPlaceholder('搜索款号、名称、颜色或 SKU').fill(style);
    await presalePicker.locator('.mobile-record-select').first().click();
    await presalePicker.getByRole('button', { name: '添加 1 款', exact: true }).click();
    check(await page.locator('.mobile-goods-selection').isVisible(), 'Presale dirty save bar missing');
    const savePresale = page.waitForResponse(response => response.url().endsWith('/api/admin/presale') && response.request().method() === 'PUT');
    await page.getByRole('button', { name: '保存修改', exact: true }).click();
    check((await savePresale).ok(), 'Real presale save failed');
    await page.getByRole('button', { name: '选品操作', exact: true }).click();
    await page.getByRole('button', { name: '调整展示顺序', exact: true }).click();
    await page.locator('.mobile-action-sheet:visible').waitFor({ state: 'hidden' });
    await page.screenshot({ path: 'output/playwright/refined-goods-presale.png', animations: 'disabled' });
    check((await api('presale')).config.styleCodes.includes(style), 'Saved presale missing complete style');
    results.push({ operation: 'presale real full-style picker and persisted draft', style });
  } finally {
    const latest = (await api('presale')).config;
    await api('presale', 'PUT', { ...originalPresale, version: latest.version });
  }
  const afterBase = await Promise.all([api('products/1'), api('products/2')]);
  check(JSON.stringify(originalBase) === JSON.stringify(afterBase), 'Base product fixtures 1/2 changed');
  check(!errors.length, errors.join('\n'));
  return { passed:true, results, errors, baseFixturesUnchanged: true, testOrigin: base, dedicatedStyle: style };
}
