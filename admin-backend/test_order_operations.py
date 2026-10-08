"""Order history regression uses only the guarded *_test fixture database."""
import copy
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor

import test_workbench as fixtures
import order_operations

db = fixtures.db


class OrderOperationsTest(unittest.TestCase):
    setUp = fixtures.WorkbenchTest.setUp
    call = fixtures.WorkbenchTest.call

    def create(self, role='admin', **extra):
        body = {'requestId': str(uuid.uuid4()), 'userId': 1, 'contactName': 'Fixture Buyer',
                'phone': '123456', 'country': 'Germany', 'address': 'Fixture address',
                'shippingFee': 12.5, 'items': [
                    {'productId': 1, 'sizeCode': 'M', 'quantity': 2, 'unitPrice': 20},
                    {'productId': 1, 'sizeCode': 'L', 'quantity': 3, 'unitPrice': 25}], **extra}
        response = self.call('orders', 'POST', body, role=role)
        self.assertEqual(response.status_code, 200, response.json)
        return self.detail(response.json['order']['id']), body

    def detail(self, order_id):
        return self.call(f'orders/{order_id}').json['order']

    def history(self, order_id, query='', role='admin'):
        return self.call(f'orders/{order_id}/operations{query}', role=role)

    def update(self, order_id, **fields):
        body = self.detail(order_id)
        response = self.call(f'orders/{order_id}', 'PUT', {
            'version': body['version'], 'status': body['status'], 'shippingFee': body['shippingFee'],
            'trackingNo': body['trackingNo'], 'paymentLink': body['paymentLink'], **fields})
        self.assertEqual(response.status_code, 200, response.json)

    def test_creation_and_replay_are_excluded_without_removing_system_audit(self):
        order, body = self.create(actor={'id': 999, 'name': 'Forged'})
        result = self.history(order['id']).json
        self.assertEqual((result['total'], result['pageSize'], result['items']), (0, 10, []))
        rows = db._fetch_all('SELECT action,batch_id FROM admin_audit_logs '
                             "WHERE entity_table='orders' AND object_id=%s ORDER BY id", (str(order['id']),))
        self.assertTrue(any(row['action'] == 'INSERT' for row in rows))
        self.assertTrue(any(row['action'] == 'UPDATE' for row in rows))
        self.assertEqual(len({row['batch_id'] for row in rows}), 1)
        self.assertEqual(self.call('orders', 'POST', body).status_code, 200)
        self.assertEqual(self.history(order['id']).json, result)
        self.update(order['id'], trackingNo='First edit')
        result = self.history(order['id']).json
        self.assertEqual(result['total'], 1)
        row = result['items'][0]
        self.assertEqual(row['actor'], {'id': 1, 'name': '陈管理员', 'role': 'admin'})
        self.assertEqual(row['action'], 'update')
        self.assertEqual(row['changes'], [{'field': 'trackingNo', 'before': None, 'after': 'First edit'}])
        self.assertNotIn('123456', str(result))
        self.assertNotIn('Fixture address', str(result))
        self.assertNotIn('batchId', row)
        self.assertFalse(any(c['before'] in (None, '') and c['after'] in (None, '') for c in row['changes']))

    def test_one_edit_aggregates_real_differences_without_false_item_replacements(self):
        order, _ = self.create()
        body = copy.deepcopy(order)
        body['items'][0]['quantity'] = 4
        body['items'][0]['unitPrice'] = 22
        body['contactName'] = 'Updated Buyer'
        body['note'] = 'Packing note\nSecond line'
        body['labelImageUrls'] = ['/uploads/fixture-photo.jpg']
        body['status'] = 'allocated'
        response = self.call(f"orders/{order['id']}/details", 'PUT', body)
        self.assertEqual(response.status_code, 200, response.json)
        result = self.history(order['id']).json
        self.assertEqual(result['total'], 1)
        row = result['items'][0]
        self.assertEqual(row['action'], 'status')
        changes = {(c['field'], c.get('sizeCode')): c for c in row['changes']}
        self.assertEqual(changes['quantity', 'M']['delta'], 2)
        self.assertEqual((changes['unitPrice', 'M']['before'], changes['unitPrice', 'M']['after']), (20, 22))
        self.assertNotIn(('quantity', 'L'), changes)
        self.assertNotIn(('unitPrice', 'L'), changes)
        self.assertEqual(changes['contactName', None]['before'], 'Fixture Buyer')
        self.assertEqual(changes['attachments', None]['after'], 1)
        self.assertEqual(changes['note', None]['after'], body['note'])
        self.assertNotIn('/uploads/', str(row))
        self.assertNotIn('updated_at', str(row))

    def test_pagination_ties_and_other_orders_do_not_mix(self):
        order, _ = self.create()
        for index in range(12):
            self.update(order['id'], trackingNo=f'Fixture-{index}')
        other, _ = self.create()
        db._fetch_one("UPDATE admin_audit_logs SET occurred_at='2026-10-08 00:00:00+00' RETURNING id")
        first = self.history(order['id']).json
        second = self.history(order['id'], '?page=2').json
        self.assertEqual((first['total'], len(first['items']), len(second['items'])), (12, 10, 2))
        ids = [row['id'] for row in first['items'] + second['items']]
        self.assertEqual(ids, sorted(ids, reverse=True))
        self.assertEqual(len(ids), len(set(ids)))
        self.assertTrue(all(row['action'] == 'update' for row in first['items'] + second['items']))
        self.assertEqual(self.history(other['id']).json['total'], 0)
        self.assertEqual(self.history(order['id'], '?page=3').json['items'], [])

    def test_cancel_restore_status_and_read_only_history(self):
        order, _ = self.create()
        self.update(order['id'], status='cancelled')
        self.assertEqual(self.history(order['id']).json['items'][0]['action'], 'cancel')
        self.update(order['id'], status='paid')
        result = self.history(order['id']).json
        self.assertEqual(result['items'][0]['action'], 'restore')
        before = db._fetch_all('SELECT id,stock,temporary_inbound FROM product_size_prices ORDER BY id')
        count = db._fetch_one('SELECT COUNT(*) AS n FROM admin_audit_logs')['n']
        self.assertEqual(self.history(order['id']).json, result)
        self.assertEqual(db._fetch_all('SELECT id,stock,temporary_inbound FROM product_size_prices ORDER BY id'), before)
        self.assertEqual(db._fetch_one('SELECT COUNT(*) AS n FROM admin_audit_logs')['n'], count)

    def test_warehouse_financial_redaction_and_order_scoped_permissions(self):
        own, _ = self.create(role='sales')
        other, _ = self.create()
        body = copy.deepcopy(own)
        body['items'][0]['quantity'] = 4
        self.assertEqual(self.call(f"orders/{own['id']}/details", 'PUT', body, role='sales').status_code, 200)
        self.update(own['id'], shippingFee=19, paymentLink='https://example.test/private-payment')
        for role in ['admin', 'sales', 'warehouse']:
            self.assertEqual(self.history(own['id'], role=role).status_code, 200)
        self.assertEqual(self.history(other['id'], role='sales').status_code, 404)
        self.assertEqual(self.history(own['id'], role='customer').status_code, 403)
        warehouse = self.history(own['id'], role='warehouse').json
        self.assertTrue(any(c['field'] == 'quantity' for r in warehouse['items'] for c in r['changes']))
        self.assertFalse(any(c['field'] in order_operations.FINANCIAL_FIELDS for r in warehouse['items'] for c in r['changes']))
        for secret in ['private-payment', 'paymentLink', 'shippingFee', 'totalAmount', 'unitPrice', 'total_price']:
            self.assertNotIn(secret, str(warehouse))
        self.assertEqual(self.call('audit-logs', role='warehouse').status_code, 403)
        db._fetch_one("UPDATE admin_users SET permissions='[]' WHERE role='warehouse' RETURNING id")
        self.assertEqual(self.history(own['id'], role='warehouse').status_code, 403)
        with self.app.test_client() as client:
            self.assertEqual(client.get(f"/api/admin/orders/{own['id']}/operations").status_code, 401)

    def test_failed_stale_and_concurrent_saves_record_only_success(self):
        order, _ = self.create()
        body = copy.deepcopy(order)
        body['items'][0]['quantity'] = -1
        self.assertEqual(self.call(f"orders/{order['id']}/details", 'PUT', body).status_code, 400)
        def update(value):
            return self.call(f"orders/{order['id']}", 'PUT', {'version': order['version'],
                             'status': 'paid', 'shippingFee': 12.5, 'trackingNo': value})
        with ThreadPoolExecutor(max_workers=2) as pool:
            result = list(pool.map(update, ['Tracking-A', 'Tracking-B']))
        self.assertEqual(sorted(r.status_code for r in result), [200, 409])
        self.assertEqual(self.history(order['id']).json['total'], 1)
        self.assertEqual(update('Stale').status_code, 409)
        self.assertEqual(self.history(order['id']).json['total'], 1)

    def test_existing_empty_missing_validation_and_actor_snapshots(self):
        self.assertEqual(self.history(1).json['total'], 0)
        self.assertEqual(self.history(99999).status_code, 404)
        for query in ['?page=0', '?page=-1', '?page=abc', '?page=2147483648', '?pageSize=0', '?pageSize=1000']:
            self.assertEqual(self.history(1, query).status_code, 400, query)
        own, _ = self.create()
        self.update(own['id'], trackingNo='Actor snapshot edit')
        before = self.history(own['id']).json
        self.assertEqual(before['total'], 1)
        db._fetch_one("UPDATE admin_users SET name='Renamed admin' WHERE id=1 RETURNING id")
        self.assertEqual(self.history(own['id']).json, before)

    def test_account_link_history_and_shared_batch_are_scoped_by_order(self):
        self.assertEqual(self.call('store-users/1', 'PUT', {'linkedAdminId': 2}).status_code, 200)
        for order_id in [1, 2, 3, 4]:
            result = self.history(order_id, role='sales').json
            self.assertEqual(result['total'], 1)
            self.assertEqual(result['items'][0]['changes'], [{'field': 'ownerAdminId', 'before': None, 'after': 2}])

    def test_creation_filter_does_not_hide_another_order_edit_in_same_batch(self):
        self.update(1, trackingNo='Existing order edit')
        created, _ = self.create()
        creation_batch = db._fetch_one("SELECT batch_id FROM admin_audit_logs WHERE entity_table='orders' "
                                     "AND action='INSERT' AND object_id=%s", (str(created['id']),))['batch_id']
        db._fetch_one("UPDATE admin_audit_logs SET batch_id=%s WHERE entity_table IN ('orders','order_items') "
                      "AND object_id='1' RETURNING id", (creation_batch,))
        result = self.history(1).json
        self.assertEqual(result['total'], 1)
        self.assertEqual(result['items'][0]['changes'], [{'field': 'trackingNo', 'before': None, 'after': 'Existing order edit'}])
        self.assertEqual(self.history(created['id']).json['total'], 0)


if __name__ == '__main__':
    unittest.main()
