"""Inventory registration history; guarded isolated database fixtures only."""
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

import test_workbench as fixtures
import workbench
db = fixtures.db


class InventoryOperationsTest(unittest.TestCase):
    setUp = fixtures.WorkbenchTest.setUp
    call = fixtures.WorkbenchTest.call
    detail = fixtures.WorkbenchTest.detail

    def history(self, product_id=1, query='', role='admin'):
        return self.call(f'inventory/{product_id}/operations{query}', role=role)

    def save(self, role='admin', **changes):
        return self.call('inventory/1', 'PUT', {'version': self.detail()['version'], 'sizeStocks': {}, **changes}, role=role)

    def test_one_save_records_all_sizes_fields_and_server_actor(self):
        response = self.save(role='warehouse', sizeStocks={'M': -5}, pendingInspectionBySize={'M': 8},
                             temporaryInboundBySize={'M': 8, 'L': 3}, actor={'id': 999, 'name': 'Forged'})
        self.assertEqual(response.status_code, 200, response.json)
        result = self.history().json
        self.assertEqual((result['total'], result['pageSize']), (1, 10))
        row = result['items'][0]
        self.assertEqual(row['actor'], {'id': 3, 'name': '王仓管', 'role': 'warehouse'})
        self.assertEqual(row['sku'], 'GT-2026-1')
        self.assertTrue(row['occurredAt'])
        sizes = {s['sizeCode']: {f['field']: f for f in s['fields']} for s in row['changes']}
        self.assertEqual(set(sizes), {'M', 'L'})
        self.assertEqual(sizes['M']['stock'], {'field': 'stock', 'before': 10, 'after': -5, 'delta': -15})
        self.assertEqual(sizes['M']['contractPending']['delta'], -2)
        self.assertEqual(sizes['M']['pendingInspection']['delta'], 2)
        self.assertEqual(sizes['M']['temporaryInbound']['delta'], 8)
        self.assertEqual(sizes['L']['temporaryInbound']['delta'], 3)
        self.assertNotIn('password', repr(row))

    def test_default_ten_rows_pagination_stable_order_and_product_isolation(self):
        ids = []
        for value in range(1, 13):
            self.assertEqual(self.save(temporaryInboundBySize={'M': value}).status_code, 200)
            ids.append(self.history().json['items'][0]['id'])
        other = self.call('inventory/2', 'GET').json['product']
        self.assertEqual(self.call('inventory/2', 'PUT', {'version': other['version'], 'sizeStocks': {'M': 15}}).status_code, 200)
        # Identical timestamps still have deterministic ID ordering.
        db._fetch_one("UPDATE inventory_registration_logs SET occurred_at='2026-10-07 08:00:00+00' RETURNING id")
        first, second = self.history().json, self.history(query='?page=2').json
        self.assertEqual((first['total'], len(first['items']), len(second['items'])), (12, 10, 2))
        self.assertEqual([r['id'] for r in first['items']+second['items']], ids[::-1])
        self.assertEqual(self.history(2).json['total'], 1)
        self.assertEqual(self.history(query='?page=3').json['items'], [])

    def test_failed_and_stale_saves_create_no_extra_record(self):
        self.assertEqual(self.history().json['total'], 0)
        version = self.detail()['version']
        for changes in [{'temporaryInboundBySize': {'M': -1}}, {'temporaryInboundBySize': {'UNKNOWN': 5}}]:
            self.assertEqual(self.save(**changes).status_code, 400)
        self.assertEqual(self.history().json['total'], 0)
        body = {'version': version, 'sizeStocks': {}, 'temporaryInboundBySize': {'M': 8}}
        self.assertEqual(self.call('inventory/1', 'PUT', body).status_code, 200)
        self.assertEqual(self.call('inventory/1', 'PUT', body).status_code, 409)
        self.assertEqual(self.history().json['total'], 1)
        self.assertEqual(self.call('inventory/999', 'PUT', {'sizeStocks': {'M': 1}}).status_code, 404)
        self.assertEqual(self.history().json['total'], 1)

    def test_history_failure_rolls_back_inventory_audit_and_operation(self):
        before = self.detail()
        record = workbench.record_inventory_registration
        def fail(*args):
            record(*args)
            raise RuntimeError('Injected history persistence failure')
        with patch.object(workbench, 'record_inventory_registration', side_effect=fail):
            with self.assertRaisesRegex(RuntimeError, 'history persistence'):
                self.save(sizeStocks={'M': -5}, temporaryInboundBySize={'M': 8})
        self.assertEqual(self.detail(), before)
        self.assertEqual(self.history().json['total'], 0)
        self.assertEqual(self.call('audit-logs?page=1').json['total'], 0)

    def test_same_version_concurrent_saves_record_once(self):
        version = self.detail()['version']
        def save(value):
            return self.call('inventory/1', 'PUT', {'version': version, 'sizeStocks': {}, 'temporaryInboundBySize': {'M': value}})
        with ThreadPoolExecutor(max_workers=2) as pool:
            responses = list(pool.map(save, [5, 8]))
        self.assertEqual(sorted(r.status_code for r in responses), [200, 409])
        self.assertEqual(self.history().json['total'], 1)

    def test_permissions_input_validation_and_inactive_product_history(self):
        self.save(temporaryInboundBySize={'M': 3})
        for role in ['admin', 'sales', 'warehouse']:
            self.assertEqual(self.history(role=role).status_code, 200)
        self.assertEqual(self.history(role='customer').status_code, 403)
        with self.app.test_client() as client:
            self.assertEqual(client.get('/api/admin/inventory/1/operations').status_code, 401)
        db._fetch_one("UPDATE admin_users SET permissions='[]' WHERE role='warehouse' RETURNING id")
        self.assertEqual(self.history(role='warehouse').status_code, 403)
        self.assertEqual(self.history(999).status_code, 404)
        for query in ['?page=0', '?page=-1', '?page=abc', '?page=2147483648', '?pageSize=0', '?pageSize=1000']:
            self.assertEqual(self.history(query=query).status_code, 400)
        db._fetch_one('UPDATE products SET is_active=FALSE WHERE id=1 RETURNING id')
        self.assertEqual(self.history().json['total'], 1)

    def test_receipt_is_separate_and_snapshots_survive_actor_rename_and_migration(self):
        self.save(temporaryInboundBySize={'M': 3})
        history = self.history().json
        receipt = self.call('inventory/1/temporary/receive', 'POST', {'version': self.detail()['version'], 'requestId': str(uuid.uuid4())})
        self.assertEqual(receipt.status_code, 200)
        db._fetch_one("UPDATE admin_users SET name='新名字' WHERE id=1 RETURNING id")
        with db._connect() as conn:
            for _ in range(2): db._apply_schema_migrations(conn.cursor())
        self.assertEqual(self.history().json, history)


if __name__ == '__main__': unittest.main()
