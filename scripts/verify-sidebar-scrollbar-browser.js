// Run after signing in to the isolated local admin browser fixture.
async (page) => {
  if (!/^http:\/\/127\.0\.0\.1:\d+\//.test(page.url())) {
    throw new Error('An isolated loopback fixture is required');
  }
  const check = (ok, message) => { if (!ok) throw new Error(message); };
  const nav = page.locator('.workspace-sidebar nav');
  const results = [];
  for (const width of [1024, 1440, 1920]) {
    await page.setViewportSize({ width, height: 600 });
    await nav.waitFor();
    await nav.evaluate(el => { el.scrollTop = 0; });
    const state = await nav.evaluate(el => ({
      width: getComputedStyle(el).scrollbarWidth,
      webkitDisplay: getComputedStyle(el, '::-webkit-scrollbar').display,
      overflowY: getComputedStyle(el).overflowY,
      scrollHeight: el.scrollHeight,
      clientHeight: el.clientHeight,
    }));
    check(state.scrollHeight > state.clientHeight, `Fixture must overflow vertically at ${width}`);
    check(state.width === 'none' && state.webkitDisplay === 'none', `Sidebar scrollbar remains visible at ${width}`);
    check(state.overflowY === 'auto', 'Sidebar scrolling was disabled');

    await nav.hover();
    await page.mouse.wheel(0, 600);
    await page.waitForFunction(() => document.querySelector('.workspace-sidebar nav').scrollTop > 0);
    const wheelScroll = await nav.evaluate(el => el.scrollTop);
    await nav.getByRole('link', { name: '财务管理' }).focus();
    await nav.evaluate(el => { el.scrollTop = 0; });
    await nav.getByRole('link', { name: 'API 对接' }).focus();
    const keyboardScroll = await nav.evaluate(el => el.scrollTop);
    check(keyboardScroll > 0, 'Keyboard focus cannot reveal the lower menu');
    check(await nav.getByRole('link', { name: 'API 对接' }).isVisible(), 'Lower menu is unavailable');
    results.push({ width, wheelScroll, keyboardScroll });
  }

  // The document keeps its normal scrollbar; only the desktop sidebar changes.
  check(await page.evaluate(() => getComputedStyle(document.documentElement).scrollbarWidth !== 'none'),
        'Document scrollbar unexpectedly hidden');
  await page.setViewportSize({ width: 390, height: 844 });
  check(await page.locator('.mobile-bottom-nav').isVisible(), 'Mobile navigation changed');
  check(await page.locator('.workspace-sidebar').count() === 0, 'Desktop sidebar leaked into mobile');
  return { sidebarThumbHidden: true, desktop: results, documentScrollbarKept: true, mobileNavigationKept: true };
}
