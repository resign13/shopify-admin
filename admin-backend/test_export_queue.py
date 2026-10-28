"""FIFO export admission integration tests; test_workbench enforces local *_test."""
import os
import threading
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch
from flask import Flask, g
from flask.testing import FlaskClient
from test_workbench import application, db, seed
from security_core import Security


class ExportQueueTest(unittest.TestCase):
    def setUp(self):
        self.tokens, _ = seed()
        db._fetch_one('DELETE FROM security_export_queue RETURNING seq')
        self.probe = Flask('fifo-export-test')
        self.security = Security(self.probe, db, 'admin')
        self.calls = []
        def export():
            self.calls.append('built')
            return {'ok': True}
        self.probe.add_url_rule('/api/admin/orders/export', 'export', export, methods=['GET', 'POST'])
        self.probe.add_url_rule('/api/admin/report', 'report', lambda: {'ok': True})
        self.probe.add_url_rule('/api/admin/orders/<int:order_id>/invoice', 'invoice', lambda order_id: {'id': order_id})
        self.admin = FlaskClient(self.probe, self.probe.response_class)
        self.sales = FlaskClient(self.probe, self.probe.response_class)
        self.admin.set_cookie(application.security.cookie, self.tokens['admin'])
        self.sales.set_cookie(application.security.cookie, self.tokens['sales'])
        self.settings = patch.dict(os.environ, {'SECURITY_EXPORT_GLOBAL_CONCURRENT': '2', 'DB_COORDINATION_POOL_MAX': '3', 'SECURITY_LIMIT_EXPORT': '5',
                                                 'SECURITY_LIMIT_EXPORT_POLL': '30'})
        self.settings.start()
        self.addCleanup(self.settings.stop)

    def call(self, client, ticket=None, query=''):
        headers = {'X-Export-Ticket': ticket} if ticket else {}
        return client.get('/api/admin/orders/export' + query, headers=headers)

    def test_fifo_cross_account_and_replay(self):
        first, second = str(uuid.uuid4()), str(uuid.uuid4())
        with db._connect(autocommit=True, coordination=True) as locks:
            for slot in (0, 1):
                locks.execute('SELECT pg_advisory_lock(hashtextextended(%s,0))', (f'export:global:{slot}',))
            a, b = self.call(self.admin, first), self.call(self.sales, second)
            self.assertEqual((a.status_code, a.json['code'], a.json['ticketId'], a.json['position'], a.headers['Retry-After']), (429, 'export_queued', first, 1, '5'))
            self.assertEqual((b.json['code'], b.json['position']), ('export_queued', 2))
            self.assertEqual(self.call(self.sales, first).json['code'], 'export_ticket_mismatch')
            self.assertEqual(self.call(self.admin, first, '?includeImages=0').json['code'], 'export_ticket_mismatch')
            self.assertEqual(self.call(self.admin).json['code'], 'export_capacity')
            locks.execute("SELECT pg_advisory_unlock(hashtextextended('export:global:0',0))")
            self.assertEqual(self.call(self.sales, second).json['position'], 2)
            self.assertEqual(self.call(self.admin, first).status_code, 200)
            self.assertEqual(self.call(self.sales, second).status_code, 200)
            self.assertEqual(self.call(self.admin, first).json['code'], 'export_ticket_finished')
            locks.execute("SELECT pg_advisory_unlock(hashtextextended('export:global:1',0))")
        self.assertEqual(len(self.calls), 2)

    def test_queue_limit_expiry_and_reentry(self):
        tickets = [str(uuid.uuid4()) for _ in range(11)]
        with db._connect(autocommit=True, coordination=True) as locks:
            for slot in (0, 1):
                locks.execute('SELECT pg_advisory_lock(hashtextextended(%s,0))', (f'export:global:{slot}',))
            for index, ticket in enumerate(tickets[:10], 1):
                response = self.call(self.admin, ticket)
                self.assertEqual((response.json['code'], response.json['position']), ('export_queued', index))
            full = self.call(self.admin, tickets[10])
            self.assertEqual((full.json['code'], full.json['message']), ('export_queue_full', '导出排队已满，请稍后重新发起。'))
            self.assertEqual(db._fetch_one('SELECT * FROM security_export_waiting'), {'has_waiting': True})
            db._fetch_one("UPDATE security_export_queue SET last_seen=clock_timestamp()-interval '21 seconds' WHERE ticket=%s RETURNING seq", (tickets[0],))
            expired = self.call(self.admin, tickets[0])
            self.assertEqual((expired.json['code'], expired.json['message']), ('export_ticket_expired', '排队已过期，请重新发起导出。'))
            self.assertEqual(self.call(self.admin, tickets[10]).json['position'], 10)
            for slot in (0, 1):
                locks.execute('SELECT pg_advisory_unlock(hashtextextended(%s,0))', (f'export:global:{slot}',))

    def test_poll_quota_limits_before_coordination_without_consuming_export_quota(self):
        ticket = str(uuid.uuid4())
        with db._connect(autocommit=True, coordination=True) as locks:
            for slot in (0, 1):
                locks.execute('SELECT pg_advisory_lock(hashtextextended(%s,0))', (f'export:global:{slot}',))
            for _ in range(30):
                response = self.call(self.admin, ticket)
                self.assertEqual((response.status_code, response.json['code']), (429, 'export_queued'))
            original_connect = db._connect
            coordination_calls = []
            def connect(*args, **kwargs):
                if kwargs.get('coordination'):
                    coordination_calls.append(True)
                return original_connect(*args, **kwargs)
            with patch.object(db, '_connect', side_effect=connect):
                response = self.call(self.admin, ticket)
            self.assertEqual((response.status_code, response.json['code'], response.json['message']),
                (429, 'export_poll_limited', '导出请求过于频繁，请稍后重试。'))
            self.assertGreater(int(response.headers['Retry-After']), 0)
            self.assertEqual(coordination_calls, [])
            self.assertEqual(self.calls, [])
            self.assertEqual(self.admin.get('/api/admin/report').status_code, 200)
            self.assertEqual(self.call(self.sales, str(uuid.uuid4())).json['code'], 'export_queued')
            export_key = self.security.digest('quota:admin:export:1')
            self.assertIsNone(db._fetch_one('SELECT ticks FROM security_rate_buckets WHERE bucket_key=%s', (export_key,)))
            # Advance only this account's polling window; actual export quota remains untouched.
            poll_key = self.security.digest('quota:admin:export-poll:1')
            db._fetch_one("UPDATE security_rate_buckets SET ticks=ARRAY(SELECT tick-interval '61 seconds' FROM unnest(ticks) AS tick) WHERE bucket_key=%s RETURNING bucket_key", (poll_key,))
            for slot in (0, 1):
                locks.execute('SELECT pg_advisory_unlock(hashtextextended(%s,0))', (f'export:global:{slot}',))
        self.assertEqual(self.call(self.admin, ticket).status_code, 200)
        # Remove the other account's waiting ticket so it does not block the remaining exports.
        db._fetch_one("UPDATE security_export_queue SET state='expired' WHERE state='waiting' RETURNING seq")
        for _ in range(4):
            self.assertEqual(self.call(self.admin, str(uuid.uuid4())).status_code, 200)
        limited = self.call(self.admin, str(uuid.uuid4()))
        self.assertEqual((limited.status_code, limited.json['code']), (429, 'rate_limited'))
        self.assertEqual(len(self.calls), 5)

    def test_poll_limit_configuration_and_bounds(self):
        with patch.dict(os.environ, {'SECURITY_LIMIT_EXPORT_POLL': '1'}):
            self.assertEqual(self.call(self.admin, str(uuid.uuid4())).status_code, 200)
            self.assertEqual(self.call(self.admin, str(uuid.uuid4())).json['code'], 'export_poll_limited')
        with patch.dict(os.environ, {'SECURITY_LIMIT_EXPORT_POLL': '0'}):
            self.assertEqual(self.call(self.admin, str(uuid.uuid4())).status_code, 500)
        with patch.dict(os.environ, {'SECURITY_LIMIT_EXPORT_POLL': '10001'}):
            self.assertEqual(self.call(self.admin, str(uuid.uuid4())).status_code, 500)

    def test_started_ticket_and_account_lock(self):
        ticket = str(uuid.uuid4())
        db._fetch_one('''INSERT INTO security_export_queue(ticket,channel,account_id,session_id,method,path,query,state)
            SELECT %s,'admin',u.id,s.public_id,'GET','/api/admin/orders/export','[]','started'
            FROM admin_users u JOIN admin_sessions s ON s.admin_user_id=u.id WHERE u.id=1 RETURNING seq''', (ticket,))
        started = self.call(self.admin, ticket)
        self.assertEqual((started.json['code'], started.json['message']), ('export_ticket_started', '该导出已开始，请等待结果，勿重复提交。'))
        with db._connect(autocommit=True, coordination=True) as lock:
            lock.execute("SELECT pg_advisory_lock(hashtextextended('export:admin:1',0))")
            other = str(uuid.uuid4())
            self.assertEqual(self.call(self.admin, other).json['code'], 'export_queued')
            lock.execute("SELECT pg_advisory_unlock(hashtextextended('export:admin:1',0))")
        self.assertEqual(self.call(self.admin, other).status_code, 200)

    def test_builder_failure_marks_ticket_finished(self):
        ticket = str(uuid.uuid4())
        self.probe.view_functions['export'] = MockFailure()
        self.assertEqual(self.call(self.admin, ticket).status_code, 500)
        self.assertEqual(self.call(self.admin, ticket).json['code'], 'export_ticket_finished')
        self.probe.view_functions['export'] = lambda: {'ok': True}
        self.assertEqual(self.call(self.admin, str(uuid.uuid4())).status_code, 200)

    def test_two_accounts_run_together_third_waits(self):
        entered = threading.Event()
        release = threading.Event()
        mutex = threading.Lock()
        count = 0
        def build():
            nonlocal count
            with mutex:
                count += 1
                if count == 2:
                    entered.set()
            if not release.wait(10):
                raise RuntimeError('test timed out')
            return {'ok': True}
        self.probe.view_functions['export'] = build
        with ThreadPoolExecutor(max_workers=2) as executor:
            first = executor.submit(self.call, self.admin, str(uuid.uuid4()))
            second = executor.submit(self.call, self.sales, str(uuid.uuid4()))
            try:
                self.assertTrue(entered.wait(8), 'two accounts did not enter the builder together')
                third = FlaskClient(self.probe, self.probe.response_class)
                third.set_cookie(application.security.cookie, self.tokens['admin'])
                ticket = str(uuid.uuid4())
                self.assertEqual(self.call(third, ticket).json['code'], 'export_queued')
            finally:
                release.set()
            self.assertEqual(first.result(timeout=10).status_code, 200)
            self.assertEqual(second.result(timeout=10).status_code, 200)
        self.assertEqual(self.call(third, ticket).status_code, 200)

    def test_waiting_active_account_does_not_block_next_runnable_account(self):
        first, second = str(uuid.uuid4()), str(uuid.uuid4())
        with db._connect(autocommit=True, coordination=True) as lock:
            lock.execute("SELECT pg_advisory_lock(hashtextextended('export:admin:1',0))")
            lock.execute("SELECT pg_advisory_lock(hashtextextended('export:global:0',0))")
            self.assertEqual(self.call(self.admin, first).json['position'], 1)
            self.assertEqual(self.call(self.sales, second).status_code, 200)
            self.assertEqual(self.call(self.admin, first).json['code'], 'export_queued')
            lock.execute("SELECT pg_advisory_unlock(hashtextextended('export:admin:1',0))")
            lock.execute("SELECT pg_advisory_unlock(hashtextextended('export:global:0',0))")
        self.assertEqual(self.call(self.admin, first).status_code, 200)

    def test_invoice_uses_ticket_queue_and_binds_order_id(self):
        ticket = str(uuid.uuid4())
        headers = {'X-Export-Ticket': ticket}
        with db._connect(autocommit=True, coordination=True) as lock:
            for slot in (0, 1):
                lock.execute('SELECT pg_advisory_lock(hashtextextended(%s,0))', (f'export:global:{slot}',))
            response = self.admin.get('/api/admin/orders/1/invoice', headers=headers)
            self.assertEqual(response.json['code'], 'export_queued')
            self.assertEqual(self.admin.get('/api/admin/orders/2/invoice', headers=headers).json['code'], 'export_ticket_mismatch')
            for slot in (0, 1):
                lock.execute('SELECT pg_advisory_unlock(hashtextextended(%s,0))', (f'export:global:{slot}',))
        self.assertEqual(self.admin.get('/api/admin/orders/1/invoice', headers=headers).status_code, 200)
        self.assertEqual(self.admin.get('/api/admin/orders/1/invoice', headers=headers).json['code'], 'export_ticket_finished')

    def test_marked_timeout_is_visible_and_ticket_finished(self):
        def timeout():
            g.security_export_timeout = True
            return {'code': 'export_timeout', 'message': '导出超时，请重试'}, 504
        self.probe.view_functions['export'] = timeout
        ticket = str(uuid.uuid4())
        response = self.call(self.admin, ticket)
        self.assertEqual((response.status_code, response.json['code'], response.json['message']), (504, 'export_timeout', '导出超时，请重试'))
        self.assertEqual(self.call(self.admin, ticket).json['code'], 'export_ticket_finished')
        self.probe.view_functions['export'] = lambda: ({'code': 'secret', 'message': 'sensitive'}, 504)
        self.assertEqual(self.call(self.admin, str(uuid.uuid4())).json['code'], 'service_error')


class MockFailure:
    def __call__(self):
        raise RuntimeError('fixture builder failure')


if __name__ == '__main__':
    unittest.main()
