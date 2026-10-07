"""Post-release read-only checks; no login sessions or application startup."""
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
import sales_ownership

with db._connect() as conn:
    conn.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
    @contextmanager
    def read_connection():
        yield conn
    db.get_connection = read_connection
    for table, column in [('store_users', 'linked_admin_user_id'), ('orders', 'owner_admin_id'), ('orders', 'order_source')]:
        if not conn.execute('SELECT 1 FROM information_schema.columns WHERE table_schema=%s AND table_name=%s AND column_name=%s', ('public', table, column)).fetchone():
            raise RuntimeError('Ownership schema incomplete')
    linked = conn.execute('SELECT count(*) AS n FROM store_users WHERE linked_admin_user_id IS NOT NULL').fetchone()['n']
    checks = ['ownership-schema']
    checked = 0
    if args.backend == 'admin-backend':
        from flask import Flask, g
        import customer_templates
        import module_permissions
        import workbench
        users = conn.execute("SELECT id,name,role,status,permissions FROM admin_users WHERE role='sales' AND status='active' ORDER BY id").fetchall()
        with Flask('sales-access-verification').test_request_context():
            g.current_user = {'id': None, 'role': 'admin'}
            templates = customer_templates.listing({'pageSize': 100})
            total = conn.execute('SELECT count(*) AS n FROM order_customer_templates').fetchone()['n']
            if templates['total'] != total:
                raise RuntimeError('Administrator template scope mismatch')
            for user in users:
                g.current_user = dict(user)
                owner = sales_ownership.scope({'salespersonId': 999999, '_ownerId': 999999}, user)
                if owner != user['id']:
                    raise RuntimeError('Salesperson scope is client-controlled')
                orders = workbench.orders_page({'_ownerId': owner, 'pageSize': 100})
                expected = conn.execute('SELECT count(*) AS n FROM orders WHERE owner_admin_id=%s', (owner,)).fetchone()['n']
                if orders['total'] != expected or any(row['ownerAdminId'] != owner for row in orders['items']):
                    raise RuntimeError('Salesperson order isolation mismatch')
                dashboard = workbench.dashboard({'_ownerId': owner})
                if set(dashboard['snapshot']) != {'statuses'}:
                    raise RuntimeError('Company inventory exposed in personal dashboard')
                sales_ownership.personalize(dashboard, owner)
                if 'temporaryInbound' in json.dumps(dashboard):
                    raise RuntimeError('Temporary inventory exposed in personal dashboard')
                own_templates = customer_templates.listing({'pageSize': 100})
                expected_templates = conn.execute('SELECT count(*) AS n FROM order_customer_templates WHERE created_by_admin_id=%s', (owner,)).fetchone()['n']
                if own_templates['total'] != expected_templates or any(row['creatorId'] != owner for row in own_templates['items']):
                    raise RuntimeError('Template creator isolation mismatch')
                other = conn.execute('SELECT id FROM order_customer_templates WHERE created_by_admin_id IS DISTINCT FROM %s LIMIT 1', (owner,)).fetchone()
                if other and customer_templates.detail(other['id']) is not None:
                    raise RuntimeError('Foreign template detail exposed')
                if 'dashboard' not in module_permissions.effective(user):
                    raise RuntimeError('Active salesperson missing dashboard permission')
                checked += 1
        checks += ['personal-order-scope', 'personal-dashboard-boundary', 'template-creator-scope', 'sales-dashboard-permission']
    else:
        sample = {'ownerAdminId': 1, 'ownerAdminName': 'internal', 'createdByAdminId': 1, 'orderSource': 'store', 'id': 1}
        if set(sales_ownership.public_order(sample)) != {'id'}:
            raise RuntimeError('Internal attribution exposed to customers')
        checks += ['public-order-boundary']
    print(json.dumps({'checks': checks, 'linkedAccounts': linked, 'salespeopleChecked': checked, 'readOnly': True}))
