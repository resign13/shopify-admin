"""Read-only deployment checks for category-first product and inventory lists."""
import argparse
from contextlib import contextmanager
import json
from pathlib import Path
import sys

parser = argparse.ArgumentParser()
parser.add_argument('backend', choices=('admin-backend', 'storefront-backend'))
args = parser.parse_args()
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / args.backend))
import db


def check_order(items, label):
    ranks = [(item['categorySortOrder'], item['categoryId']) for item in items]
    if ranks != sorted(ranks):
        raise RuntimeError(f'{label}: product categories are out of order')
    if len({item['id'] for item in items}) != len(items):
        raise RuntimeError(f'{label}: duplicate product rows')


with db._connect() as conn:
    conn.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')

    @contextmanager
    def read_connection():
        yield conn

    # Every legacy helper uses the same read-only snapshot. No app startup,
    # migrations, login sessions, orders or category updates are performed.
    db.get_connection = read_connection
    products = db.list_products()
    check_order(products, 'catalog')
    checks = ['catalog']
    if args.backend == 'admin-backend':
        from flask import Flask, g
        import workbench
        with Flask('category-deployment-verification').test_request_context():
            g.current_user = {'role': 'admin'}
            for pending, label in ((False, 'products'), (True, 'inventory')):
                for sort, direction in (('category', 'asc'), ('updatedAt', 'desc'), ('stock', 'asc')):
                    page, items, total = 1, [], None
                    while total is None or len(items) < total:
                        response = workbench.products_page({'page': page, 'pageSize': 100, 'sort': sort, 'direction': direction}, pending=pending)
                        total = response['total']
                        items.extend(response['items'])
                        if not response['items'] and len(items) < total:
                            raise RuntimeError(f'{label}: incomplete pagination')
                        page += 1
                    if len(items) != total:
                        raise RuntimeError(f'{label}: pagination count mismatch')
                    check_order(items, f'{label}/{sort}')
                checks.append(label)
            check_order(workbench.products_for_export({}), 'inventory-export')
            checks.append('inventory-export')
    else:
        if any(item['stock'] < 0 or any(size['stock'] < 0 for size in item.get('sizePrices', [])) for item in products):
            raise RuntimeError('storefront: negative stock exposed to customers')
        checks.append('public-stock')
    print(json.dumps({'categoryOrderVerification': 'passed', 'backend': args.backend,
                      'activeProducts': len(products), 'checks': checks}))
