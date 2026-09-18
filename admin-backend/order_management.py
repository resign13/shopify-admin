"""Back-office order entry and delta-based line editing, inside the request transaction."""
import hashlib
import json
import uuid
from urllib.parse import urlsplit
from decimal import Decimal, InvalidOperation
from flask import g
import db


def amount(value, label):
    if isinstance(value, bool) or value is None or str(value).strip() == '':
        raise ValueError(f'{label}必须是非负金额')
    try:
        result = Decimal(str(value))
    except InvalidOperation:
        raise ValueError(f'{label}格式无效')
    if not result.is_finite() or result < 0 or result > Decimal('9999999999.99') or result != result.quantize(Decimal('.01')):
        raise ValueError(f'{label}须为非负金额，最多两位小数')
    return result


def positive(value, label):
    result = db._parse_non_negative_int(value, label)
    if not result:
        raise ValueError(f'{label}必须大于零')
    return result


def order_images(payload, old):
    """New images replace the image list; existing non-image attachments survive."""
    if 'labelImageUrls' not in payload:
        return None
    urls = payload['labelImageUrls']
    if not isinstance(urls, list) or len(urls) > 9:
        raise ValueError('订单最多上传 9 张图片')
    cleaned = []
    for url in urls:
        if not isinstance(url, str) or len(url) > 2048:
            raise ValueError('订单图片地址无效')
        parsed = urlsplit(url)
        if not ((parsed.scheme in {'https', 'http'} and parsed.netloc) or (not parsed.netloc and not parsed.scheme and parsed.path.startswith('/uploads/'))):
            raise ValueError('订单图片地址无效')
        if not parsed.path.lower().endswith(('.jpg', '.jpeg', '.png', '.webp', '.gif', '.avif', '.bmp')):
            raise ValueError('订单附件请上传图片')
        if url in cleaned:
            raise ValueError('订单图片不能重复')
        cleaned.append(url)
    legacy = db._parse_label_image_urls(old) if old else []
    files = [url for url in legacy if not urlsplit(url).path.lower().endswith(('.jpg', '.jpeg', '.png', '.webp', '.gif', '.avif', '.bmp'))]
    return cleaned + files


