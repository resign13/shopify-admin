"""Security resource/audit acceptance using guarded synthetic PostgreSQL data."""
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import MagicMock, Mock, patch
from flask import Flask
from flask.testing import FlaskClient
from test_workbench import application, db, seed
from security_core import Security


class SecurityOperationsTest(unittest.TestCase):
    def setUp(self):
        self.tokens, self.products = seed()
        db._fetch_one('DELETE FROM security_export_queue RETURNING seq')

    def get(self, path, role='admin'):
        with application.app.test_client() as client:
            return client.get(path, headers={'Authorization': 'Bearer ' + self.tokens[role]})

    def business(self):
        return db._fetch_one("SELECT (SELECT md5(string_agg(to_jsonb(t)::text,'|' ORDER BY id)) FROM orders t) AS orders,(SELECT md5(string_agg(to_jsonb(t)::text,'|' ORDER BY id)) FROM product_size_prices t) AS inventory")

    def test_security_audit_requires_account_management_not_just_finance(self):
        self.get('/api/admin/orders', role='customer')
        response = self.get('/api/admin/admin-users/security-audit')
        self.assertEqual(response.status_code, 200, response.json)
        self.assertGreater(response.json['total'], 0)
        for row in response.json['items']:
            self.assertNotIn('ip_digest', row)
            self.assertNotIn('request_body', row)
            self.assertNotIn('token', row)
        for role in ['sales', 'warehouse', 'customer']:
            self.assertEqual(self.get('/api/admin/admin-users/security-audit', role).status_code, 403)
        restricted = db.create_admin_user({'name': 'Restricted fixture', 'email': 'restricted@fixture.test', 'passwordHash': 'unused-fixture', 'role': 'admin', 'permissions': ['finance'], 'status': 'active'})
        self.tokens['restricted'] = db.create_admin_session(restricted['id'])
        self.assertEqual(self.get('/api/admin/admin-users/security-audit', 'restricted').status_code, 403)
        finance = db.create_admin_user({'name': 'Finance fixture', 'email': 'finance@fixture.test', 'passwordHash': 'unused-fixture', 'role': 'finance', 'permissions': ['finance'], 'status': 'active'})
        self.tokens['finance'] = db.create_admin_session(finance['id'])
        self.assertEqual(self.get('/api/admin/admin-users/security-audit', 'finance').status_code, 403)

    def test_retention_preserves_recent_records_and_all_business_balances(self):
        before = self.business()
        for age in ['91 days', '1 day']:
            db._fetch_one("INSERT INTO security_audit_events(created_at,channel,event_code,route,status,ip_digest) VALUES(clock_timestamp()-%s::interval,'admin','fixture_retention','/api/fixture',403,'fixture-digest') RETURNING id", (age,))
        for age in ['31 days', '1 day']:
            db._fetch_one("INSERT INTO security_request_metrics(hour,channel,route,status,calls,duration_ms) VALUES(date_trunc('hour',clock_timestamp()-%s::interval),'admin','/api/fixture',200,1,1) RETURNING hour", (age,))
        result = subprocess.run([sys.executable, str(Path(__file__).resolve().parents[1] / 'scripts/security-maintenance.py'), '--expected-db', db.DB_NAME], capture_output=True, text=True, env=os.environ.copy(), timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(db._fetch_one("SELECT COUNT(*) AS n FROM security_audit_events WHERE event_code='fixture_retention'")['n'], 1)
        self.assertEqual(db._fetch_one("SELECT COUNT(*) AS n FROM security_request_metrics WHERE route='/api/fixture'")['n'], 1)
        self.assertEqual(self.business(), before)

    def test_concurrent_export_rejected_before_builder_and_lock_released(self):
        before = self.business()
        with db._connect(autocommit=True) as conn:
            conn.execute("SELECT pg_advisory_lock(hashtextextended('export:admin:1',0))")
            try:
                with patch.object(application.order_export_process, 'build') as builder:
                    r = self.get('/api/admin/orders/export')
                    self.assertEqual(r.status_code, 429, r.json)
                    self.assertEqual(r.json['code'], 'export_in_progress')
                    self.assertGreater(int(r.headers['Retry-After']), 0)
                    builder.assert_not_called()
            finally:
                conn.execute("SELECT pg_advisory_unlock(hashtextextended('export:admin:1',0))")
        r = self.get('/api/admin/orders/export')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self.business(), before)
        r.close()

    def test_busy_retries_do_not_consume_export_quota(self):
        probe = Flask('export-quota')
        Security(probe, db, 'admin')
        builder = Mock(return_value={'ok': True})
        def build():
            return builder()
        probe.add_url_rule('/api/admin/export', 'export', build)
        client = FlaskClient(probe, probe.response_class)
        client.set_cookie(application.security.cookie, self.tokens['admin'])
        with patch.dict(os.environ, {'SECURITY_LIMIT_EXPORT': '5', 'SECURITY_LIMIT_EXPORT_POLL': '30', 'SECURITY_EXPORT_GLOBAL_CONCURRENT': '1'}):
            with db._connect(autocommit=True, coordination=True) as lock:
                for key, code in [('export:admin:1', 'export_in_progress'), ('export:global:0', 'export_capacity')]:
                    lock.execute('SELECT pg_advisory_lock(hashtextextended(%s,0))', (key,))
                    try:
                        for _ in range(6):
                            response = client.get('/api/admin/export')
                            self.assertEqual((response.status_code, response.json['code']), (429, code))
                            self.assertEqual(response.headers['Retry-After'], '5')
                    finally:
                        lock.execute('SELECT pg_advisory_unlock(hashtextextended(%s,0))', (key,))
            builder.assert_not_called()
            for _ in range(5):
                self.assertEqual(client.get('/api/admin/export').status_code, 200)
            response = client.get('/api/admin/export')
            self.assertEqual((response.status_code, response.json['code']), (429, 'rate_limited'))
            self.assertEqual(builder.call_count, 5)
            # A rate-limited request must release both locks for other requests.
            with db._connect(autocommit=True, coordination=True) as lock:
                for key in ['export:admin:1', 'export:global:0']:
                    self.assertTrue(lock.execute('SELECT pg_try_advisory_lock(hashtextextended(%s,0)) AS locked', (key,)).fetchone()['locked'])
                    lock.execute('SELECT pg_advisory_unlock(hashtextextended(%s,0))', (key,))

    def test_first_export_lock_query_failure_closes_connection(self):
        conn = MagicMock()
        def execute(sql, *args):
            if 'pg_try_advisory_lock' in sql:
                raise RuntimeError('first lock query failed')
            if 'SELECT has_waiting' in sql:
                return MagicMock(fetchone=Mock(return_value={'has_waiting': False}))
            return MagicMock(fetchall=Mock(return_value=[]))
        conn.execute.side_effect = execute
        original_connect = db._connect
        def connect(*args, **kwargs):
            return conn if kwargs.get('coordination') else original_connect(*args, **kwargs)
        with patch.object(db, '_connect', side_effect=connect):
            response = self.get('/api/admin/orders/export')
        self.assertEqual(response.status_code, 500)
        conn.close.assert_called_once_with()
        response = self.get('/api/admin/orders/export?includeImages=0')
        self.assertEqual(response.status_code, 200)
        response.close()

    def test_export_builder_failure_releases_locks(self):
        with patch.object(application.order_export_process, 'build', side_effect=RuntimeError('builder failed')):
            response = self.get('/api/admin/orders/export?includeImages=0')
        self.assertEqual(response.status_code, 500)
        response = self.get('/api/admin/orders/export?includeImages=0')
        self.assertEqual(response.status_code, 200)
        response.close()

    def test_invalid_global_export_configuration_releases_account_lock(self):
        with patch.dict(os.environ, {'SECURITY_EXPORT_GLOBAL_CONCURRENT': '0'}):
            response = self.get('/api/admin/orders/export?includeImages=0')
        self.assertEqual(response.status_code, 500)
        response = self.get('/api/admin/orders/export?includeImages=0')
        self.assertEqual(response.status_code, 200)
        response.close()

    def test_export_quota_failure_releases_both_locks(self):
        original_reserve = application.security.reserve
        def reserve(label, *args):
            if label == 'export':
                raise RuntimeError('quota unavailable')
            return original_reserve(label, *args)
        with patch.object(application.security, 'reserve', side_effect=reserve):
            response = self.get('/api/admin/orders/export?includeImages=0')
        self.assertEqual(response.status_code, 500)
        response = self.get('/api/admin/orders/export?includeImages=0')
        self.assertEqual(response.status_code, 200)
        response.close()

    def test_unexpected_errors_do_not_expose_exception_text_or_query(self):
        probe = Flask('sanitized-errors')
        Security(probe, db, 'admin')
        @probe.get('/api/auth/csrf-fixture/login')
        def fail():
            raise ValueError('credential-fixture-do-not-log')
        # Authenticate a real cookie; the endpoint name is not a login bypass.
        client = FlaskClient(probe, probe.response_class)
        client.set_cookie(application.security.cookie, self.tokens['admin'])
        with self.assertLogs(probe.logger, level='ERROR') as logs:
            r = client.get('/api/auth/csrf-fixture/login?customerName=private-fixture')
        self.assertEqual(r.status_code, 500)
        self.assertNotIn('credential-fixture', str(r.json) + '\n'.join(logs.output))
        self.assertNotIn('private-fixture', str(r.json) + '\n'.join(logs.output))
        self.assertEqual(r.headers['Cache-Control'], 'no-store')

    def test_export_query_timeout_is_independent_and_does_not_leak_to_next_request(self):
        probe = Flask('export-timeouts')
        Security(probe, db, 'admin')
        def report():
            with db._connect() as conn:
                return {'timeout': conn.execute('SHOW statement_timeout').fetchone()['statement_timeout']}
        probe.add_url_rule('/api/admin/export', 'export', report)
        probe.add_url_rule('/api/admin/report', 'report', report)
        client = FlaskClient(probe, probe.response_class)
        client.set_cookie(application.security.cookie, self.tokens['admin'])
        with patch.dict(os.environ, {'DB_STATEMENT_TIMEOUT_MS': '15000', 'DB_EXPORT_STATEMENT_TIMEOUT_MS': '60000'}), probe.app_context():
            self.assertEqual(client.get('/api/admin/report').json['timeout'], '15s')
            self.assertEqual(client.get('/api/admin/export').json['timeout'], '1min')
            self.assertEqual(client.get('/api/admin/report').json['timeout'], '15s')


if __name__ == '__main__':
    unittest.main()
