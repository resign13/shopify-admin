import assert from 'node:assert/strict'
import { test } from 'node:test'
import { dashboardDatePresets, dashboardToday, dashboardPresetDates, dashboardDateFilter, matchDashboardPreset } from './dashboardDates.js'

test('dashboard shortcuts use today, yesterday, month-to-date and previous calendar month', () => {
  assert.deepEqual(dashboardDatePresets.map(p => p.label), ['今天', '昨天', '本月', '上月'])
  const today = '2026-11-13'
  assert.deepEqual(dashboardPresetDates('today', today), [today, today])
  assert.deepEqual(dashboardPresetDates('yesterday', today), ['2026-11-12', '2026-11-12'])
  assert.deepEqual(dashboardPresetDates('this_month', today), ['2026-11-01', today])
  assert.deepEqual(dashboardPresetDates('last_month', today), ['2026-10-01', '2026-10-31'])
  assert.deepEqual(dashboardDateFilter({}, today), { preset: 'this_month', dates: ['2026-11-01', today] })
})

test('Beijing date remains correct across UTC midnight and client timezones', () => {
  assert.equal(dashboardToday(new Date('2026-11-12T15:59:59Z')), '2026-11-12')
  assert.equal(dashboardToday(new Date('2026-11-12T16:00:00Z')), '2026-11-13')
  assert.equal(dashboardToday(new Date('2026-11-13T23:00:00-08:00')), '2026-11-14')
})

test('calendar presets handle January, leap years, short months and month-end', () => {
  assert.deepEqual(dashboardPresetDates('last_month', '2026-01-31'), ['2025-12-01', '2025-12-31'])
  assert.deepEqual(dashboardPresetDates('last_month', '2024-03-31'), ['2024-02-01', '2024-02-29'])
  assert.deepEqual(dashboardPresetDates('last_month', '2025-03-01'), ['2025-02-01', '2025-02-28'])
  assert.deepEqual(dashboardPresetDates('yesterday', '2026-01-01'), ['2025-12-31', '2025-12-31'])
  assert.deepEqual(dashboardPresetDates('this_month', '2026-11-30'), ['2026-11-01', '2026-11-30'])
})

test('restored routes highlight only the preset matching the actual requested range', () => {
  const today = '2026-11-13'
  assert.deepEqual(dashboardDateFilter({ datePreset: 'yesterday' }, today), { preset: 'yesterday', dates: ['2026-11-12', '2026-11-12'] })
  assert.equal(dashboardDateFilter({ dateFrom: today, dateTo: today, datePreset: 'last_month' }, today).preset, 'today')
  assert.equal(dashboardDateFilter({ dateFrom: '2026-11-04', dateTo: '2026-11-07' }, today).preset, 'custom')
  assert.equal(dashboardDateFilter({ dateFrom: '2026-10-01', dateTo: '2026-10-31', datePreset: 'last_month' }, today).preset, 'last_month')
  assert.equal(matchDashboardPreset(['2026-11-01', '2026-11-01'], 'this_month', '2026-11-01'), 'this_month')
  assert.equal(matchDashboardPreset(['2026-11-01', '2026-11-01'], 'today', '2026-11-01'), 'today')
})

test('legacy bookmarks retain explicit dates and rolling ranges without stale shortcut selection', () => {
  const today = '2026-11-13'
  assert.deepEqual(dashboardDateFilter({ datePreset: '7' }, today), { dates: ['2026-11-07', today], preset: 'custom' })
  assert.deepEqual(dashboardDateFilter({ dateFrom: '2026-10-15', dateTo: today, datePreset: '30' }, today), { dates: ['2026-10-15', today], preset: 'custom' })
  assert.equal(dashboardDateFilter({ dateFrom: today, dateTo: today, datePreset: '1' }, today).preset, 'today')
  assert.equal(dashboardDateFilter({ datePreset: 'not-a-preset' }, today).preset, 'this_month')
})
