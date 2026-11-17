export function contractExportQuery(query, ids = null) {
  const params = new URLSearchParams();
  for (const key of ['keyword', 'createdMonth']) {
    const value = String(query[key] ?? '').trim();
    if (value) params.set(key, value);
  }
  if (ids !== null) params.set('contractIds', [...new Set(ids)].join(','));
  return params.toString();
}
