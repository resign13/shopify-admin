"""Completed results reuse a private file and recheck live access on every GET."""
from io import BytesIO
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import threading
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch
from test_workbench import application, db, seed
import order_export_process
import order_export_results


class ExportResultsTest(unittest.TestCase):
    def setUp(self):
        self.tokens, _ = seed()
        self.directory = TemporaryDirectory(prefix='order-results-test-')
        self.addCleanup(self.directory.cleanup)
        self.settings = patch.dict(os.environ, {'ORDER_EXPORT_RESULT_DIR': self.directory.name,
            'SECURITY_EXPORT_GLOBAL_CONCURRENT': '2', 'SECURITY_LIMIT_EXPORT': '100', 'SECURITY_LIMIT_READ': '1000'})
        self.settings.start()
        self.addCleanup(self.settings.stop)
        self.builder = patch.object(application.order_export_process, 'build', side_effect=lambda *a, **k: BytesIO(b'complete-xlsx-fixture'))
        self.build = self.builder.start()
        self.addCleanup(self.builder.stop)
        db._fetch_one('UPDATE orders SET owner_admin_id=2 WHERE id=1 RETURNING id')

    def call(self, path, role='admin', method='GET', ticket=None):
        headers = {'Authorization': 'Bearer ' + self.tokens[role]}
        if ticket:
            headers['X-Export-Ticket'] = ticket
        with application.app.test_client() as client:
            return client.open(path, method=method, headers=headers)

    def generate(self, role='admin', kind='export'):
        ticket = str(uuid.uuid4())
        response = self.call('/api/admin/orders/' + kind + '?orderIds=1&includeImages=0', role, 'POST', ticket)
        self.assertEqual(response.status_code, 200, response.json)
        self.assertEqual(response.json['status'], 'ready')
        self.assertEqual(response.json['ticketId'], ticket)
        self.assertNotIn(self.directory.name, str(response.json))
        return response.json

    def test_ready_repeated_download_and_replay_never_regenerate_or_remark(self):
        result = self.generate('warehouse')
        before = db._fetch_all('SELECT * FROM order_warehouse_prints ORDER BY order_id')
        self.assertEqual(len(before), 1)
        for _ in range(2):
            response = self.call(result['downloadUrl'], 'warehouse')
            self.assertEqual((response.status_code, response.data), (200, b'complete-xlsx-fixture'))
            response.close()
        self.assertEqual(self.call(result['statusUrl'], 'warehouse').json['status'], 'ready')
        duplicate = self.call('/api/admin/orders/export?orderIds=1&includeImages=0', 'warehouse', 'POST', result['ticketId'])
        self.assertEqual((duplicate.status_code, duplicate.json['code']), (409, 'export_ticket_finished'))
        self.assertEqual(self.build.call_count, 1)
        self.assertEqual(db._fetch_all('SELECT * FROM order_warehouse_prints ORDER BY order_id'), before)
        # Generation coordination locks are already free while the result remains reusable.
        with db._connect(autocommit=True, coordination=True) as conn:
            for key in ('export:admin:3', 'export:global:0', 'export:global:1'):
                self.assertTrue(conn.execute('SELECT pg_try_advisory_lock(hashtextextended(%s,0)) AS locked', (key,)).fetchone()['locked'])
                conn.execute('SELECT pg_advisory_unlock(hashtextextended(%s,0))', (key,))

    def test_download_does_not_hold_snapshot_or_acquire_generation_slots(self):
        result = self.generate()
        original = order_export_results.send_file
        def check(*args, **kwargs):
            self.assertIsNone(db.REQUEST_CONNECTION.get())
            return original(*args, **kwargs)
        with db._connect(autocommit=True, coordination=True) as locks:
            for slot in (0, 1):
                locks.execute('SELECT pg_advisory_lock(hashtextextended(%s,0))', (f'export:global:{slot}',))
            try:
                with patch.object(order_export_results, 'send_file', side_effect=check):
                    response = self.call(result['downloadUrl'])
                self.assertEqual(response.status_code, 200)
                response.close()
            finally:
                for slot in (0, 1):
                    locks.execute('SELECT pg_advisory_unlock(hashtextextended(%s,0))', (f'export:global:{slot}',))

    def test_account_session_role_permissions_and_ownership_rechecked(self):
        result = self.generate('sales')
        for key in ('statusUrl', 'downloadUrl'):
            self.assertEqual(self.call(result[key], 'admin').status_code, 404)
        db._fetch_one('UPDATE orders SET owner_admin_id=NULL WHERE id=1 RETURNING id')
        self.assertEqual(self.call(result['downloadUrl'], 'sales').status_code, 404)
        db._fetch_one('UPDATE orders SET owner_admin_id=2 WHERE id=1 RETURNING id')
        db._fetch_one("UPDATE admin_users SET permissions='[]' WHERE id=2 RETURNING id")
        self.assertEqual(self.call(result['downloadUrl'], 'sales').status_code, 403)
        db._fetch_one("UPDATE admin_users SET permissions=NULL,role='warehouse' WHERE id=2 RETURNING id")
        self.assertEqual(self.call(result['downloadUrl'], 'sales').status_code, 403)
        db._fetch_one("UPDATE admin_users SET role='sales' WHERE id=2 RETURNING id")
        old = self.tokens['sales']
        self.tokens['sales'] = db.create_admin_session(2)
        self.assertEqual(self.call(result['downloadUrl'], 'sales').status_code, 404)
        self.tokens['sales'] = old
        self.assertEqual(self.call(result['downloadUrl'], 'sales').status_code, 401)

    def test_expiry_removes_file_and_status_never_rebuilds(self):
        result = self.generate()
        path = order_export_results.file_path(result['ticketId'])
        os.utime(path, (1, 1))
        response = self.call(result['downloadUrl'])
        self.assertEqual((response.status_code, response.json['code']), (410, 'export_result_expired'))
        self.assertFalse(path.exists())
        self.assertEqual(self.call(result['statusUrl']).json['status'], 'expired')
        self.assertEqual(self.build.call_count, 1)

    def test_failed_timeout_and_image_failure_are_recoverable_status_not_generation(self):
        for error, code, status in [(order_export_process.ExportTimeout(), 'export_timeout', 504),
                (order_export_process.ImageUnavailable(), 'export_image_unavailable', 502)]:
            with self.subTest(code=code):
                self.build.side_effect = error
                ticket = str(uuid.uuid4())
                response = self.call('/api/admin/orders/export?orderIds=1&includeImages=0', method='POST', ticket=ticket)
                self.assertEqual((response.status_code, response.json['code']), (status, code))
                result = self.call('/api/admin/orders/export-results/' + ticket)
                self.assertEqual((result.status_code, result.json['status'], result.json['code']), (200, 'failed', code))
                self.assertEqual(list(order_export_results.folder().glob('*.xlsx')), [])

    def test_finalize_conflict_never_publishes_file_or_prints(self):
        def change(*args, **kwargs):
            db._fetch_one("UPDATE orders SET updated_at=clock_timestamp() WHERE id=1 RETURNING id")
            return BytesIO(b'complete-xlsx-fixture')
        self.build.side_effect = change
        ticket = str(uuid.uuid4())
        response = self.call('/api/admin/orders/export?orderIds=1&includeImages=0', 'warehouse', 'POST', ticket)
        self.assertEqual(response.status_code, 409)
        result = self.call('/api/admin/orders/export-results/' + ticket, 'warehouse')
        self.assertEqual(result.json['status'], 'failed')
        self.assertEqual(list(order_export_results.folder().glob('*.xlsx')), [])
        self.assertEqual(db._fetch_all('SELECT * FROM order_warehouse_prints'), [])

    def test_inflight_status_then_ready_without_replaying_generation(self):
        entered, release = threading.Event(), threading.Event()
        def wait(*args, **kwargs):
            entered.set()
            if not release.wait(10):
                raise RuntimeError('test generator wait expired')
            return BytesIO(b'complete-xlsx-fixture')
        self.build.side_effect = wait
        ticket = str(uuid.uuid4())
        base = '/api/admin/orders/export-results/' + ticket
        with ThreadPoolExecutor(max_workers=1) as executor:
            pending = executor.submit(self.call, '/api/admin/orders/export?orderIds=1&includeImages=0', 'admin', 'POST', ticket)
            try:
                self.assertTrue(entered.wait(5))
                self.assertEqual(self.call(base).json['status'], 'started')
                self.assertEqual(self.call(base + '/download').status_code, 409)
            finally:
                release.set()
            response = pending.result(timeout=10)
        self.assertEqual(response.json['status'], 'ready')
        self.assertEqual(self.call(base).json['status'], 'ready')
        self.assertEqual(self.build.call_count, 1)

    def test_waiting_expiry_orphaned_started_and_unknown_tickets(self):
        ticket = str(uuid.uuid4())
        base = '/api/admin/orders/export-results/' + ticket
        self.assertEqual(self.call(base).status_code, 404)
        with db._connect(autocommit=True, coordination=True) as locks:
            for slot in (0, 1):
                locks.execute('SELECT pg_advisory_lock(hashtextextended(%s,0))', (f'export:global:{slot}',))
            try:
                response = self.call('/api/admin/orders/export?orderIds=1&includeImages=0', method='POST', ticket=ticket)
                self.assertEqual(response.json['code'], 'export_queued')
                self.assertEqual(self.call(base).json['status'], 'waiting')
                db._fetch_one("UPDATE security_export_queue SET created_at=clock_timestamp()-interval '121 seconds' WHERE ticket=%s RETURNING seq", (ticket,))
                self.assertEqual(self.call(base).json['status'], 'expired')
            finally:
                for slot in (0, 1):
                    locks.execute('SELECT pg_advisory_unlock(hashtextextended(%s,0))', (f'export:global:{slot}',))
        db._fetch_one("UPDATE security_export_queue SET state='started' WHERE ticket=%s RETURNING seq", (ticket,))
        self.assertEqual(self.call(base).json['status'], 'failed')
        self.assertEqual(self.build.call_count, 0)

    def test_parent_image_precheck_uses_safe_502_and_terminal_status(self):
        from export_image_cache import ExportImageError
        ticket = str(uuid.uuid4())
        with patch.object(application, 'prepare_export_images', side_effect=ExportImageError()):
            response = self.call('/api/admin/orders/export?orderIds=1&includeImages=1', method='POST', ticket=ticket)
        self.assertEqual((response.status_code, response.json['code']), (502, 'export_image_unavailable'))
        status = self.call('/api/admin/orders/export-results/' + ticket)
        self.assertEqual((status.json['status'], status.json['code']), ('failed', 'export_image_unavailable'))
        self.assertEqual(self.build.call_count, 0)

    def test_test_database_result_namespace_is_separate_and_required(self):
        folder = order_export_results.folder()
        self.assertEqual(folder.parent, Path(self.directory.name).resolve())
        self.assertTrue(folder.name.endswith('_test'))
        with patch.dict(os.environ, {'PGDATABASE': 'lumiere_admin'}):
            with self.assertRaises(ValueError):
                order_export_results.folder()
        with patch.dict(os.environ, {'APP_ENV': 'development'}):
            self.assertEqual(order_export_results.folder(), Path(self.directory.name).resolve())

    def test_legacy_no_ticket_still_returns_a_file(self):
        response = self.call('/api/admin/orders/export?orderIds=1&includeImages=0', method='POST')
        self.assertEqual((response.status_code, response.data), (200, b'complete-xlsx-fixture'))
        response.close()
        self.assertEqual(list(order_export_results.folder().glob('*.xlsx')), [])


if __name__ == '__main__':
    unittest.main()
