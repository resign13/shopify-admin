// Removing a chip changes the applied query, never submits the input draft.
export function removeAppliedOrderFilter(query, key, filters, dates) {
  const nextQuery = { ...query, page: 1 };
  const nextFilters = { ...filters };
  let nextDates = Array.isArray(dates) ? [...dates] : dates;
  if (key === 'dateFrom' || key === 'dateTo') {
    nextQuery.dateFrom = '';
    nextQuery.dateTo = '';
    if (Array.isArray(dates) && dates[0] === query.dateFrom && dates[1] === query.dateTo)
      nextDates = null;
  } else {
    nextQuery[key] = '';
    // An unchanged field mirrors the removed chip; a different value is an
    // unsubmitted draft and belongs to the user's next explicit query.
    if (Object.hasOwn(nextFilters, key) && String(nextFilters[key] ?? '') === String(query[key] ?? ''))
      nextFilters[key] = '';
  }
  return { query: nextQuery, filters: nextFilters, dates: nextDates };
}
