export const customerFields = [
  { key: 'contactName', label: '收货人', required: true },
  { key: 'phone', label: '联系电话', required: true },
  { key: 'country', label: '国家', required: true },
  { key: 'contactValue', label: '联系邮箱' },
  { key: 'address', label: '详细地址', required: true },
  { key: 'apartment', label: '公寓 / 房间' },
  { key: 'city', label: '城市' },
  { key: 'state', label: '州 / 省' },
  { key: 'zip', label: '邮编' },
];

// Strict whitelist: never copy goods, prices, order status, version or request ID.
export function customerProfile(source = {}) {
  return {
    userId: source.userId ?? null,
    ...Object.fromEntries([...customerFields.map(field => field.key), 'note']
      .map(key => [key, source[key] ?? ''])),
    labelImageUrls: [...(source.labelImageUrls || [])],
    labelPdfUrl: source.labelPdfUrl || '',
  };
}

export function applyCustomerProfile(order, profile) {
  Object.assign(order, customerProfile(profile));
}
