"""Real PostgreSQL pooling/transaction boundaries; isolated local *_test only."""
import os
if os.environ.get('PGHOST')!='127.0.0.1' or not os.environ.get('PGDATABASE','').endswith('_test'):
    raise RuntimeError('Explicit isolated local *_test database required')
from concurrent.futures import ThreadPoolExecutor
import hashlib
import secrets
import time
import unittest
from unittest.mock import patch
import psycopg
from psycopg import sql
from psycopg.rows import dict_row, tuple_row
import db
import database_pool as pooling


class DatabasePoolTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        assert db.DB_HOST=='127.0.0.1' and db.DB_NAME.endswith('_test')
        cls.kwargs=dict(host=db.DB_HOST,port=db.DB_PORT,dbname=db.DB_NAME,user=db.DB_USER,
            password=db.DB_PASSWORD,row_factory=dict_row,connect_timeout=2)
        cls.role='pool_'+hashlib.sha256(db.DB_NAME.encode()).hexdigest()[:12]+'_test'
        cls.secret=secrets.token_urlsafe(40)
        with psycopg.connect(**cls.kwargs) as conn:
            conn.execute('CREATE TABLE IF NOT EXISTS connection_reuse_fixture(id integer PRIMARY KEY,value integer NOT NULL)')
            if not conn.execute('SELECT 1 FROM pg_roles WHERE rolname=%s',(cls.role,)).fetchone():
                conn.execute(sql.SQL('CREATE ROLE {} LOGIN').format(sql.Identifier(cls.role)))
            conn.execute(sql.SQL('ALTER ROLE {} PASSWORD {}').format(sql.Identifier(cls.role),sql.Literal(cls.secret)))
            conn.execute(sql.SQL('GRANT CONNECT ON DATABASE {} TO {}').format(sql.Identifier(db.DB_NAME),sql.Identifier(cls.role)))
            conn.execute(sql.SQL('GRANT USAGE ON SCHEMA public TO {}').format(sql.Identifier(cls.role)))
            conn.execute(sql.SQL('GRANT SELECT ON connection_reuse_fixture TO {}').format(sql.Identifier(cls.role)))

    @classmethod
    def tearDownClass(cls):
        pooling.close_all()
        with psycopg.connect(**cls.kwargs) as conn:
            conn.execute('DROP TABLE connection_reuse_fixture')
            conn.execute(sql.SQL('REVOKE ALL ON DATABASE {} FROM {}').format(sql.Identifier(db.DB_NAME),sql.Identifier(cls.role)))
            conn.execute(sql.SQL('REVOKE ALL ON SCHEMA public FROM {}').format(sql.Identifier(cls.role)))
            conn.execute(sql.SQL('DROP ROLE {}').format(sql.Identifier(cls.role)))

    def setUp(self):
        pooling.close_all()
        self.env=patch.dict(os.environ,{'DB_UNIT_POOL_MAX':'2','DB_UNIT_POOL_MAX_WAITING':'2','DB_UNIT_POOL_TIMEOUT_SECONDS':'0.5'})
        self.env.start()
        with psycopg.connect(**self.kwargs) as conn:conn.execute('TRUNCATE connection_reuse_fixture')

    def tearDown(self):
        pooling.close_all();self.env.stop()

    def borrow(self,**kwargs):
        return pooling.borrow(self.kwargs,namespace='pool-test',prefix='DB_UNIT',**kwargs)

    def count(self):
        with psycopg.connect(**self.kwargs) as conn:
            return conn.execute('SELECT count(*) AS n FROM connection_reuse_fixture').fetchone()['n']

    def test_context_commit_exception_rollback_and_explicit_close_rollback(self):
        with self.borrow() as conn:conn.execute('INSERT INTO connection_reuse_fixture VALUES(1,10)')
        self.assertTrue(conn.closed)
        with self.assertRaises(RuntimeError):
            with self.borrow() as conn:
                conn.execute('INSERT INTO connection_reuse_fixture VALUES(2,20)')
                raise RuntimeError('fixture rollback')
        conn=self.borrow();conn.execute('INSERT INTO connection_reuse_fixture VALUES(3,30)');conn.close();conn.close()
        self.assertEqual(self.count(),1)
        with self.assertRaises(psycopg.OperationalError):conn.execute('SELECT 1')

    def test_16_clients_reuse_at_most_two_physical_connections(self):
        def one(_):
            with self.borrow() as conn:
                pid=conn.info.backend_pid;conn.execute('SELECT pg_sleep(0.01)')
                return pid
        with patch.dict(os.environ,{'DB_UNIT_POOL_TIMEOUT_SECONDS':'2','DB_UNIT_POOL_MAX_WAITING':'32'}):
            with ThreadPoolExecutor(max_workers=16) as pool: pids=list(pool.map(one,range(32)))
        self.assertLessEqual(len(set(pids)),2)
        self.assertLessEqual(pooling.statistics()['pool-test']['connections_num'],2)

    def test_exhaustion_has_bounded_wait_no_raw_fallback_or_business_write(self):
        first=self.borrow();second=self.borrow();started=time.perf_counter()
        try:
            with self.assertRaises(pooling.DatabaseBusy):self.borrow()
            self.assertLess(time.perf_counter()-started,1.5)
            self.assertEqual(self.count(),0)
        finally:first.close();second.close()
        with self.borrow() as conn:self.assertEqual(conn.execute('SELECT 1 AS n').fetchone()['n'],1)

    def test_concurrent_close_returns_a_connection_only_once(self):
        conn=self.borrow()
        with ThreadPoolExecutor(max_workers=8) as executor:list(executor.map(lambda _:conn.close(),range(32)))
        self.assertTrue(conn.closed)
        with self.borrow() as conn:self.assertEqual(conn.execute('SELECT 1 AS n').fetchone()['n'],1)

    def test_bounded_wait_queue_rejects_extra_client(self):
        with patch.dict(os.environ,{'DB_UNIT_POOL_MAX_WAITING':'1','DB_UNIT_POOL_TIMEOUT_SECONDS':'2'}):
            first=self.borrow();second=self.borrow()
            with ThreadPoolExecutor(max_workers=1) as executor:
                future=executor.submit(self.borrow)
                deadline=time.monotonic()+1
                while pooling.statistics()['pool-test'].get('requests_waiting',0)!=1 and time.monotonic()<deadline:time.sleep(.01)
                started=time.monotonic()
                try:
                    with self.assertRaises(pooling.DatabaseBusy):self.borrow()
                    self.assertLess(time.monotonic()-started,.5)
                finally:first.close();second.close()
                future.result(timeout=2).close()

    def test_session_role_gucs_temp_objects_and_locks_do_not_leak(self):
        with self.borrow() as conn:
            conn.execute('CREATE TEMP TABLE pool_temporary_fixture(n integer)')
            conn.execute("SET search_path=pg_catalog; SET statement_timeout=17")
            conn.execute('SELECT pg_advisory_lock(936417021)')
            conn.execute(sql.SQL('SET ROLE {}').format(sql.Identifier(self.role)))
            conn.commit();conn.row_factory=tuple_row;conn.read_only=True
        with self.borrow(settings={'statement_timeout':15000,'lock_timeout':5000}) as conn:
            row=conn.execute("SELECT current_user AS role,current_setting('statement_timeout') AS timeout,current_setting('transaction_read_only') AS ro,to_regclass('pg_temp.pool_temporary_fixture') AS temp").fetchone()
            self.assertEqual(row,{'role':db.DB_USER,'timeout':'15s','ro':'off','temp':None})
        with psycopg.connect(**self.kwargs) as peer:
            self.assertTrue(peer.execute('SELECT pg_try_advisory_lock(936417021) AS locked').fetchone()['locked'])
            peer.execute('SELECT pg_advisory_unlock(936417021)')

    def test_readonly_snapshot_and_notifications_flags_do_not_leak(self):
        with self.borrow(settings={'gingtto.notifications_paused':'on'}) as conn:
            conn.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
            with self.assertRaises(psycopg.errors.ReadOnlySqlTransaction):conn.execute('INSERT INTO connection_reuse_fixture VALUES(5,5)')
        with self.borrow(settings={'gingtto.notifications_paused':'off'}) as conn:
            self.assertEqual(conn.execute("SELECT current_setting('gingtto.notifications_paused') AS n,current_setting('transaction_read_only') AS ro").fetchone(),{'n':'off','ro':'off'})
            conn.execute('INSERT INTO connection_reuse_fixture VALUES(5,5)')
        self.assertEqual(self.count(),1)

    def test_dead_socket_is_replaced_without_replaying_a_write(self):
        conn=self.borrow();pid=conn.info.backend_pid
        conn.execute('INSERT INTO connection_reuse_fixture VALUES(1,1)')
        with psycopg.connect(**self.kwargs) as peer:
            row=peer.execute("SELECT datname,application_name FROM pg_stat_activity WHERE pid=%s",(pid,)).fetchone()
            self.assertEqual(row,{'datname':db.DB_NAME,'application_name':'gingtto-pool-test'})
            peer.execute('SELECT pg_terminate_backend(%s)',(pid,))
        with self.assertRaises(psycopg.OperationalError):conn.execute('SELECT 1')
        conn.close()
        with self.borrow() as replacement:self.assertNotEqual(replacement.info.backend_pid,pid)
        self.assertEqual(self.count(),0)

    def test_namespace_and_credential_boundaries(self):
        with self.borrow() as conn:pid=conn.info.backend_pid
        other={**self.kwargs,'user':self.role,'password':self.secret}
        with pooling.borrow(other,namespace='pool-test',prefix='DB_UNIT') as conn:
            self.assertNotEqual(conn.info.backend_pid,pid)
            self.assertEqual(conn.execute('SELECT current_user AS n').fetchone()['n'],self.role)
            with self.assertRaises(psycopg.errors.InsufficientPrivilege):conn.execute('INSERT INTO connection_reuse_fixture VALUES(1,1)')
        with self.borrow() as conn:self.assertEqual(conn.execute('SELECT current_user AS n').fetchone()['n'],db.DB_USER)
        with pooling.borrow(self.kwargs,namespace='external-budget-fixture',prefix='DB_UNIT') as conn:
            with self.borrow() as other:self.assertNotEqual(conn.info.backend_pid,other.info.backend_pid)

    def test_connection_options_are_reapplied_not_sticky(self):
        for ms in (60000,15000,5000):
            with self.borrow(settings={'statement_timeout':ms}) as conn:
                self.assertEqual(conn.execute("SELECT current_setting('statement_timeout')::interval AS v").fetchone()['v'].total_seconds(),ms/1000)

    def test_ambient_pgoptions_does_not_replace_explicit_runtime_settings(self):
        with patch.dict(os.environ,{'PGOPTIONS':'-c default_transaction_read_only=on'}):
            with self.borrow(settings={'statement_timeout':15000}) as conn:
                self.assertEqual(conn.execute("SELECT current_setting('transaction_read_only') AS ro").fetchone()['ro'],'off')
                conn.execute('INSERT INTO connection_reuse_fixture VALUES(1,1)')
        self.assertEqual(self.count(),1)

    def test_cross_process_lease_rejected_and_import_does_not_preload_pool(self):
        conn=self.borrow()
        with patch('database_pool.os.getpid',return_value=os.getpid()+1):
            with self.assertRaises(psycopg.OperationalError):conn.execute('SELECT 1')
        conn.close()
        with patch.dict(os.environ,{'APP_ENV':'production'}):self.assertFalse(pooling.enabled())

    def test_pool_off_and_invalid_capacity_settings(self):
        with patch.dict(os.environ,{'DB_POOL_ENABLED':'0'}):
            with db._connect() as conn:self.assertIsInstance(conn,psycopg.Connection)
        for setting,value in [('DB_UNIT_POOL_MAX','0'),('DB_UNIT_POOL_MAX_WAITING','0'),('DB_UNIT_POOL_TIMEOUT_SECONDS','99')]:
            with patch.dict(os.environ,{setting:value}):
                with self.assertRaises(ValueError):self.borrow()

    def test_capacity_failure_http503_retry_after_no_session_revocation(self):
        import app as application
        from flask.testing import FlaskClient
        client=FlaskClient(application.app,application.app.response_class)
        client.set_cookie(application.app.extensions['security'].cookie,secrets.token_urlsafe(32))
        with patch.object(db,'_connect',side_effect=pooling.DatabaseBusy('fixture budget full')):
            response=client.get('/api/auth/me')
        self.assertEqual(response.status_code,503)
        self.assertEqual(response.json['code'],'database_busy')
        self.assertEqual(response.headers['Retry-After'],'2')
        self.assertNotIn('X-Session-Revoked',response.headers)


if __name__=='__main__':unittest.main()
