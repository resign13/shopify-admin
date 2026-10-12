export function sortStyles(items) {
  return [...items].sort((a, b) => Date.parse(b.firstListedAt) - Date.parse(a.firstListedAt) || b.firstProductId - a.firstProductId)
}
export function selectedStyles(codes, items, mode) {
  const lookup = new Map(items.map(item => [item.styleCode, item]))
  const rows = codes.map(code => lookup.get(code) || { styleCode: code, variants: [], missing: true, name: '款号已变更或移除，请重新选择' })
  return mode === 'manual' ? rows : [...sortStyles(rows.filter(r => !r.missing)), ...rows.filter(r => r.missing)]
}
export function moveStyle(codes, from, to) {
  const next = [...codes]
  if (from < 0 || to < 0 || from >= next.length || to >= next.length) return next
  next.splice(to, 0, next.splice(from, 1)[0])
  return next
}
