export function orderExportIds(selected, pageRows) {
  const rows = selected.length ? selected : pageRows;
  return rows.map(row => row.id).filter(id => id !== null && id !== undefined && String(id) !== '');
}
