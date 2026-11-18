async page => {
  const base = 'http://127.0.0.1:5395'
  if (!page.url().startsWith(base + '/')) throw new Error('Isolated dashboard *_test fixture required')
  let checks = 0
  const check = (value, message) => { if (!value) throw new Error(message); checks++ }
  const top = page.getByRole('form', { name: '经营概览筛选', exact: true })
  const lower = page.getByRole('form', { name: '款号商品表现', exact: true })
  const panel = page.locator('.style-performance-panel')
  const displayed = form => form.locator('.el-range-input').evaluateAll(inputs => inputs.map(i => i.value).join('/'))
  const checkDateAfterSearch = async () => {
    const date = lower.locator('.style-report-date')
    await date.waitFor()
    check(await lower.getByRole('button', { name:'重置', exact:true, includeHidden:true }).count() === 0, 'Obsolete reset action remains')
    check(!(await date.textContent()).includes('统计日期') &&
      await date.getByLabel('开始日期', {exact:true}).count() === 1 &&
      await date.getByLabel('结束日期', {exact:true}).count() === 1, 'Use accessible start/end names without a visible date caption')
    check(await date.evaluate(el => el.previousElementSibling?.matches('.el-input:first-child') &&
      el.nextElementSibling?.matches('.el-select')), 'Date must follow search and precede category')
    check(await date.evaluate(el => {
      const before = (a,b) => a.width > 0 && b.width > 0 && (a.bottom <= b.top + 1 ||
        (a.top < b.bottom && b.top < a.bottom && a.right <= b.left + 1))
      const d = el.getBoundingClientRect()
      return before(el.previousElementSibling.getBoundingClientRect(), d) && before(d, el.nextElementSibling.getBoundingClientRect())
    }), 'Visible filters must be ordered search, date, category')
  }
  const pick = async (form, first, last) => {
    await form.locator('.el-range-input').first().click()
    const calendar = page.getByRole('grid', { name: /选择日期/ }).first()
    await calendar.getByRole('gridcell', { name: first, exact: true }).click()
    await calendar.getByRole('gridcell', { name: last, exact: true }).click()
  }
  const responseFor = (view, from, to) => page.waitForResponse(response => {
    const url = new URL(response.url())
    return url.pathname === '/api/admin/dashboard' && url.searchParams.get('view') === view &&
      url.searchParams.get('dateFrom') === from && url.searchParams.get('dateTo') === to
  })
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
    check(await displayed(lower) === from + '/' + to, 'Lower dates did not follow top shortcut')
  }
  await page.reload()
  await page.waitForURL(u => u.searchParams.get('datePreset') === 'last_month')
  check(await range.getByRole('radio', { name: '上月', exact: true }).isChecked(), 'Reload lost calendar selection')
  await page.waitForFunction(() => !document.querySelector('.el-skeleton, button.is-loading'))
  await page.screenshot({ path: 'output/playwright/dashboard-calendar-desktop.png', fullPage: false, animations: 'disabled' })
  await page.goto(base + '/dashboard?dateFrom=2026-09-18&dateTo=2026-09-18&stylePage=2&velocityWindow=30')
  await panel.getByText(/显示第 11/).waitFor()
  await checkDateAfterSearch()
  const keyword = lower.getByPlaceholder('搜索款号、颜色 SKU 或商品名称')
  await keyword.fill('未查询的关键词')
  await top.getByRole('combobox', { name: '订单状态筛选' }).press('Enter')
  await page.getByRole('option', { name: '已付款', exact: true }).click()
  await page.keyboard.press('Escape')
  // Neither picker needs a click on 查询. Changing dates must not submit other draft fields.
  for (const [form, first, last, units, daily] of [[lower,'16','17',3,1.5], [top,'18','18',6,6]]) {
    const from = '2026-09-' + first, to = '2026-09-' + last
    const [overview, performance] = await Promise.all([
      responseFor('workbench', from, to), responseFor('style-performance', from, to), pick(form, first, last),
    ])
    const result = await performance.json()
    check((await overview.json()).metrics.units === units && result.summary.units === units, 'Panels fetched different sales periods')
    check(result.items.find(r => r.styleCode === 'GT-2026').averageDailyUnits === daily, 'Wrong period daily average')
    check(result.velocityWindow.dateTo === today && result.velocityWindow.days === 30, 'Report dates moved turnover')
    await page.locator('.metric').filter({ hasText:'下单商品件数' }).getByText(String(units), { exact:true }).waitFor()
    await panel.locator('.style-summary-grid').getByText(units + ' 件', { exact:true }).waitFor()
    await page.waitForURL(u => u.searchParams.get('dateFrom') === from && u.searchParams.get('stylePage') === '1')
    check(await displayed(top) === from + '/' + to && await displayed(lower) === from + '/' + to, 'Range inputs disagree')
    check(await keyword.inputValue() === '未查询的关键词' && !new URL(page.url()).searchParams.has('statuses'), 'Other drafts applied or lost')
  }
  const [turnoverChange] = await Promise.all([
    responseFor('style-performance', '2026-09-18', '2026-09-18'),
    panel.locator('.el-radio-button').filter({ hasText:'近 7 天周转' }).click(),
  ])
  const changed = await turnoverChange.json()
  check(changed.velocityWindow.days === 7 && changed.velocityWindow.dateTo === today &&
    changed.items.find(r => r.styleCode === 'GT-2026')?.averageDailyUnits === 6, 'Turnover switch submitted drafts or changed reporting sales')
  const detail = responseFor('style-detail', '2026-09-18', '2026-09-18')
  await panel.getByRole('button', { name:'GT-2026', exact:true }).click()
  check((await (await detail).json()).velocityWindow.dateTo === today, 'Detail used a different turnover date')
  await page.keyboard.press('Escape')
  const [exportRequest, download] = await Promise.all([
    page.waitForRequest(r => new URL(r.url()).pathname === '/api/admin/dashboard/style-performance/export'),
    page.waitForEvent('download'), panel.getByRole('button', {name:'导出 Excel',exact:true}).click(),
  ])
  const exported = new URL(exportRequest.url()).searchParams
  check(exported.get('dateFrom') === '2026-09-18' && exported.get('dateTo') === '2026-09-18' &&
    !exported.get('keyword') && !exported.get('statuses') && !await download.failure(), 'Export did not use applied shared filters')
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
  await mobile.getByRole('button', { name: '经营筛选', exact: true }).click()
  await lower.getByRole('button', { name: '更多筛选', exact: true }).click()
  check(await lower.locator('.el-range-input').first().isVisible(), 'Phone lower date picker missing')
  await checkDateAfterSearch()
  const mobileQuery = responseFor('style-performance', '2026-09-16', '2026-09-18')
  await pick(lower, '16', '18')
  check((await mobileQuery).ok() && await displayed(page.locator('#mobile-dashboard-filters')) === '2026-09-16/2026-09-18', 'Mobile lower date not applied to upper picker')
  check(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), 'Phone date controls overflow')
  await page.waitForFunction(() => !document.querySelector('.el-skeleton, button.is-loading'))
  await page.screenshot({ path: 'output/playwright/dashboard-calendar-mobile.png', fullPage: false, animations: 'disabled' })
  return { checks, bidirectionalDates: true, retainedDrafts: true, fixedTurnover: true, detailAndExport: true, mobile: true }
}
