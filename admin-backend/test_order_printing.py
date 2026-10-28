"""Warehouse export marks, guarded by the shared local *_test fixture."""
from io import BytesIO
import unittest
from unittest.mock import patch
from flask.testing import FlaskClient
from psycopg.errors import ForeignKeyViolation
from openpyxl import load_workbook
from werkzeug.security import generate_password_hash
from test_workbench import application, db, seed
import order_printing


class OrderPrintingTest(unittest.TestCase):
    def setUp(self):
        self.tokens, _ = seed()
        application.app.config['TESTING'] = True

    def call(self, route, method='GET', role='warehouse'):
        with application.app.test_client() as client:
            return client.open('/api/admin/' + route, method=method,
                               headers={'Authorization': 'Bearer ' + self.tokens[role]})

    def marks(self):
        return db._fetch_all('SELECT * FROM order_warehouse_prints ORDER BY order_id')

    def snapshot(self):
        return {table: db._fetch_all(f'SELECT to_jsonb(t) AS row FROM {table} t ORDER BY id')
                for table in ('orders', 'order_items', 'products', 'product_size_prices',
                              'inventory_registration_logs', 'admin_audit_logs')}

    def test_successful_selected_export_marks_list_and_detail_without_business_changes(self):
        before = self.snapshot()
        response = self.call('orders/export?view=workbench&orderIds=1,2&includeImages=0', 'POST')
        self.assertEqual(response.status_code, 200)
        self.assertEqual([r['order_id'] for r in self.marks()], [1, 2])
        self.assertEqual(self.snapshot(), before)
        rows = self.call('orders?page=1&pageSize=25').json['items']
        self.assertEqual({r['id'] for r in rows if r['warehousePrinted']}, {1, 2})
        for role in ('warehouse', 'admin'):
            order = self.call('orders/1', role=role).json['order']
            self.assertTrue(order['warehousePrinted'])
            self.assertTrue(order['warehousePrintedAt'])
            self.assertEqual(order['warehousePrintedBy'], '王仓管')
            if role == 'warehouse':
                self.assertNotIn('totalAmount', order)
                self.assertNotIn('unitPrice', order['items'][0])
        sheet = load_workbook(BytesIO(response.data)).active
        self.assertFalse(any('单价' in str(c.value) for row in sheet for c in row))

    def test_both_export_types_keep_first_mark_and_filter_intersection(self):
        query = '?view=workbench&status=paid&orderIds=1,2,999999&includeImages=0'
        self.assertEqual(self.call('orders/export-by-sheet' + query, 'POST').status_code, 200)
        first = self.marks()
        self.assertEqual([r['order_id'] for r in first], [1])
        self.assertEqual(first[0]['export_kind'], 'export-by-sheet')
        self.assertEqual(self.call('orders/export' + query, 'POST').status_code, 200)
        self.assertEqual(self.marks(), first)
        with db.get_connection() as conn:
            order_printing.migrate(conn.cursor())
            order_printing.migrate(conn.cursor())
        self.assertEqual(self.marks(), first)

    def test_mark_visible_to_every_authorized_department_with_order_scope_preserved(self):
        db._fetch_one('UPDATE orders SET owner_admin_id=2 WHERE id=1 RETURNING id')
        self.assertEqual(self.call('orders/export?orderIds=1&includeImages=0', 'POST').status_code, 200)
        finance = db.create_admin_user({'name':'财务验收','email':'finance-print@gingtto.test',
            'passwordHash':generate_password_hash('Fixture-Only',method='pbkdf2:sha256:1000'),
            'role':'finance','status':'active','permissions':['finance','orders']})
        self.tokens['finance'] = db.create_admin_session(finance['id'])
        for role in ('admin','sales','warehouse','finance'):
            with self.subTest(role=role):
                order = self.call('orders/1', role=role).json['order']
                self.assertTrue(order['warehousePrinted'])
                rows = self.call('orders?page=1&pageSize=25', role=role).json['items']
                self.assertTrue(next(row for row in rows if row['id']==1)['warehousePrinted'])
        db._fetch_one('UPDATE orders SET owner_admin_id=NULL WHERE id=1 RETURNING id')
        self.assertEqual(self.call('orders/1', role='sales').status_code, 404)
        rows = self.call('orders?page=1&pageSize=25', role='sales').json['items']
        self.assertNotIn(1, [row['id'] for row in rows])
        db._fetch_one("UPDATE admin_users SET permissions='[\"finance\"]' WHERE id=%s RETURNING id",(finance['id'],))
        self.assertEqual(self.call('orders/1', role='finance').status_code, 403)
        self.assertEqual(self.call('orders/1', role='customer').status_code, 403)

    def test_nonwarehouse_exports_and_empty_results_do_not_mark(self):
        for kind in ('export', 'export-by-sheet'):
            query = '?view=workbench&orderIds=1&includeImages=0'
            for method in ('GET', 'POST'):
                self.assertEqual(self.call('orders/' + kind + query, method, role='admin').status_code, 200)
            self.assertEqual(self.call('orders/' + kind + '?view=workbench&orderIds=999999&includeImages=0', 'POST').status_code, 200)
        db._fetch_one('UPDATE orders SET owner_admin_id=2 WHERE id=1 RETURNING id')
        self.assertEqual(self.call('orders/export?view=workbench&orderIds=1&includeImages=0', 'POST', role='sales').status_code, 200)
        self.assertEqual(self.marks(), [])

    def test_auth_csrf_revocation_and_read_only_get_cannot_create_marks(self):
        for kind in ('export', 'export-by-sheet'):
            route = 'orders/' + kind + '?orderIds=1&includeImages=0'
            response = self.call(route)
            self.assertEqual(response.status_code, 405)
            self.assertEqual(response.headers['Allow'], 'POST')
            self.assertEqual(self.call(route, 'POST', role='customer').status_code, 403)
            raw = FlaskClient(application.app, use_cookies=True)
            self.assertEqual(raw.post('/api/admin/' + route).status_code, 401)
            raw.set_cookie(application.security.cookie, self.tokens['warehouse'])
            self.assertEqual(raw.post('/api/admin/' + route).status_code, 403)
        db._fetch_one("UPDATE admin_users SET permissions='[]' WHERE role='warehouse' RETURNING id")
        self.assertEqual(self.call('orders/export?orderIds=1&includeImages=0', 'POST').status_code, 403)
        self.assertEqual(self.marks(), [])

    def test_export_failure_and_batch_failure_leave_no_partial_marks(self):
        before = self.snapshot()
        for kind, builder_kind in (('export', 'combined'), ('export-by-sheet', 'split')):
            with patch.object(application.order_export_process, 'build', side_effect=RuntimeError('Synthetic render failure')) as mocked:
                response = self.call('orders/' + kind + '?orderIds=1,2&includeImages=0', 'POST')
                self.assertEqual(response.status_code, 500)
                self.assertNotIn('Content-Disposition', response.headers)
                mocked.assert_called_once()
                self.assertEqual(mocked.call_args.args[0], builder_kind)
            self.assertEqual(self.marks(), [])
        with patch.object(application, 'send_file', side_effect=RuntimeError('Synthetic response failure')):
            self.assertEqual(self.call('orders/export?orderIds=1&includeImages=0', 'POST').status_code, 500)
        with patch.object(order_printing, 'record', side_effect=RuntimeError('Synthetic mark failure')):
            response = self.call('orders/export?orderIds=1&includeImages=0', 'POST')
            self.assertEqual(response.status_code, 500)
            self.assertNotIn('Content-Disposition', response.headers)
        actor = {'id': 3, 'name': '王仓管', 'role': 'warehouse'}
        with self.assertRaises(ForeignKeyViolation):
            order_printing.record(db, [{'id': 1}, {'id': 999999}], actor, 'export')
        self.assertEqual(self.marks(), [])
        self.assertEqual(self.snapshot(), before)


if __name__ == '__main__':
    unittest.main()
