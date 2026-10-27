// Run through playwright-cli against the guarded local *_test fixture on 5380.
async (page) => {
  const base = 'http://127.0.0.1:5380';
  if (!page.url().startsWith(base + '/')) throw new Error('Isolated mobile fixture required');
  const check = (value, message) => { if (!value) throw new Error(message); };
  const errors = [], results = [];
  const onError = error => errors.push(error.message);
  page.on('pageerror', onError);
  const routes = ['dashboard','orders','inventory','finance','products','size-charts','categories','contracts','presale','store-accounts','admin-users','audit-logs','api-integrations','products/1/edit'];
  for (const width of [360,393,430,768,1024,1440,1920,852]) {
    await page.setViewportSize({ width, height: width === 852 ? 393 : width < 768 ? 852 : 1000 });
    for (const route of routes) {
      await page.goto(base + '/' + route);
      await page.locator('.workspace-content').waitFor();
      await page.waitForLoadState('networkidle');
      if (width < 768) await page.evaluate(() => document.fonts.ready);
      const m = await page.evaluate(() => ({scroll:document.documentElement.scrollWidth, width:innerWidth,
        left:document.querySelector('.workspace-main').getBoundingClientRect().left,
        font:getComputedStyle(document.querySelector('.workspace-content')).fontFamily,
        bottomNav:!!document.querySelector('.mobile-bottom-nav'),
        mobileFontDownloaded:performance.getEntriesByType('resource').some(r => r.name.includes('NotoSansSC') && r.transferSize > 0),
      }));
      check(m.scroll <= width + 1, `Overflow ${route} at ${width}: ${m.scroll}`);
      if (width < 768) {
        check(m.bottomNav, 'Missing mobile navigation: ' + route);
        check(m.font.includes('GINGTTO Mobile'), 'Mobile font differs: ' + route);
      } else {
        check(!m.bottomNav && !m.font.includes('GINGTTO Mobile'), 'Desktop/tablet styles changed: ' + route);
        check(!m.mobileFontDownloaded, 'Desktop downloaded phone-only font: ' + route);
      }
      if (width < 1024) check(m.left === 0, 'Compact sidebar consumes width: ' + route);
      results.push({width, route, overflow:false, phone:width < 768});
      if (width === 393 && !route.includes('/')) await page.screenshot({path:'output/playwright/mobile-real-'+route+'.png',fullPage:true});
      if (width === 768 && route === 'inventory') await page.screenshot({path:'output/playwright/mobile-real-tablet-inventory.png',fullPage:true});
      if (width === 1440 && route === 'orders') await page.screenshot({path:'output/playwright/mobile-real-desktop-orders.png',fullPage:true});
    }
  }
  // Navigation permission filtering and resize must not remount business pages.
  await page.setViewportSize({width:393,height:852});
  await page.goto(base + '/orders'); await page.waitForLoadState('networkidle');
  let reads = 0;
  const countReads = request => { if (/\/api\/admin\/orders\?/.test(request.url())) reads++; };
  page.on('request', countReads);
  await page.setViewportSize({width:1440,height:1000});
  await page.locator('main .el-table').waitFor();
  await page.setViewportSize({width:393,height:852});
  await page.locator('.mobile-bottom-nav').waitFor();
  check(reads === 0, 'Resize repeated business queries'); page.off('request', countReads);
  await page.getByRole('navigation',{name:'快捷导航'}).getByRole('button',{name:'全部',exact:true}).click();
  const menu = page.getByRole('dialog',{name:'全部模块',exact:true});
  await menu.getByRole('link',{name:'API 对接',exact:true}).waitFor();
  check(await menu.locator('a').count() === 13, 'Module count differs from actual permissions');
  await menu.getByRole('link',{name:'库存管理',exact:true}).click();
  await menu.waitFor({state:'hidden'});
  await page.waitForURL(url => url.pathname === '/inventory');
  check(!errors.length, 'Uncaught browser errors: ' + errors.join('; '));
  page.off('pageerror', onError);
  return {passed:true,layoutChecks:results.length, results, fontUnified:true, desktopFontUnchanged:true,
    desktopNoPhoneFontDownload:true, resizeNoDuplicateReads:true, navigationModules:13, errors};
}
