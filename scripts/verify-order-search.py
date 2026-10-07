"""Verify deployed style keyword search using a read-only database transaction."""
import argparse
from contextlib import contextmanager
import json
from pathlib import Path
import sys

parser = argparse.ArgumentParser()
parser.add_argument('--keyword', default='ZM4757')
args = parser.parse_args()
keyword = args.keyword.strip()
if not keyword or '%' in keyword or '_' in keyword:
    raise ValueError('Use a non-empty literal style keyword without LIKE wildcards')
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'admin-backend'))
import db
import workbench

with db._connect() as conn:
    conn.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
    @contextmanager
    def read_connection():
        yield conn
    db.get_connection = read_connection
    rows = conn.execute("SELECT o.id,o.owner_admin_id,o.order_no,su.name,su.email,su.company_name,o.tracking_no,"
                        "i.sku AS item_sku,p.sku AS current_sku,p.product_code,"
                        + workbench._style_code_sql('p') + " AS style_code FROM orders o "
                        "JOIN store_users su ON su.id=o.store_user_id LEFT JOIN order_items i ON i.order_id=o.id "
                        "LEFT JOIN products p ON p.id=i.product_id").fetchall()
    expected = {row['id'] for row in rows if keyword.lower() in ' '.join(str(row[key] or '') for key in
                ('order_no', 'name', 'email', 'company_name', 'tracking_no', 'item_sku', 'current_sku', 'product_code', 'style_code')).lower()}
    owners = [None, *[row['id'] for row in conn.execute("SELECT id FROM admin_users WHERE role='sales' AND status='active'").fetchall()]]
    for owner in owners:
        scoped = expected if owner is None else {row['id'] for row in rows if row['id'] in expected and row['owner_admin_id'] == owner}
        query = {'keyword': keyword.lower(), 'pageSize': 100}
        ids = workbench.order_ids(query, owner_id=owner)
        page = workbench.orders_page(query, owner_id=owner)
        if set(ids) != scoped or len(ids) != len(scoped) or page['total'] != len(scoped) or sum(page['statusCounts'].values()) != len(scoped):
            raise RuntimeError('Order style search, totals or owner isolation mismatch')
    print(json.dumps({'keyword': keyword, 'matchedOrders': len(expected), 'scopesChecked': len(owners), 'readOnly': True}))
