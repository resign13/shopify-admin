"""Prepare and apply the one-time release of legacy pending-payment order inventory."""
import argparse
from collections import defaultdict
import json
from pathlib import Path
import sys

vendor = Path(__file__).resolve().parent / '_vendor'
if vendor.is_dir():
    sys.path.insert(0, str(vendor))

import db
import inventory_policy


def build_report(cur):
    version = inventory_policy.ORDER_STOCK_ON_PAYMENT_VERSION
    report = {'version': version, 'alreadyApplied': inventory_policy.order_stock_on_payment_enabled(cur),
              'orders': [], 'balances': [], 'needsReview': []}
    if report['alreadyApplied']:
        return report
    cur.execute("""SELECT o.id AS order_id,o.order_no,i.id AS line_id,i.product_id,i.sku AS order_sku,
      COALESCE(i.size_code,'') AS size_code,i.quantity,p.sku AS current_sku,p.stock AS product_stock,
      s.stock AS size_stock,EXISTS(SELECT 1 FROM product_size_prices sp WHERE sp.product_id=p.id) AS has_sizes
      FROM orders o LEFT JOIN order_items i ON i.order_id=o.id
      LEFT JOIN products p ON p.id=i.product_id
      LEFT JOIN product_size_prices s ON s.product_id=p.id AND s.size_code=i.size_code
      WHERE o.status='pending_payment' ORDER BY o.id,i.id""")
    orders = {}
    balances = defaultdict(dict)
    for row in cur.fetchall():
        order_id, order_no = row['order_id'], row['order_no']
        order = orders.setdefault(order_id, {'orderId': order_id, 'orderNo': order_no, 'items': []})
        key = (row['product_id'], row['size_code'])
        item = {'lineId': row['line_id'], 'productId': key[0], 'sizeCode': key[1], 'orderSku': row['order_sku'],
                'sku': row['current_sku'], 'quantity': row['quantity']}
        stock = row['size_stock'] if row['has_sizes'] else row['product_stock']
        if row['line_id'] is None:
            reason = '订单没有商品行'
        elif stock is None or (not row['has_sizes'] and key[1]):
            reason = '历史商品或实际尺码无法匹配'
        elif not row['quantity'] or row['quantity'] < 0:
            reason = '订单数量不正确'
        else:
            reason = None
        if reason:
            report['needsReview'].append(dict(item, orderId=order_id, orderNo=order_no, reason=reason))
            continue
        order['items'].append(item)
        balance = balances[key]
        if not balance:
            balance.update(productId=key[0], sku=row['current_sku'], sizeCode=key[1], before=stock, release=0)
        balance['release'] += row['quantity']
    report['orders'] = list(orders.values())
    for key in sorted(balances):
        balance = balances[key]
        balance['after'] = balance['before'] + balance['release']
        if not inventory_policy.MIN_STOCK <= balance['after'] <= inventory_policy.MAX_STOCK:
            report['needsReview'].append(dict(balance, reason='回补后超出允许的库存数量范围'))
        report['balances'].append(balance)
    return report


def preview():
    with db.get_connection() as conn, conn.cursor() as cur:
        cur.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
        return build_report(cur)


def apply(reviewed):
    with db.get_connection() as conn, conn.cursor() as cur:
        # Both applications and any inventory writers must be paused before this step.
        # Lock out concurrent writes to the reviewed rows through the actual commit.
        cur.execute('LOCK TABLE orders, order_items, products, product_size_prices, inventory_policy_versions '
                    'IN SHARE ROW EXCLUSIVE MODE')
        current = build_report(cur)
        if current['alreadyApplied']:
            return {'alreadyApplied': True, 'ordersReleased': 0, 'unitsReleased': 0}
        if current['needsReview']:
            raise ValueError('存在需要核对的订单或库存；请处理报告中的 needsReview 后重新预览')
        if reviewed != current:
            raise ValueError('订单或现货已变化，当前数据与已核对的清单不一致；请重新预览')
        changes = {(row['productId'], row['sizeCode']): row['release'] for row in current['balances']}
        inventory_policy.adjust_stock(cur, changes)
        expected = {(row['productId'], row['sizeCode']): row['after'] for row in current['balances']}
        actual = {(row['productId'], row['sizeCode']): row['before'] for row in build_report(cur)['balances']}
        if actual != expected:
            raise ValueError('实际回补后的尺码库存与核对清单不一致，切换已回滚')
        cur.execute('INSERT INTO inventory_policy_versions(version) VALUES (%s)', (current['version'],))
        return {'alreadyApplied': False, 'ordersReleased': len(current['orders']), 'unitsReleased': sum(changes.values())}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument('--preview', type=Path, metavar='OUTPUT_JSON')
    action.add_argument('--apply', type=Path, metavar='REVIEWED_JSON')
    args = parser.parse_args()
    try:
        if args.preview:
            result = preview()
            args.preview.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
            print(json.dumps({'orders': len(result['orders']), 'variants': len(result['balances']),
                              'needsReview': len(result['needsReview']), 'alreadyApplied': result['alreadyApplied']}))
        else:
            print(json.dumps(apply(json.loads(args.apply.read_text(encoding='utf-8-sig')))))
    except ValueError as exc:
        parser.exit(1, str(exc) + '\n')
