// Run through playwright-cli against the guarded local *_test fixture on 5380.
async (page) => {
  const base = 'http://127.0.0.1:5380';
  if (!page.url().startsWith(base + '/')) throw new Error('Isolated mobile fixture required');
  const check = (value, message) => { if (!value) throw new Error(message); };
  const errors = [], results = [];
  const onError = error => errors.push(error.message);
  page.on('pageerror', onError);
  const routes = ['dashboard','orders','inventory','finance','products','size-charts','categories','contracts','presale','store-accounts','admin-users','audit-logs','api-integrations','products/1/edit'];
  // Wait for the data used by this screen, not 500 ms of silence from every
  // request (including voice polling). Keep all 112 layout checks and fonts.
  const resources = {'store-accounts':['store-users'], 'products/1/edit':['products/1/family'],
    finance:['finance/preferences','finance/options'], 'api-integrations':['api-integrations/me','api-integrations/logs'],
    dashboard:['dashboard?view=workbench','dashboard?view=style-performance']};
  const visit = async route => {
    const responses = (resources[route] || [route]).map(resource => page.waitForResponse(response => {
      const actual = new URL(response.url()), expected = new URL(base + '/api/admin/' + resource);
      return actual.pathname === expected.pathname && [...expected.searchParams].every(([k,v]) => actual.searchParams.get(k) === v);
    }));
    await page.goto(base + '/' + route);
    const loaded = await Promise.all(responses);
    for (const response of loaded) { check(response.ok(), `Failed layout data: ${route}`); await response.finished(); }
    await page.locator('.workspace-content').waitFor();
    if (route === 'dashboard') await page.locator('.chart canvas').waitFor();
    if (route === 'products/1/edit') await page.locator('.editor-layout').waitFor();
    if (route === 'finance' && page.viewportSize().width < 768 && Number((await loaded[0].json()).exchangeRate) > 0) {
      await page.locator('.mf-hero').waitFor();
    }
    await page.waitForFunction(() => ![...document.querySelectorAll('.workspace-content .el-loading-mask, .workspace-content .el-skeleton')].some(el => el.getBoundingClientRect().height && getComputedStyle(el).visibility !== 'hidden'));
  };
  for (const width of [360,393,430,768,1024,1440,1920,852]) {
    await page.setViewportSize({ width, height: width === 852 ? 393 : width < 768 ? 852 : 1000 });
    for (const route of routes) {
      await visit(route);
      if (width < 768) await page.evaluate(() => document.fonts.ready);
      const m = await page.evaluate(() => ({scroll:document.documentElement.scrollWidth, width:innerWidth,
        left:document.querySelector('.workspace-main').getBoundingClientRect().left,
        font:getComputedStyle(document.querySelector('.workspace-content')).fontFamily,
        bottomNav:!!document.querySelector('.mobile-bottom-nav'),
        voicePanel:!!document.querySelector('.voice-panel'),
        voiceTrigger:!!document.querySelector('.mobile-voice-trigger'),
        mobileFontDownloaded:performance.getEntriesByType('resource').some(r => r.name.includes('NotoSansSC') && r.transferSize > 0),
      }));
      check(m.scroll <= width + 1, `Overflow ${route} at ${width}: ${m.scroll}`);
      check(width < 1024 ? !m.voicePanel && !m.voiceTrigger : m.voicePanel && !m.voiceTrigger,
        `Voice reminder visibility incorrect for ${route} at ${width}`);
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
  await visit('orders');
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
