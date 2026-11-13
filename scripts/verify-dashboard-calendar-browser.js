async page => {
  const base = 'http://127.0.0.1:5395'
  if (!page.url().startsWith(base + '/')) throw new Error('Isolated dashboard *_test fixture required')
  let checks = 0
  const check = (value, message) => { if (!value) throw new Error(message); checks++ }
  const today = await page.evaluate(() => new Intl.DateTimeFormat('en-CA', {
    timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit',
  }).format(new Date()))
  const date = new Date(today + 'T00:00:00Z')
  const iso = d => d.toISOString().slice(0, 10)
  const yesterday = iso(new Date(date.valueOf() - 86400000))
  const lastEnd = new Date(Date.UTC(date.getUTCFullYear(), date.getUTCMonth(), 0))
  const presets = [
    ['today', '今天', today, today],
    ['yesterday', '昨天', yesterday, yesterday],
    ['this_month', '本月', today.slice(0, 8) + '01', today],
    ['last_month', '上月', iso(lastEnd).slice(0, 8) + '01', iso(lastEnd)],
  ]
  await page.setViewportSize({ width: 1440, height: 1000 })
  await page.goto(base + '/dashboard')
  await page.waitForURL(u => u.searchParams.get('datePreset') === 'this_month')
  const range = page.locator('section.panel').first().locator('.el-radio-group').first()
  check((await range.innerText()).replace(/\s/g, '') === '今天昨天本月上月', 'Incorrect desktop shortcuts')
  for (const [key, label, from, to] of presets) {
    const response = page.waitForResponse(r => r.url().includes('view=workbench') &&
      new URL(r.url()).searchParams.get('dateFrom') === from && new URL(r.url()).searchParams.get('dateTo') === to)
    await range.locator('.el-radio-button').filter({ hasText: label }).click()
    check((await response).ok(), 'Date query failed: ' + label)
    await page.waitForURL(u => u.searchParams.get('datePreset') === key)
    check(await range.getByRole('radio', { name: label, exact: true }).isChecked(), 'Shortcut highlight mismatch: ' + label)
    check((await range.locator('.el-radio-button.is-active').innerText()).trim() === label, 'Visible shortcut class mismatch: ' + label)
    check((await page.locator('.filter-scope').innerText()).includes(`${from} 至 ${to}`), 'Applied date label mismatch')
  }
  await page.reload()
  await page.waitForURL(u => u.searchParams.get('datePreset') === 'last_month')
  check(await range.getByRole('radio', { name: '上月', exact: true }).isChecked(), 'Reload lost calendar selection')
  await page.waitForFunction(() => !document.querySelector('.el-skeleton, button.is-loading'))
  await page.screenshot({ path: 'output/playwright/dashboard-calendar-desktop.png', fullPage: false, animations: 'disabled' })
  await page.goto(base + `/dashboard?dateFrom=${yesterday}&dateTo=${yesterday}&datePreset=today`)
  await page.waitForURL(u => u.searchParams.get('datePreset') === 'yesterday')
  check(await range.getByRole('radio', { name: '昨天', exact: true }).isChecked(), 'Stale route preset overrode actual dates')
  await page.setViewportSize({ width: 390, height: 844 })
  const mobile = page.locator('.mobile-dashboard-range')
  check((await mobile.locator('div').innerText()).replace(/\s/g, '') === '今天昨天本月上月', 'Incorrect mobile shortcuts')
  await mobile.getByRole('button', { name: '本月', exact: true }).click()
  await page.waitForURL(u => u.searchParams.get('datePreset') === 'this_month')
  check(await mobile.getByRole('button', { name: '本月', exact: true }).evaluate(el => el.classList.contains('active')), 'Mobile highlight mismatch')
  await mobile.getByRole('button', { name: '经营筛选', exact: true }).click()
  check(await page.locator('#mobile-dashboard-filters .el-date-editor').isVisible(), 'Custom date input removed')
  await page.goto(base + '/dashboard?dateFrom=2026-09-18&dateTo=2026-09-19&datePreset=this_month')
  await page.waitForURL(u => u.searchParams.get('datePreset') === 'custom')
  check(await mobile.locator('div button.active').count() === 0, 'Custom range shows a stale shortcut highlight')
  check(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), 'Phone date controls overflow')
  await page.waitForFunction(() => !document.querySelector('.el-skeleton, button.is-loading'))
  await page.screenshot({ path: 'output/playwright/dashboard-calendar-mobile.png', fullPage: false, animations: 'disabled' })
  return { checks, calendarPresets: true, reload: true, oldRouteNoStaleHighlight: true, customDatesRetained: true, mobile: true }
}
