export const dashboardDatePresets = [
  { value: 'today', label: '今天' },
  { value: 'yesterday', label: '昨天' },
  { value: 'this_month', label: '本月' },
  { value: 'last_month', label: '上月' },
]
export const defaultDashboardPreset = 'this_month'

export function dashboardToday(now = new Date()) {
  return new Intl.DateTimeFormat('en-CA', {
    timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit',
  }).format(now)
}

export function dashboardPresetDates(value, today = dashboardToday()) {
  const end = new Date(`${today}T00:00:00Z`)
  const start = new Date(end)
  if (value === 'today' || value === '1') return [today, today]
  if (value === 'yesterday') {
    start.setUTCDate(start.getUTCDate() - 1)
    return [start.toISOString().slice(0, 10), start.toISOString().slice(0, 10)]
  }
  if (value === 'this_month') start.setUTCDate(1)
  else if (value === 'last_month') {
    end.setUTCDate(0)
    start.setUTCDate(1)
    start.setUTCMonth(start.getUTCMonth() - 1)
  } else if (value === '7' || value === '30') {
    // Existing bookmarked ranges remain usable, without keeping old shortcuts.
    start.setUTCDate(start.getUTCDate() - Number(value) + 1)
  } else return null
  return [start.toISOString().slice(0, 10), end.toISOString().slice(0, 10)]
}

export function matchDashboardPreset(dates, preferred = '', today = dashboardToday()) {
  const value = preferred === '1' ? 'today' : preferred
  const matches = preset => {
    const range = dashboardPresetDates(preset, today)
    return dates?.[0] === range[0] && dates?.[1] === range[1]
  }
  if (dashboardDatePresets.some(p => p.value === value) && matches(value)) return value
  return dashboardDatePresets.find(p => matches(p.value))?.value || 'custom'
}

export function dashboardDateFilter(query = {}, today = dashboardToday()) {
  const preferred = typeof query.datePreset === 'string' ? query.datePreset : ''
  const explicit = typeof query.dateFrom === 'string' && query.dateFrom && typeof query.dateTo === 'string' && query.dateTo
  const dates = explicit ? [query.dateFrom, query.dateTo]
    : dashboardPresetDates(preferred, today) || dashboardPresetDates(defaultDashboardPreset, today)
  return { dates, preset: matchDashboardPreset(dates, preferred || defaultDashboardPreset, today) }
}
