export const operationNames = {
  update: '修改订单', status: '修改状态',
  cancel: '取消订单', restore: '恢复订单', delete: '删除订单',
};

export const operationFields = {
  status: '订单状态', customerId: '商城账号编号', contactName: '联系人',
  country: '国家', apartment: '公寓 / 单元', city: '城市', state: '省 / 州',
  note: '备注', trackingNo: '物流单号', ownerAdminId: '业务员编号',
  shippingFee: '运费', totalAmount: '应付总额', attachments: '订单附件',
  quantity: '数量', unitPrice: '单价',
};

export function operationValue(field, value, statusNames, money) {
  if (value == null || value === '') return '未填写';
  if (field === 'status') return statusNames[value] || value;
  if (field === 'attachments') return `${value} 个文件`;
  if (['shippingFee', 'totalAmount', 'unitPrice'].includes(field)) {
    return Array.isArray(value) ? value.map(money).join(' / ') : money(value);
  }
  return String(value);
}
