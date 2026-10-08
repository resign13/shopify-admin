"""Order-scoped, read-only history from the existing transactional audit trail.

A batch is one successful operation, even when saving an order replaces hundreds
of size rows. Creation batches are excluded from this modification history;
the underlying system audit remains intact. Only explicitly supported fields
are exposed to order readers.
"""
from collections import defaultdict

import db


ORDER_FIELDS = {
    'status': 'status', 'store_user_id': 'customerId',
    'contact_name': 'contactName', 'country': 'country',
    'apartment': 'apartment', 'city': 'city', 'state': 'state',
    'note': 'note', 'tracking_no': 'trackingNo',
    'owner_admin_id': 'ownerAdminId',
    'shipping_fee': 'shippingFee', 'total_amount': 'totalAmount',
}
FINANCIAL_FIELDS = {'shippingFee', 'totalAmount', 'unitPrice'}


def _attachments(data):
    value = (data or {}).get('label_image_urls') or []
    if isinstance(value, str):
        import json
        try:
            value = json.loads(value)
        except (ValueError, TypeError):
            value = []
    urls = set(url for url in value if isinstance(url, str)) if isinstance(value, list) else set()
    if (data or {}).get('label_pdf_url'):
        urls.add(data['label_pdf_url'])
    return sorted(urls)


def _line_totals(states):
    totals = {}
    for data in states:
        if not data:
            continue
        key = (data.get('product_id'), data.get('size_code') or '')
        line = totals.setdefault(key, {'sku': data.get('sku') or '', 'quantity': 0, 'prices': set()})
        line['quantity'] += int(data.get('quantity') or 0)
        line['prices'].add(data.get('unit_price'))
    for line in totals.values():
        prices = sorted((price for price in line.pop('prices') if price is not None))
        line['unitPrice'] = prices[0] if len(prices) == 1 else prices or None
    return totals


def summarize(rows, *, hide_amounts=False):
    """Collapse intermediate header writes and item DELETE/INSERT replacements."""
    first, last = rows[0], rows[-1]
    before, after, header_seen = None, None, False
    item_states = {}
    for row in rows:
        old, new = row['before_data'], row['after_data']
        if row['entity_table'] == 'orders':
            if not header_seen:
                before, header_seen = old, True
            after = new
        else:
            item_id = (new or old)['id']
            state = item_states.setdefault(item_id, {'before': old, 'after': None})
            state['after'] = new
    changes = []
    if header_seen:
        for column, field in ORDER_FIELDS.items():
            if hide_amounts and field in FINANCIAL_FIELDS:
                continue
            previous, current = (before or {}).get(column), (after or {}).get(column)
            if previous != current and not (previous in (None, '') and current in (None, '')):
                changes.append({'field': field, 'before': previous, 'after': current})
        old_files, new_files = _attachments(before), _attachments(after)
        if old_files != new_files:
            # Keep URLs/private file contents out of the history response.
            changes.append({'field': 'attachments', 'before': len(old_files), 'after': len(new_files)})
    old_lines = _line_totals(state['before'] for state in item_states.values())
    new_lines = _line_totals(state['after'] for state in item_states.values())
    for key in sorted(old_lines.keys() | new_lines.keys(), key=lambda key: (key[0] or 0, key[1])):
        old, new = old_lines.get(key, {}), new_lines.get(key, {})
        for field in ('quantity', 'unitPrice'):
            if hide_amounts and field in FINANCIAL_FIELDS:
                continue
            previous = old.get(field, 0 if field == 'quantity' else None)
            current = new.get(field, 0 if field == 'quantity' else None)
            if previous != current:
                change = {'field': field, 'sku': (new or old)['sku'], 'sizeCode': key[1],
                          'before': previous, 'after': current}
                if field == 'quantity':
                    change['delta'] = current - previous
                changes.append(change)
    action = 'update'
    if header_seen and before is None:
        action = 'create'
    elif header_seen and after is None:
        action = 'delete'
    elif header_seen and (before or {}).get('status') != (after or {}).get('status'):
        if after.get('status') == 'cancelled':
            action = 'cancel'
        elif before.get('status') == 'cancelled':
            action = 'restore'
        else:
            action = 'status'
    return {'id': last['id'], 'occurredAt': db._iso(last['occurred_at']),
            'actor': {key: (first['actor'] or {}).get(key) for key in ('id', 'name', 'role')},
            'action': action, 'changes': changes}


def page(order_id, args, *, hide_amounts=False):
    current, size = int(args.get('page', 1)), int(args.get('pageSize', 10))
    if not 1 <= current <= 2147483647 or size not in {10, 25, 50}:
        raise ValueError('订单操作记录分页参数无效')
    if not db._fetch_one('SELECT id FROM orders WHERE id=%s', (order_id,)):
        return None
    # Match both headers and child lines, including ownership backfills performed
    # through store-users. Never mix another order from the same admin batch.
    # Creating an order also performs header UPDATEs and item INSERTs. Exclude
    # the entire creation batch before counting/paging, not just its INSERT row.
    # Correlate by order as well as batch so edits to other orders in that same
    # transaction remain visible.
    where = """history.entity_table IN ('orders','order_items') AND history.object_id=%s
        AND NOT EXISTS (
            SELECT 1 FROM admin_audit_logs created
            WHERE created.entity_table='orders' AND created.action='INSERT'
              AND created.object_id=history.object_id AND created.batch_id=history.batch_id
        )"""
    params = (str(order_id),)
    total = db._fetch_one('SELECT COUNT(DISTINCT history.batch_id) AS total FROM admin_audit_logs history WHERE ' + where, params)['total']
    batches = db._fetch_all('SELECT batch_id,MAX(occurred_at) AS occurred_at,MAX(id) AS id '
                           'FROM admin_audit_logs history WHERE ' + where +
                           ' GROUP BY batch_id ORDER BY occurred_at DESC,id DESC LIMIT %s OFFSET %s',
                           (*params, size, (current - 1) * size))
    grouped = defaultdict(list)
    if batches:
        rows = db._fetch_all('SELECT id,occurred_at,actor,entity_table,batch_id,before_data,after_data '
                             'FROM admin_audit_logs history WHERE ' + where + ' AND batch_id=ANY(%s) ORDER BY id',
                             (*params, [batch['batch_id'] for batch in batches]))
        for row in rows:
            grouped[row['batch_id']].append(row)
    return {'items': [summarize(grouped[batch['batch_id']], hide_amounts=hide_amounts) for batch in batches],
            'total': total, 'page': current, 'pageSize': size}
