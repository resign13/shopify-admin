"""Read-only reorder drafts and validation inside the existing order transaction."""
import json
from decimal import Decimal
from urllib.parse import urlsplit

from flask import abort, g

import db
import sales_ownership


class PriceChanged(Exception):
    def __init__(self, changes):
        super().__init__('商品价格已变化，草稿已保留，请核对最新价格后重新确认创建。')
        self.changes = changes


def source(order_id, *, lock=False):
    sales_ownership.assert_access(order_id, lock=lock)
    row = db._fetch_one('SELECT * FROM orders WHERE id=%s' + (' FOR SHARE' if lock else ''), (order_id,))
    if not row:
        abort(404, description='来源订单不存在或无权访问')
    return row


def attachments(order):
    # Historical attachments must not be truncated by the new-upload limits.
    urls = db._json_list(order.get('label_image_urls'))
    fallback = str(order.get('label_pdf_url') or '').strip()
    if fallback and fallback not in urls:
        urls.append(fallback)
    return list(dict.fromkeys(urls))


def inherited_attachments(payload, origin):
    values = payload.get('inheritedAttachmentUrls', [])
    from flask import current_app
    allowed = set(attachments(origin))
    allowed.update(current_app.extensions['media'].canonical(v) for v in list(allowed))
    if (not isinstance(values, list) or any(not isinstance(v, str) for v in values)
            or len(values) != len(set(values)) or any(v not in allowed for v in values)):
        raise ValueError('继承附件与来源订单不一致，请重新打开草稿核对')
    return values


def validate_attachment_uploads(inherited, new_images, new_pdf):
    images = sum(urlsplit(url).path.lower().endswith(('.jpg','.jpeg','.png','.webp','.gif','.avif','.bmp')) for url in inherited)
    if new_images and images + len(new_images) > 9:
        raise ValueError('新增图片与保留图片合计最多 9 张；历史超限附件可继续保留')
    if new_pdf and any(urlsplit(url).path.lower().endswith('.pdf') for url in inherited):
        raise ValueError('请先移除保留的 PDF，再上传替换文件')


def current_products(ids):
    products = {p['id']: {'id': p['id'], 'sku': p['sku'], 'isActive': p['is_active'],
                         'categoryId': p['category_id'], 'sizePrices': []}
                for p in db._fetch_all('SELECT id,sku,is_active,category_id FROM products WHERE id=ANY(%s)', (ids,))}
    prices = {}
    for size in db._fetch_all('SELECT product_id,size_code,price,stock,weight_grams FROM product_size_prices WHERE product_id=ANY(%s) ORDER BY id', (ids,)):
        prices[(size['product_id'], size['size_code'])] = size
        products[size['product_id']]['sizePrices'].append({'sizeCode': size['size_code'], 'price': db._num(size['price']), 'stock': size['stock'], 'weightGrams': size['weight_grams']})
    return products, prices


def refresh_items(rows):
    products, prices = current_products(sorted({r['productId'] for r in rows if r.get('productId')}))
    items, issues = [], []
    for row in rows:
        item = dict(row)
        key = (item.get('productId'), item.get('sizeCode') or '')
        product, size = products.get(key[0]), prices.get(key)
        reason = ('商品已删除' if not product else '商品已下架' if not product['isActive']
                  else '原订单未指定尺码' if not key[1] else '原尺码已移除' if not size
                  else '数量超过单行上限' if not 0 <= item['quantity'] <= 2147483647 else '')
        if reason:
            issues.append({**item, 'reason': reason})
        else:
            item.pop('reason', None)
            item.setdefault('oldUnitPrices', [item.get('unitPrice', db._num(size['price']))])
            items.append({**item, 'unitPrice': db._num(size['price'])})
    return items, issues, list(products.values())


def draft(order_id):
    origin = source(order_id)
    customer = db._fetch_one('SELECT id,name,email,company_name,status FROM store_users WHERE id=%s', (origin['store_user_id'],))
    owner = db._fetch_one('SELECT id,name,role,status FROM admin_users WHERE id=%s', (origin['owner_admin_id'],)) if origin['owner_admin_id'] else None
    owner_valid = bool(owner and owner['role'] == 'sales' and owner['status'] == 'active')
    rows = db._fetch_all('SELECT * FROM order_items WHERE order_id=%s ORDER BY id', (order_id,))
    grouped = {}
    for row in rows:
        key = (row['product_id'], row['size_code'] or '')
        # Deleted products lose their foreign key. They are not the same product
        # just because both IDs are NULL; retain every orphan line for review.
        group_key = key if key[0] is not None else ('deleted', row['id'])
        item = grouped.setdefault(group_key, {'productId': key[0], 'sizeCode': key[1], 'sku': row['sku'],
            'productName': row['product_name'], 'quantity': 0, 'oldUnitPrices': []})
        item['quantity'] += int(row['quantity'])
        price = db._num(row['unit_price'])
        if price not in item['oldUnitPrices']:
            item['oldUnitPrices'].append(price)
    items, issues, products = refresh_items(list(grouped.values()))
    mapping = {'contactName': 'contact_name', 'phone': 'phone', 'country': 'country',
               'contactValue': 'contact_email', 'address': 'address_line1', 'apartment': 'apartment',
               'city': 'city', 'state': 'state', 'zip': 'postal_code', 'note': 'note'}
    profile = {key: origin.get(column) or '' for key, column in mapping.items()}
    profile['address'] = profile['address'] or origin.get('shipping_address') or ''
    profile.update(userId=customer['id'] if customer and customer['status'] == 'active' else None,
                   secondaryOrderNo='',
                   ownerAdminId=owner['id'] if owner_valid else None,
                   shippingFee=db._num(origin.get('shipping_fee') or 0), items=items,
                   inheritedAttachmentUrls=attachments(origin), labelImageUrls=[], labelPdfUrl='')
    if g.current_user['role'] == 'sales':
        profile['ownerAdminId'] = g.current_user['id']
    return {'sourceOrderId': order_id, 'sourceOrderNo': origin['order_no'], 'draft': profile,
            'customer': {'id': customer['id'], 'name': customer['name'], 'email': customer['email'], 'companyName': customer['company_name']} if customer else None,
            'customerUnavailable': not customer or customer['status'] != 'active',
            'ownerNeedsConfirmation': g.current_user['role'] == 'admin' and bool(origin['owner_admin_id']) and not owner_valid,
            'products': products, 'issues': issues}


def check_price(changes, key, submitted, current, sku):
    if Decimal(str(submitted)) != current:
        changes.append({'productId': key[0], 'sizeCode': key[1], 'sku': sku,
                        'previousPrice': db._num(submitted), 'unitPrice': db._num(current)})


def audit(order_id, origin):
    # Keep this separate from order modification history (new orders have none).
    actor = {key: g.current_user.get(key) for key in ('id', 'name', 'role')}
    db._fetch_one('''INSERT INTO admin_audit_logs(actor,module,action,entity_table,object_id,batch_id,after_data)
        VALUES(%s::jsonb,'orders','REORDER','order_reorders',%s,current_setting('gingtto.batch'),%s::jsonb) RETURNING id''',
        (json.dumps(actor), str(order_id), json.dumps({'sourceOrderId': origin['id'], 'sourceOrderNo': origin['order_no'], 'orderId': order_id})))
