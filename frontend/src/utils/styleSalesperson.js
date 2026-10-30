// The style panel can override the overview owner without changing overview filters.
export function stylePerformanceQuery(global, filters, isAdmin) {
  const query = { ...filters, ...global };
  delete query.styleSalespersonId;
  if (isAdmin && filters.styleSalespersonId) query.salespersonId = filters.styleSalespersonId;
  if (!isAdmin) delete query.salespersonId;
  if (isPersonalStyleScope(query, !isAdmin)) {
    query.risk = "";
    if (["stock", "estimatedDays"].includes(query.sort)) query.sort = "units";
  }
  return query;
}

export function isPersonalStyleScope(query, isSales) {
  return isSales || !!(query.salespersonId && query.salespersonId !== "all");
}

// Export the last successfully applied query, never draft controls or pagination.
export function stylePerformanceExportQuery(appliedQuery) {
  const keys = ["dateFrom", "dateTo", "country", "style", "salespersonId",
    "keyword", "category", "risk", "sort", "direction", "velocityWindow"];
  return Object.fromEntries(keys.filter(key => appliedQuery[key] != null && appliedQuery[key] !== "")
    .map(key => [key, appliedQuery[key]]));
}