def save_order(payload, order_id=None):
    old = None
    if order_id is not None:
        if not payload.get('version'):
            raise ValueError('缺少订单版本，请重新打开订单')
        old = db._fetch_one('SELECT * FROM orders WHERE id=%s FOR UPDATE', (order_id,))
        if not old:
            raise ValueError('订单不存在')
    else:
        try:
            request_id = str(uuid.UUID(str(payload.get('requestId', ''))))
        except ValueError:
            raise ValueError('缺少有效的提交编号，请重新打开新增订单')
        digest = hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        db._fetch_one('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))', (request_id,))
        previous = db._fetch_one('SELECT * FROM admin_order_requests WHERE request_id=%s', (request_id,))
        if previous:
            if previous['actor_id'] != g.current_user['id'] or previous['payload_hash'] != digest:
                raise ValueError('提交编号已使用，请先检查订单列表，避免重复建单')
            existing = db.get_order_by_id(previous['order_id'])
            if not existing:
                raise ValueError('该请求已创建过订单，订单随后被删除，请重新打开新增订单')
            return {'order': existing, 'replayed': True}

    user_id = positive(payload.get('userId'), '客户编号')
    image_urls = order_images(payload, old)
    next_status = payload.get('status', old['status'] if old else 'pending_payment')
    if not isinstance(next_status, str) or next_status not in {'pending_payment', 'allocated', 'paid', 'shipped', 'completed', 'cancelled'}:
        raise ValueError('订单状态无效')
    if not old and next_status != 'pending_payment':
        raise ValueError('新增订单必须为待付款状态')
    tracking = payload.get('trackingNo', (old or {}).get('tracking_no') or '')
    payment = payload.get('paymentLink', (old or {}).get('payment_link') or '')
    if not isinstance(tracking, str) or len(tracking) > 500 or not isinstance(payment, str) or len(payment) > 2048:
        raise ValueError('物流单号或付款链接无效')
    if next_status == 'shipped' and not tracking.strip():
        raise ValueError('发货必须填写物流单号')
    user = db._fetch_one('SELECT id,status FROM store_users WHERE id=%s FOR SHARE', (user_id,))
    if not user or (user['status'] != 'active' and (not old or old['store_user_id'] != user_id)):
        raise ValueError('请选择有效商城客户')
    fields = {}
    for key in ['contactName', 'phone', 'country', 'contactValue', 'address', 'apartment', 'city', 'state', 'zip', 'note']:
        value = payload.get(key, '')
        if not isinstance(value, str) or len(value) > (5000 if key == 'note' else 500):
            raise ValueError(f'{key}格式或长度无效')
        fields[key] = value.strip()
    if any(not fields[key] for key in ['contactName', 'phone', 'country', 'address']):
        raise ValueError('请填写收货人、联系电话、国家及收货地址')
    shipping = amount(payload.get('shippingFee', 0), '运费')
    rows = payload.get('items')
    if not isinstance(rows, list) or not 1 <= len(rows) <= 500:
        raise ValueError('订单需包含 1–500 个商品尺码行')
    desired = {}
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError('商品明细格式无效')
        key = (positive(row.get('productId'), '商品编号'), str(row.get('sizeCode') or '').strip())
        if key in desired:
            raise ValueError('同一商品尺码不能重复，请合并数量')
        desired[key] = {'quantity': positive(row.get('quantity'), '商品数量'), 'price': amount(row.get('unitPrice'), '商品单价')}
    previous_rows = db._fetch_all('SELECT * FROM order_items WHERE order_id=%s ORDER BY id', (order_id,)) if old else []
    previous_quantities = {}
    for row in previous_rows:
        key = (row['product_id'], row['size_code'] or '')
        previous_quantities[key] = previous_quantities.get(key, 0) + row['quantity']
    before_lines = [(r['product_id'], r['size_code'] or '', r['quantity'], r['unit_price']) for r in previous_rows]
    after_lines = [(p, s, r['quantity'], r['price']) for (p, s), r in desired.items()]
    lines_changed = sorted(before_lines) != sorted(after_lines)
    if old and old['status'] in {'cancelled', 'shipped', 'completed'} and lines_changed:
        raise ValueError('已取消、已发货或已完成订单仅可修改收货资料和备注，商品明细保持不变')
    products = {}
    for product_id in sorted({k[0] for k in desired} | {k[0] for k in previous_quantities}):
        product = db._fetch_one('SELECT * FROM products WHERE id=%s FOR UPDATE', (product_id,))
        if not product:
            raise ValueError('商品已删除，请重新核对订单')
        products[product_id] = product
    for key in sorted(set(desired) | set(previous_quantities)):
        product_id, size_code = key
        new = desired.get(key)
        delta = (new['quantity'] if new else 0) - previous_quantities.get(key, 0)
        size = db._fetch_one('SELECT stock FROM product_size_prices WHERE product_id=%s AND size_code=%s FOR UPDATE', key)
        if new and not size and key not in previous_quantities:
            raise ValueError(f"{products[product_id]['sku']} 的尺码 {size_code} 不存在")
        if delta and not size and size_code:
            raise ValueError('原订单尺码已移除，请先恢复尺码再调整数量')
        if delta > 0 and not products[product_id]['is_active']:
            raise ValueError('已下架商品不能增加订购数量')
        available = size['stock'] if size else products[product_id]['stock']
        if delta > available:
            raise ValueError(f"{products[product_id]['sku']} / {size_code} 库存不足，现货 {available}，需追加 {delta}")
        if not 0 <= available - delta <= 2147483647:
            raise ValueError('调整后的库存超出允许范围')
        if delta:
            if size:
                db._fetch_one('UPDATE product_size_prices SET stock=stock-%s WHERE product_id=%s AND size_code=%s RETURNING id', (delta, *key))
    for product_id, product in products.items():
        delta = sum(r['quantity'] for k,r in desired.items() if k[0] == product_id) - sum(q for k,q in previous_quantities.items() if k[0] == product_id)
        if not 0 <= product['stock'] - delta <= 2147483647:
            raise ValueError('商品总库存不足或超出允许范围，请核对库存')
        if delta:
            db._fetch_one('UPDATE products SET stock=stock-%s,updated_at=NOW() WHERE id=%s RETURNING id', (delta, product_id))
        elif any(k[0] == product_id and (desired.get(k, {}).get('quantity', 0) != previous_quantities.get(k, 0)) for k in set(desired) | set(previous_quantities)):
            db._fetch_one('UPDATE products SET updated_at=NOW() WHERE id=%s RETURNING id', (product_id,))
    total = amount(sum(row['quantity'] * row['price'] for row in desired.values()) + shipping, '订单总额')
    address = ', '.join(fields[key] for key in ['address', 'apartment', 'city', 'state', 'zip', 'country'] if fields[key])
    if not old:
        record = db._fetch_one("INSERT INTO orders(order_no,store_user_id,status,contact_name,phone,shipping_address,total_amount) VALUES(%s,%s,'pending_payment',%s,%s,%s,%s) RETURNING id", ('TEMP-'+uuid.uuid4().hex, user_id, fields['contactName'], fields['phone'], address, total))
        order_id = record['id']
        db._fetch_one('UPDATE orders SET order_no=%s WHERE id=%s RETURNING id', (f'LM-{order_id:06d}', order_id))
    db._fetch_one('''UPDATE orders SET store_user_id=%s,contact_name=%s,phone=%s,country=%s,contact_email=%s,
        address_line1=%s,apartment=%s,city=%s,state=%s,postal_code=%s,shipping_address=%s,note=%s,
        shipping_fee=%s,total_amount=%s,updated_at=NOW() WHERE id=%s RETURNING id''',
        (user_id, fields['contactName'], fields['phone'], fields['country'], fields['contactValue'], fields['address'], fields['apartment'], fields['city'], fields['state'], fields['zip'], address, fields['note'], shipping, total, order_id))
    if lines_changed:
        db._fetch_one('DELETE FROM order_items WHERE order_id=%s RETURNING id', (order_id,))
        previous_map = {(r['product_id'], r['size_code'] or ''): r for r in previous_rows}
        for (product_id, size), row in desired.items():
            product = products[product_id]
            original = previous_map.get((product_id, size))
            title = db._fetch_one("SELECT name FROM product_translations WHERE product_id=%s AND lang_code='zh'", (product_id,))
            name = original['product_name'] if original else (title['name'] if title else product['sku'])
            sku = original['sku'] if original else product['sku']
            db._fetch_one('''INSERT INTO order_items(order_id,product_id,product_name,sku,size_code,quantity,unit_price,total_price)
                VALUES(%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id''', (order_id, product_id, name, sku, size, row['quantity'], row['price'], row['quantity'] * row['price']))
    if not old:
        db._fetch_one('INSERT INTO admin_order_requests(request_id,actor_id,payload_hash,order_id) VALUES(%s,%s,%s,%s) RETURNING request_id', (request_id, g.current_user['id'], digest, order_id))
    if image_urls is not None:
        legacy_files = [url for url in image_urls if not urlsplit(url).path.lower().endswith(('.jpg', '.jpeg', '.png', '.webp', '.gif', '.avif', '.bmp'))]
        db._fetch_one('UPDATE orders SET label_image_urls=%s,label_pdf_url=%s WHERE id=%s RETURNING id',
                      (json.dumps(image_urls, ensure_ascii=False), legacy_files[0] if legacy_files else '', order_id))
    if old:
        db.update_order_status(order_id, next_status, tracking.strip(), payment.strip(), shipping)
    return {'order': db.get_order_by_id(order_id), 'replayed': False}
