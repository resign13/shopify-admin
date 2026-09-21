"""Signed inventory policy. Mirrored in storefront-backend; parity is regression-tested."""
import re
from psycopg.sql import SQL, Identifier

MIN_STOCK = -2147483648
MAX_STOCK = 2147483647
OPEN_STATUSES = {'pending_payment', 'allocated', 'paid'}


def parse_stock(value, label='现货余额', *, allow_blank=False):
    if allow_blank and value in (None, ''):
        return 0
    if isinstance(value, bool) or not re.fullmatch(r'-?\d+', str(value).strip()):
        raise ValueError(f'{label}必须是整数')
    value = int(value)
    if not MIN_STOCK <= value <= MAX_STOCK:
        raise ValueError(f'{label}超出允许范围')
    return value


def stock_metrics(values):
    values = list(values)
    return {'availableStock': sum(max(v, 0) for v in values),
            'shortageUnits': sum(max(-v, 0) for v in values),
            'shortageSizeCount': sum(v < 0 for v in values)}


def available_sql(alias='p'):
    return f'COALESCE((SELECT SUM(GREATEST(s.stock,0)) FROM product_size_prices s WHERE s.product_id={alias}.id),GREATEST({alias}.stock,0))'


def public_inventory(value):
    """Customer boundary: clip each real size BEFORE aggregating; omit internal metrics."""
    if isinstance(value, list):
        return [public_inventory(v) for v in value]
    if not isinstance(value, dict):
        return value
    hidden = {'shortageUnits', 'shortageSizeCount', 'contractPending', 'pendingInspection', 'pendingInbound'}
    result = {k: public_inventory(v) for k, v in value.items() if k not in hidden}
    if 'zeroSizes' in result:
        result['zeroSizes'] += int(value.get('shortageSizeCount', 0))
    if 'stock' in result:
        result['stock'] = (sum(s['stock'] for s in result['sizePrices']) if result.get('sizePrices')
                           else max(int(result.get('availableStock', result['stock']) or 0), 0))
    return result


def migrate(cur):
    cur.execute('SELECT pg_advisory_xact_lock(7192031)')
    # Remove checks on stock only, retaining price and pipeline constraints.
    cur.execute("""SELECT c.conname,t.relname FROM pg_constraint c
      JOIN pg_class t ON t.oid=c.conrelid JOIN pg_namespace n ON n.oid=t.relnamespace
      JOIN pg_attribute a ON a.attrelid=t.oid AND a.attname='stock'
      WHERE n.nspname='public' AND t.relname IN ('products','product_size_prices')
        AND c.contype='c' AND c.conkey=ARRAY[a.attnum]::smallint[]""")
    for row in cur.fetchall():
        cur.execute(SQL('ALTER TABLE {} DROP CONSTRAINT {}').format(Identifier(row['relname']), Identifier(row['conname'])))
    cur.execute('CREATE TABLE IF NOT EXISTS inventory_policy_versions (version TEXT PRIMARY KEY, applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW())')
    cur.execute('''CREATE TABLE IF NOT EXISTS inventory_legacy_cancelled_orders (
      order_id BIGINT PRIMARY KEY, order_no TEXT NOT NULL, order_updated_at TIMESTAMPTZ,
      captured_at TIMESTAMPTZ NOT NULL DEFAULT NOW())''')
    cur.execute("INSERT INTO inventory_policy_versions(version) VALUES('signed-stock-v1') ON CONFLICT DO NOTHING RETURNING version")
    if cur.fetchone():
        cur.execute("""INSERT INTO inventory_legacy_cancelled_orders(order_id,order_no,order_updated_at)
          SELECT id,order_no,updated_at FROM orders WHERE status='cancelled' ON CONFLICT DO NOTHING""")


def validate_transition(previous, next_status):
    if next_status not in OPEN_STATUSES | {'cancelled', 'shipped', 'completed'}:
        raise ValueError('订单状态无效')
    if previous == 'cancelled' and next_status != 'cancelled':
        raise ValueError('已取消订单不能恢复，请新建订单')
    if previous in {'shipped', 'completed'} and next_status not in ({'shipped', 'completed'} if previous == 'shipped' else {'completed'}):
        raise ValueError('已发货或已完成订单不能退回发货前状态或取消')


def adjust_stock(cur, changes):
    """Apply signed per-size deltas under deterministic product/size locks; caller owns transaction."""
    for product_id in sorted({key[0] for key in changes}):
        cur.execute('SELECT id,stock FROM products WHERE id=%s FOR UPDATE', (product_id,))
        product = cur.fetchone()
        if not product:
            raise ValueError('商品不存在，无法调整库存')
        cur.execute('SELECT size_code,stock FROM product_size_prices WHERE product_id=%s ORDER BY size_code FOR UPDATE', (product_id,))
        sizes = {row['size_code']: row['stock'] for row in cur.fetchall()}
        for (pid, size), delta in sorted(changes.items()):
            if pid != product_id or not delta:
                continue
            if sizes:
                if size not in sizes:
                    raise ValueError('原订单尺码已移除，请恢复尺码后再调整库存')
                sizes[size] = parse_stock(sizes[size] + delta)
                cur.execute('UPDATE product_size_prices SET stock=%s WHERE product_id=%s AND size_code=%s', (sizes[size], pid, size))
            else:
                if size:
                    raise ValueError('原订单尺码已移除，请恢复尺码后再调整库存')
                product['stock'] = parse_stock(product['stock'] + delta)
        total = parse_stock(sum(sizes.values()) if sizes else product['stock'], '商品库存合计')
        cur.execute('UPDATE products SET stock=%s,updated_at=clock_timestamp() WHERE id=%s', (total, product_id))


def return_order_stock(cur, order_ids):
    cur.execute("""SELECT product_id,COALESCE(size_code,'') AS size_code,SUM(quantity) AS quantity
      FROM order_items WHERE order_id=ANY(%s) GROUP BY product_id,COALESCE(size_code,'')""", (order_ids,))
    adjust_stock(cur, {(r['product_id'], r['size_code']): int(r['quantity']) for r in cur.fetchall()})
