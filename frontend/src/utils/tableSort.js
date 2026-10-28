export function normalizeSortState(value) {
  const prop = typeof value?.prop === 'string' ? value.prop : '';
  const order = value?.order;
  return prop && ['ascending', 'descending'].includes(order)
    ? { prop, order } : { prop: '', order: null };
}

export function queryToSortState(query = {}) {
  // Category is the backend's default grouping, not a sortable table column.
  return normalizeSortState({
    prop: query.sort === 'category' ? '' : query.sort,
    order: query.direction === 'asc' ? 'ascending' : 'descending',
  });
}

export function sortStateToQuery(value, defaults = {}) {
  const { prop, order } = normalizeSortState(value);
  if (!prop) return { sort: defaults.sort || '', direction: defaults.direction || '' };
  return { sort: prop, direction: order === 'ascending' ? 'asc' : order === 'descending' ? 'desc' : '' };
}

export function createTableSort(initial, onChange) {
  let value = normalizeSortState(initial);
  return {
    get value() { return value; },
    sync(next, table) {
      value = normalizeSortState(next);
      // Element Plus sort() emits synchronously. Set the authoritative value
      // first so that its echo is equal and cannot emit another query.
      if (value.prop) table?.sort(value.prop, value.order);
      else table?.clearSort();
      return value;
    },
    change(next) {
      const normalized = normalizeSortState(next);
      if (value.prop === normalized.prop && value.order === normalized.order) return false;
      value = normalized;
      onChange(value);
      return true;
    },
  };
}
