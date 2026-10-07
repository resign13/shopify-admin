"""Read-only production checks: no sessions, migrations or inventory writes."""
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


def check_public(value):
    if isinstance(value, list):
        for item in value: check_public(item)
    elif isinstance(value, dict):
        if 'temporaryInbound' in value:
            raise RuntimeError('Internal temporary quantity exposed to customers')
        if 'stock' in value and value['stock'] < 0:
            raise RuntimeError('Negative stock exposed to customers')
        for child in value.values(): check_public(child)


with db._connect() as conn:
    conn.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')

    @contextmanager
    def read_connection():
        yield conn
    db.get_connection = read_connection
    column = conn.execute("SELECT data_type,is_nullable,column_default FROM information_schema.columns WHERE table_schema='public' AND table_name='product_size_prices' AND column_name='temporary_inbound'").fetchone()
    if not column or column['data_type'] != 'integer' or column['is_nullable'] != 'NO' or column['column_default'] != '0':
        raise RuntimeError('Temporary quantity schema/default incompatible')
    constraint = conn.execute("SELECT 1 FROM pg_constraint WHERE conrelid='product_size_prices'::regclass AND conname='product_size_prices_temporary_inbound_check' AND convalidated").fetchone()
    if not constraint:
        raise RuntimeError('Temporary quantity nonnegative constraint missing')
    invalid = conn.execute('SELECT count(*) AS n FROM product_size_prices WHERE contract_pending<0 OR pending_inspection<0 OR pending_inbound<0 OR temporary_inbound<0').fetchone()['n']
    mismatches = conn.execute('SELECT count(*) AS n FROM products p JOIN (SELECT product_id,SUM(stock) AS balance FROM product_size_prices GROUP BY product_id) s ON s.product_id=p.id WHERE p.stock<>s.balance').fetchone()['n']
    if invalid or mismatches:
        raise RuntimeError(f'Inventory consistency failed: invalid stages={invalid}, parent mismatches={mismatches}')
    products = db.list_products()
    if args.backend == 'admin-backend':
        from inventory_policy import public_inventory
        products = public_inventory(products)
    check_public(products)
    checks = ['temporary-column', 'nonnegative-stages', 'parent-balance', 'public-field-boundary']
    if args.backend == 'admin-backend':
        from flask import Flask, g
        import workbench
        if not conn.execute("SELECT to_regclass('inventory_registration_logs') AS logs,to_regclass('idx_inventory_registration_product_time') AS idx").fetchone()['idx']:
            raise RuntimeError('Registration history schema/index missing')
        internal = db.list_products(include_contract_pending=True, include_inactive=True)
        if any('temporaryInbound' not in s for p in internal for s in p.get('sizePrices', [])):
            raise RuntimeError('Internal inventory missing temporary quantity')
        with Flask('temporary-inbound-verification').test_request_context():
            g.current_user = {'role': 'admin'}
            page = workbench.products_page({'page': 1, 'pageSize': 25, 'sort': 'category'}, pending=True)
            if 'temporaryInbound' not in page['summary']:
                raise RuntimeError('Inventory summary missing temporary quantity')
            if internal:
                history = workbench.inventory_registrations_page(internal[0]['id'], {})
                if history['pageSize'] != 10 or len(history['items']) > 10:
                    raise RuntimeError('Registration history pagination incompatible')
        checks += ['internal-size-quantity', 'inventory-summary', 'registration-history-pagination']
    print(json.dumps({'checks': checks, 'publicProducts': len(products), 'readOnly': True}))
