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
