"""Account attribution and row-level access, using guarded synthetic fixtures only."""
import copy
import io
import json
from pathlib import Path
import subprocess
import sys
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

from test_workbench import seed, application, db
import sales_ownership


class SalesOwnershipTest(unittest.TestCase):
    def setUp(self):
        self.tokens, _ = seed()
        application.app.config['TESTING'] = True
        self.a = db.get_admin_user_by_email('sales@gingtto.test')['id']
        self.b = db.create_admin_user({'name': 'Sales B', 'email': 'sales-b@fixture.test',
                                     'passwordHash': 'fixture', 'role': 'sales', 'status': 'active'})['id']
        self.tokens['b'] = db.create_admin_session(self.b)

    def call(self, path, method='GET', body=None, role='admin'):
        with application.app.test_client() as client:
            return client.open('/api/admin/' + path, method=method, json=body,
                               headers={'Authorization': 'Bearer ' + self.tokens[role]})

    def link(self, owner):
        return self.call('store-users/1', 'PUT', {'linkedAdminId': owner})

    def stock(self):
        return db._fetch_all('SELECT product_id,size_code,stock,contract_pending,pending_inspection,pending_inbound '
                             'FROM product_size_prices ORDER BY product_id,size_code')

    def backend(self, role='admin', **extra):
        body = {'requestId': str(uuid.uuid4()), 'userId': 1, 'contactName': 'Fixture', 'phone': '123',
                'country': 'Germany', 'address': 'Fixture', 'shippingFee': 0,
                'items': [{'productId': 1, 'sizeCode': 'M', 'quantity': 1, 'unitPrice': 10}], **extra}
        return self.call('orders', 'POST', body, role)

    def owners(self):
        return {r['id']: r['owner_admin_id'] for r in db._fetch_all('SELECT id,owner_admin_id FROM orders')}

    def scoped_fixture(self):
        db._fetch_one('UPDATE orders SET owner_admin_id=%s WHERE id=2 RETURNING id', (self.b,))
        self.assertEqual(self.link(self.a).status_code, 200)

    def test_link_backfills_store_history_once_without_stock_changes(self):
        backend = self.backend().json['order']['id']
        db._fetch_one('UPDATE orders SET owner_admin_id=%s WHERE id=2 RETURNING id', (self.b,))
        before = self.stock()
        response = self.link(self.a)
        self.assertEqual(response.status_code, 200, response.json)
        self.assertEqual(response.json['user']['linkedAdminId'], self.a)
        self.assertEqual(self.owners(), {1: self.a, 2: self.b, 3: self.a, 4: self.a, backend: None})
        self.assertEqual(self.link(self.b).status_code, 200)
        self.assertEqual(self.link(None).status_code, 200)
        self.assertEqual(self.owners()[1], self.a)
        self.assertEqual(self.stock(), before)
        self.assertGreater(db._fetch_one("SELECT count(*) AS n FROM admin_audit_logs WHERE entity_table='orders' AND action='UPDATE'")['n'], 0)
        for owner in [1, 3, 99999, True, -1]:
            self.assertEqual(self.link(owner).status_code, 400)
            self.assertIsNone(db.get_store_user_by_id(1)['linkedAdminId'])
        self.assertEqual(self.call('store-users/1', 'PUT', {'linkedAdminId': self.a}, 'sales').status_code, 403)

    def test_backend_owner_creator_reassignment_and_forgery(self):
        response = self.backend('sales')
        self.assertEqual(response.status_code, 200, response.json)
        order = response.json['order']
        self.assertEqual((order['ownerAdminId'], order['createdByAdminId'], order['orderSource']), (self.a, self.a, 'backend'))
        self.assertEqual(self.backend('sales', ownerAdminId=self.b).status_code, 400)
        self.assertEqual(self.backend(ownerAdminId=self.b).json['order']['ownerAdminId'], self.b)
        before = self.stock()
        edit = self.call(f"orders/{order['id']}").json['order']
        edit['ownerAdminId'] = self.b
        response = self.call(f"orders/{order['id']}/details", 'PUT', edit)
        self.assertEqual(response.status_code, 200, response.json)
        self.assertEqual(response.json['order']['createdByAdminId'], self.a)
        self.assertEqual(self.stock(), before)
        self.assertEqual(self.call(f"orders/{order['id']}", role='sales').status_code, 404)
        self.assertEqual(self.call(f"orders/{order['id']}", role='b').status_code, 200)

    def test_all_order_reads_mutations_and_exports_are_scoped(self):
        self.scoped_fixture()
        for params in ['', '?page=1', f'?page=1&salespersonId={self.b}&_ownerId={self.b}']:
            response = self.call('orders' + params, role='sales')
            data = response.json
            items = data.get('items', data.get('orders', []))
            self.assertEqual({r['id'] for r in items}, {1, 3, 4})
            if 'statusCounts' in data: self.assertEqual(sum(data['statusCounts'].values()), 3)
        for path, method, body in [('orders/2', 'GET', None), ('orders/2/invoice', 'GET', None),
                                   ('orders/2', 'PUT', {'status': 'paid'}),
                                   ('orders/2/details', 'PUT', {})]:
            self.assertEqual(self.call(path, method, body, 'sales').status_code, 404, path)
        self.assertEqual(self.call('orders/1', role='sales').status_code, 200)
        self.assertEqual(self.call('orders/2', role='warehouse').status_code, 200)
        self.assertEqual(self.call('orders/2', role='admin').status_code, 200)
        for route, builder in [('export', 'build_orders_export'), ('export-by-sheet', 'build_orders_sheet_export')]:
            for query in ['', 'view=workbench&', f'view=workbench&salespersonId={self.b}&']:
                with patch.object(application, builder, return_value=io.BytesIO(b'fixture')) as mocked:
                    response = self.call(f'orders/{route}?{query}orderIds=1,2,3,4', role='sales')
                    self.assertEqual(response.status_code, 200, response.json)
                    self.assertEqual({r['id'] for r in mocked.call_args.args[0]}, {1, 3, 4})
        for selected in [str(self.b), 'unassigned', 'invalid', '999999']:
            response = self.call('orders?page=1&salespersonId=' + selected)
            self.assertEqual(response.status_code, 200 if selected in [str(self.b), 'unassigned'] else 400)

    def test_dashboard_all_views_and_drilldowns_use_trusted_owner(self):
        self.scoped_fixture()
        query = f'dateFrom=2026-09-18&dateTo=2026-09-18&salespersonId={self.b}&_ownerId={self.b}'
        response = self.call('dashboard?view=workbench&' + query, role='sales')
        self.assertEqual(response.status_code, 200, response.json)
        data = response.json
        self.assertEqual((data['metrics']['orders'], data['metrics']['units']), (1, 3))
        self.assertEqual({r['id'] for r in data['recentOrders']}, {1, 3})
        self.assertEqual(data['snapshot']['statuses'], {'paid': 1, 'cancelled': 1, 'completed': 1})
        self.assertEqual(data['filters']['countries'], ['France', 'Germany'])
        self.assertNotIn('stock', data['snapshot'])
        for view in ['style-performance', 'style-detail', 'style-size-detail']:
            response = self.call(f'dashboard?view={view}&styleCode=GT-2026&productId=1&{query}', role='sales')
            self.assertEqual(response.status_code, 200, response.json)
            data = response.json
            self.assertEqual(data['scope']['ownerId'], self.a)
            self.assertNotIn('stock', json.dumps(data))
            self.assertNotIn('estimatedDays', json.dumps(data))
            if view == 'style-performance': self.assertEqual(data['summary']['units'], 3)
        legacy = self.call('dashboard?' + query, role='sales')
        self.assertEqual(legacy.status_code, 200)
        self.assertEqual(next(r['value'] for r in legacy.json['stats'] if r['label'] == 'Orders'), 3)
        own = self.call('dashboard?view=workbench&' + query).json
        self.assertEqual(own['metrics']['units'], 3)
        global_data = self.call('dashboard?view=workbench&dateFrom=2026-09-18&dateTo=2026-09-18').json
        self.assertEqual(global_data['metrics']['units'], 6)
        self.assertIn('stock', global_data['snapshot'])

    def test_owner_identity_protection_and_disabled_history(self):
        self.scoped_fixture()
        self.assertEqual(self.call(f'admin-users/{self.a}', 'DELETE').status_code, 400)
        self.assertEqual(self.call(f'admin-users/{self.a}', 'PUT', {'role': 'warehouse'}).status_code, 400)
        self.assertEqual(self.call(f'admin-users/{self.a}', 'PUT', {'status': 'disabled'}).status_code, 200)
        self.assertEqual(self.link(self.a).status_code, 200)
        self.assertEqual(self.call('salespeople', role='sales').status_code, 401)
        self.assertEqual(self.call('salespeople', role='warehouse').status_code, 403)
        self.assertEqual([r['id'] for r in self.call('salespeople', role='b').json['items']], [self.b])

    def test_idempotent_replay_does_not_disclose_a_reassigned_order(self):
        body = {'requestId': str(uuid.uuid4()), 'userId': 1, 'contactName': 'Fixture', 'phone': '123',
                'country': 'Germany', 'address': 'Fixture', 'shippingFee': 0,
                'items': [{'productId': 1, 'sizeCode': 'M', 'quantity': 1, 'unitPrice': 10}]}
        created = self.call('orders', 'POST', body, 'sales').json['order']
        edit = self.call(f"orders/{created['id']}").json['order']
        edit['ownerAdminId'] = self.b
        self.assertEqual(self.call(f"orders/{created['id']}/details", 'PUT', edit).status_code, 200)
        before = self.stock()
        self.assertEqual(self.call('orders', 'POST', body, 'sales').status_code, 404)
        self.assertEqual(self.stock(), before)

    def test_compatibility_service_does_not_expose_internal_links_or_owners(self):
        self.scoped_fixture()
        with application.app.test_client() as client:
            headers = {'X-Service-Token': application.SERVICE_TOKEN}
            for path in ['store-users/1', 'orders?userId=1', 'orders?page=1']:
                response = client.get('/api/internal/' + path, headers=headers)
                self.assertEqual(response.status_code, 200, response.json)
                for field in ['linkedAdminId', 'linkedAdminName', 'ownerAdminId', 'ownerAdminName', 'createdByAdminId']:
                    self.assertNotIn(field, json.dumps(response.json))

    def test_migration_is_idempotent_and_preserves_explicit_unassignment(self):
        db._fetch_one('UPDATE orders SET created_by_admin_id=%s WHERE id=1 RETURNING id', (self.a,))
        with db._connect() as conn:
            cur = conn.cursor()
            cur.execute("DELETE FROM sales_ownership_migrations WHERE name='initial-owner-v1'")
            sales_ownership.migrate(cur)
            cur.execute('SELECT owner_admin_id,order_source FROM orders WHERE id=1')
            self.assertEqual(dict(cur.fetchone()), {'owner_admin_id': self.a, 'order_source': 'backend'})
            cur.execute('UPDATE orders SET owner_admin_id=NULL WHERE id=1')
            sales_ownership.migrate(cur)
            sales_ownership.migrate(cur)
            cur.execute('SELECT owner_admin_id FROM orders WHERE id=1')
            self.assertIsNone(cur.fetchone()['owner_admin_id'])
        self.assertEqual(self.owners()[1], None)

    def store_script(self, code):
        backend = Path(__file__).resolve().parents[2] / 'shopify/storefront-backend'
        if not backend.exists(): self.skipTest('Sibling storefront checkout not available')
        output = subprocess.check_output([sys.executable, '-c', code], cwd=backend, text=True, encoding='utf-8', timeout=90)
        return json.loads(output)

    def test_storefront_new_orders_use_link_not_client_input_and_hide_internal_fields(self):
        self.assertEqual(self.link(self.a).status_code, 200)
        code = '''import db,json
db.ensure_database_ready()
order=db.create_order({'userId':1,'ownerAdminId':5,'contactName':'Fixture','phone':'123',
 'shippingAddress':'Fixture','items':[{'productId':1,'sizeCode':'M','quantity':1}]})
print(json.dumps(order))'''
        order = self.store_script(code)
        self.assertNotIn('ownerAdminId', order)
        self.assertNotIn('createdByAdminId', order)
        row = db._fetch_one('SELECT owner_admin_id,created_by_admin_id,order_source FROM orders WHERE id=%s', (order['id'],))
        self.assertEqual(dict(row), {'owner_admin_id': self.a, 'created_by_admin_id': None, 'order_source': 'store'})
        self.assertEqual(self.link(self.b).status_code, 200)
        next_order = self.store_script(code)
        self.assertEqual(self.owners()[order['id']], self.a)
        self.assertEqual(self.owners()[next_order['id']], self.b)

    def test_concurrent_link_and_store_creation_leave_no_unassigned_order(self):
        code = '''import db,json
print(json.dumps(db.create_order({'userId':1,'contactName':'Fixture','phone':'123',
 'shippingAddress':'Fixture','items':[{'productId':1,'sizeCode':'M','quantity':1}]})))'''
        with ThreadPoolExecutor(max_workers=2) as pool:
            created = pool.submit(self.store_script, code)
            linked = pool.submit(self.link, self.a)
            self.assertEqual(linked.result(timeout=90).status_code, 200)
            order = created.result(timeout=90)
        self.assertEqual(self.owners()[order['id']], self.a)

    def test_concurrent_link_and_ownership_edit_use_consistent_lock_order(self):
        edit = self.call('orders/1').json['order']
        edit['ownerAdminId'] = self.b
        edit['address'] = edit['shippingAddress']
        before = self.stock()
        with ThreadPoolExecutor(max_workers=2) as pool:
            linked = pool.submit(self.link, self.a)
            edited = pool.submit(self.call, 'orders/1/details', 'PUT', edit)
            link_result = linked.result(timeout=30)
            edit_result = edited.result(timeout=30)
        self.assertEqual(link_result.status_code, 200, link_result.json)
        # If linking wins, the explicit edit sees the updated version and asks
        # the operator to re-read. Either order is valid; no deadlock or lost update.
        self.assertIn(edit_result.status_code, [200, 409], edit_result.json)
        self.assertEqual(self.owners()[1], self.b if edit_result.status_code == 200 else self.a)
        self.assertEqual(self.stock(), before)

    def test_concurrent_link_and_backend_creation_use_consistent_lock_order(self):
        with ThreadPoolExecutor(max_workers=2) as pool:
            linked = pool.submit(self.link, self.a)
            created = pool.submit(self.backend, 'admin', ownerAdminId=self.b)
            link_result = linked.result(timeout=30)
            create_result = created.result(timeout=30)
        self.assertEqual(link_result.status_code, 200, link_result.json)
        self.assertEqual(create_result.status_code, 200, create_result.json)
        self.assertEqual(create_result.json['order']['ownerAdminId'], self.b)
        self.assertEqual(self.owners()[1], self.a)


if __name__ == '__main__':
    unittest.main()
