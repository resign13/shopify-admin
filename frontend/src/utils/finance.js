export const financeCostPageSize = 20;
export const financeToday = () => new Intl.DateTimeFormat('en-CA', {timeZone:'Asia/Shanghai',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date());
export const financeCodes = value => [...new Set(String(value || '').split(/[,，]/).map(v=>v.trim()).filter(Boolean))];
export function financeCostFilters(query) {
  return {styleCodes:financeCodes(Array.isArray(query.styleCodes)?query.styleCodes.join(','):query.styleCodes).join(','),
    keyword:String(query.keyword||'').trim(),category:query.category||'',missingOnly:Boolean(query.missingOnly)};
}
export function financeCostKey(query) {
  const filters=financeCostFilters(query);
  return JSON.stringify({...filters,styleCodes:financeCodes(filters.styleCodes).map(v=>v.toLowerCase()).sort()});
}
export const financeActiveStates = ['pending_payment','partially_allocated','allocated','paid','shipped','completed'];
export function financeReportDates(today=financeToday()) {
  const start=new Date(today+'T00:00:00Z');start.setUTCDate(start.getUTCDate()-29);
  return {dateFrom:start.toISOString().slice(0,10),dateTo:today};
}
// Compare query semantics, not selection order or server decimal formatting.
export function financeReportKey(filters) {
  const set=values=>[...new Set((values||[]).map(String))].sort();
  const rate=Number(filters.exchangeRate);
  return JSON.stringify({dateFrom:filters.dateFrom,dateTo:filters.dateTo,
    customerName:String(filters.customerName||'').trim(),customerId:filters.customerId?String(filters.customerId):null,
    salespersonIds:set(filters.salespersonIds),styleCodes:set(financeCodes(Array.isArray(filters.styleCodes)?filters.styleCodes.join(','):filters.styleCodes)),
    statuses:set(filters.statuses?.length?filters.statuses:financeActiveStates),exchangeRate:Number.isFinite(rate)&&rate>0?rate.toFixed(6):null});
}
export const costValue = value => value === null || value === undefined || value === '' ? null : Number(value).toFixed(2);
export const batchTargets = (styles, selected) => styles.filter(row=>selected.includes(row.styleCode));
export const clearBatchTargets = (styles, selected) => batchTargets(styles,selected).filter(row=>costValue(row.draftCost)!==null);
export function costChanges(styles) {
  return styles.filter(row=>costValue(row.draftCost)!==row.costCny).map(row=>({styleCode:row.styleCode,costCny:costValue(row.draftCost),version:row.version}));
}
