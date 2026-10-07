"""Customer presets, shared access, snapshots and stock neutrality in a *_test DB."""
import copy
import io
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from test_workbench import seed, application, db
import customer_templates


class CustomerTemplatesTest(unittest.TestCase):
    def setUp(self):
        self.tokens, _ = seed()
        application.app.config['TESTING'] = True

    def call(self, path, method='GET', body=None, role='admin', **kwargs):
        with application.app.test_client() as client:
            return client.open('/api/admin/' + path, method=method, json=body,
                               headers={'Authorization': 'Bearer ' + self.tokens[role]}, **kwargs)

    def payload(self):
        return {'name': '德国客户 · 常用地址', 'profile': {
            'userId': 1, 'contactName': 'Alex Customer', 'phone': '123456',
            'country': 'Germany', 'contactValue': 'alex@example.test',
            'address': '18 Market Street', 'apartment': 'Room 10', 'city': 'Berlin',
            'state': 'Berlin', 'zip': '10000', 'note': 'Keep separate labels',
            'labelImageUrls': ['/uploads/a.jpg', '/uploads/b.jpg'], 'labelPdfUrl': '/uploads/packing.pdf'}}

    def create(self, role='admin'):
        response = self.call('orders/templates', 'POST', self.payload(), role)
        self.assertEqual(response.status_code, 200, response.json)
        return response.json['template']

    def balances(self):
        return (db._fetch_all('SELECT id,stock FROM products ORDER BY id'),
                db._fetch_all('SELECT id,stock FROM product_size_prices ORDER BY id'),
                db._fetch_one('SELECT COUNT(*) AS n FROM orders'))

    def test_shared_crud_paging_search_and_stock_neutrality(self):
        before = self.balances()
        item = self.create('sales')
        for role in ('admin', 'sales'):
            self.assertEqual(self.call(f"orders/templates/{item['id']}", role=role).json['template']['profile'], self.payload()['profile'])
        listing = self.call('orders/templates?page=1&pageSize=25&keyword=Northline').json
        self.assertEqual(listing['total'], 1)
        self.assertNotIn('profile', listing['items'][0])
        self.assertTrue(listing['items'][0]['customerActive'])
        updated = self.call(f"orders/templates/{item['id']}", 'PUT', {**self.payload(), 'name': 'Changed', 'version': item['version']})
        self.assertEqual(updated.status_code, 200, updated.json)
        self.assertEqual(updated.json['template']['creatorId'], item['creatorId'])
        self.assertEqual(self.call(f"orders/templates/{item['id']}", 'DELETE', {'version': updated.json['template']['version']}, 'sales').status_code, 200)
        self.assertEqual(self.call(f"orders/templates/{item['id']}").status_code, 404)
        self.assertEqual(self.balances(), before)
        logs = db._fetch_all("SELECT * FROM admin_audit_logs WHERE entity_table='order_customer_templates' ORDER BY id")
        self.assertEqual([row['action'] for row in logs], ['INSERT', 'UPDATE', 'DELETE'])
        self.assertTrue(all(row['module'] == 'orders' for row in logs))
        self.assertTrue(all('customer_info' not in (row['after_data'] or {}) for row in logs))

    def test_versions_concurrent_edit_delete_and_rollback(self):
        item = self.create()
        body = {**self.payload(), 'version': item['version']}
        def update(index):
            return self.call(f"orders/templates/{item['id']}", 'PUT', {**body, 'name': f'Concurrent {index}'})
        with ThreadPoolExecutor(max_workers=2) as pool:
            responses = list(pool.map(update, range(2)))
        self.assertEqual(sorted(response.status_code for response in responses), [200, 409])
        self.assertEqual(self.call(f"orders/templates/{item['id']}", 'DELETE', {'version': item['version']}).status_code, 409)
        fresh = self.call(f"orders/templates/{item['id']}").json['template']
        self.assertEqual(fresh['version'], '2')
        self.assertEqual(self.call(f"orders/templates/{item['id']}", 'PUT', self.payload()).status_code, 400)
        self.assertEqual(self.call(f"orders/templates/{item['id']}", 'DELETE', []).status_code, 400)
        self.assertEqual(self.call(f"orders/templates/{item['id']}").json['template'], fresh)

    def test_validation_and_only_customer_fields_are_saved(self):
        before = self.balances()
        for change in [lambda body: body.update(name=' '), lambda body: body.update(name='a' * 121),
                       lambda body: body.update(profile=[]), lambda body: body['profile'].update(userId=999),
                       lambda body: body['profile'].update(contactName='a' * 501),
                       lambda body: body['profile'].update(note='a' * 5001),
                       lambda body: body['profile'].update(labelImageUrls=['/uploads/a.jpg'] * 2),
                       lambda body: body['profile'].update(labelImageUrls=[f'/uploads/{i}.jpg' for i in range(10)]),
                       lambda body: body['profile'].update(labelImageUrls=['javascript:alert.jpg']),
                       lambda body: body['profile'].update(labelPdfUrl='javascript:packing.pdf'),
                       lambda body: body['profile'].update(labelPdfUrl='/uploads/no.jpg')]:
            body = self.payload(); change(body)
            response = self.call('orders/templates', 'POST', body)
            self.assertEqual(response.status_code, 400, response.json)
        self.assertEqual(self.call('orders/templates?pageSize=999').status_code, 400)
        body = self.payload()
        body['profile'].update(items=[{'quantity': 99}], status='completed', shippingFee=999, requestId=str(uuid.uuid4()))
        saved = self.call('orders/templates', 'POST', body).json['template']['profile']
        self.assertEqual(saved, self.payload()['profile'])
        self.assertEqual(self.balances(), before)

    def test_role_and_module_permissions_for_all_endpoints(self):
        item = self.create()
        for role in ('warehouse', 'customer'):
            for path, method, body in [('orders/templates', 'GET', None), ('orders/templates', 'POST', self.payload()),
                                       (f"orders/templates/{item['id']}", 'GET', None),
                                       (f"orders/templates/{item['id']}", 'PUT', {**self.payload(), 'version': item['version']}),
                                       (f"orders/templates/{item['id']}", 'DELETE', {'version': item['version']}),
                                       ('orders/templates/attachments', 'POST', None)]:
                self.assertEqual(self.call(path, method, body, role).status_code, 403)
        db._fetch_one("UPDATE admin_users SET permissions='[]'::jsonb WHERE role='sales' RETURNING id")
        self.assertEqual(self.call('orders/templates', role='sales').status_code, 403)
        self.assertEqual(self.call('orders/templates', 'POST', self.payload(), 'sales').status_code, 403)
        with application.app.test_client() as client:
            self.assertEqual(client.get('/api/admin/orders/templates').status_code, 401)

    def test_templates_are_snapshots_for_order_and_do_not_reference_later_edits(self):
        item = self.create()
        body = {**item['profile'], 'requestId': str(uuid.uuid4()),
                'items': [{'productId': 1, 'sizeCode': 'M', 'quantity': 2, 'unitPrice': 20}]}
        created = self.call('orders', 'POST', body)
        self.assertEqual(created.status_code, 200, created.json)
        order = self.call(f"orders/{created.json['order']['id']}").json['order']
        self.assertEqual(order['note'], item['profile']['note'])
        self.assertEqual(order['labelImageUrls'], ['/uploads/a.jpg', '/uploads/b.jpg', '/uploads/packing.pdf'])
        after_order = self.balances()
        changed = self.payload(); changed['profile'].update(note='New template note', labelImageUrls=[])
        updated = self.call(f"orders/templates/{item['id']}", 'PUT', {**changed, 'version': item['version']}).json['template']
        self.assertEqual(self.call(f"orders/templates/{item['id']}", 'DELETE', {'version': updated['version']}).status_code, 200)
        self.assertEqual(self.call(f"orders/{order['id']}").json['order'], order)
        self.assertEqual(self.balances(), after_order)

    def test_pdf_validation_in_order_and_legacy_pdf_preservation(self):
        item = self.create()
        body = {**item['profile'], 'requestId': str(uuid.uuid4()),
                'items': [{'productId': 1, 'sizeCode': 'M', 'quantity': 2, 'unitPrice': 20}]}
        before = self.balances()
        self.assertEqual(self.call('orders', 'POST', {**body, 'labelPdfUrl': '//evil.test/a.pdf'}).status_code, 400)
        self.assertEqual(self.balances(), before)
        created = self.call('orders', 'POST', body).json['order']
        order = self.call(f"orders/{created['id']}").json['order']
        edit = copy.deepcopy(order); edit.pop('labelPdfUrl'); edit['labelImageUrls'] = []
        response = self.call(f"orders/{order['id']}/details", 'PUT', edit)
        self.assertEqual(response.status_code, 200, response.json)
        self.assertEqual(response.json['order']['labelImageUrls'], ['/uploads/packing.pdf'])
        edit = self.call(f"orders/{order['id']}").json['order']; edit['labelPdfUrl'] = ''; edit['labelImageUrls'] = []
        self.assertEqual(self.call(f"orders/{order['id']}/details", 'PUT', edit).json['order']['labelImageUrls'], [])

    def test_pdf_upload_and_invalid_files(self):
        before = self.balances()
        with TemporaryDirectory() as directory, patch.object(application, 'UPLOAD_DIR', Path(directory)):
            def upload(raw, name='packing.pdf'):
                with application.app.test_client() as client:
                    return client.post('/api/admin/orders/templates/attachments',
                                       headers={'Authorization': 'Bearer ' + self.tokens['sales']},
                                       data={'files': (io.BytesIO(raw), name)}, content_type='multipart/form-data')
            self.assertEqual(upload(b'not PDF').status_code, 400)
            self.assertEqual(upload(b'%PDF-1.4\n', 'bad.html').status_code, 400)
            self.assertEqual(upload(b'%PDF-' + b'x' * (32 * 1024 * 1024)).status_code, 400)
            response = upload(b'%PDF-1.4\nfixture\n%%EOF')
            self.assertEqual(response.status_code, 200, response.json)
            self.assertTrue(response.json['urls'][0].endswith('.pdf'))
            self.assertEqual(len(list(Path(directory).glob('*.pdf'))), 1)
        self.assertEqual(self.balances(), before)

    def test_partial_presets_disabled_customers_and_repeat_migrations(self):
        response = self.call('orders/templates', 'POST', {'name': 'Draft customer', 'profile': {'userId': 1}})
        self.assertEqual(response.status_code, 200, response.json)
        item = response.json['template']
        with db.get_connection() as conn, conn.cursor() as cur:
            customer_templates.migrate(cur); customer_templates.migrate(cur)
        self.assertEqual(self.call(f"orders/templates/{item['id']}").json['template'], item)
        db._fetch_one("UPDATE store_users SET status='disabled' WHERE id=1 RETURNING id")
        self.assertFalse(self.call(f"orders/templates/{item['id']}").json['template']['customerActive'])
        self.assertEqual(self.call('orders/templates', 'POST', self.payload()).status_code, 400)
        self.assertEqual(self.call(f"orders/templates/{item['id']}", 'PUT', {**self.payload(), 'version': item['version']}).status_code, 400)


if __name__ == '__main__':
    unittest.main()
