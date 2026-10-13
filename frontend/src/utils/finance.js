export const financeToday = () => new Intl.DateTimeFormat('en-CA', {timeZone:'Asia/Shanghai',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date());
export const financeCodes = value => [...new Set(String(value || '').split(/[,，]/).map(v=>v.trim()).filter(Boolean))];
export const financeActiveStates = ['pending_payment','allocated','paid','shipped','completed'];
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
export const cellKey = (id, size) => JSON.stringify([id, size]);
export const costValue = value => value === null || value === undefined || value === '' ? null : Number(value).toFixed(2);
export function batchTargets(variants, selected, size) {
  return variants.filter(v=>selected.includes(v.id)).flatMap(v=>v.sizes.filter(s=>!size || s.sizeCode===size).map(s=>({variant:v,size:s})));
}
export const clearBatchTargets = (variants, selected, size) => batchTargets(variants,selected,size).filter(({size})=>costValue(size.draftCost)!==null);
export function costChanges(variants) {
  return variants.flatMap(v=>v.sizes.filter(s=>costValue(s.draftCost)!==s.costCny).map(s=>({productId:v.id,sizeCode:s.sizeCode,costCny:costValue(s.draftCost),version:s.version})));
}
