"""Real auxiliary-role checks on an explicitly isolated local *_test database."""
import argparse
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import psycopg

parser = argparse.ArgumentParser()
parser.add_argument('--expected-db', required=True)
parser.add_argument('--prefix', required=True)
args = parser.parse_args()
if os.environ.get('PGHOST') != '127.0.0.1' or os.environ.get('PGDATABASE') != args.expected_db or not args.expected_db.endswith('_test') or not args.prefix.endswith('_test'):
    raise SystemExit('Explicit isolated local *_test database and role prefix required')
root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root / 'admin-backend'))
os.environ.update(APP_ENV='test', DB_SCHEMA_AUTO_MIGRATE='1', PRIVATE_STORAGE_BUCKET='')
import test_workbench as fixtures
fixtures.seed()
db = fixtures.db
business_tables = ['orders', 'order_items', 'products', 'product_size_prices', 'finance_cost_history','finance_style_costs','finance_style_cost_audit', 'store_users', 'admin_users']


def business_fingerprint():
    with db._connect() as conn:
        conn.execute('SET TRANSACTION READ ONLY')
        return {name: conn.execute('SELECT md5(COALESCE(jsonb_agg(to_jsonb(t) ORDER BY to_jsonb(t)::text)::text,\'[]\')) AS digest FROM ' + name + ' t').fetchone()['digest'] for name in business_tables}


with db._connect() as conn:
    baseline = conn.execute('SELECT last_sequence FROM order_notification_state FOR UPDATE').fetchone()['last_sequence']
    ids = [r['id'] for r in conn.execute('SELECT id FROM orders ORDER BY id LIMIT 2').fetchall()]
    old = conn.execute("INSERT INTO order_created_events(order_id,recorded_at,publish_sequence) VALUES(%s,clock_timestamp()-interval '8 days',%s) RETURNING id", (ids[0], baseline + 1)).fetchone()['id']
    fresh = conn.execute('INSERT INTO order_created_events(order_id,publish_sequence) VALUES(%s,%s) RETURNING id', (ids[1], baseline + 2)).fetchone()['id']
    conn.execute('UPDATE order_notification_state SET last_sequence=%s', (baseline + 2,))
before = business_fingerprint()
env = os.environ.copy()
passwords = {kind: secrets.token_urlsafe(40) for kind in ['migrator', 'admin', 'store', 'maintenance', 'exporter']}
for kind, value in passwords.items(): env['SECURITY_DB_' + kind.upper() + '_PASSWORD'] = value
for script in ['provision-db-roles.py', 'provision-security-roles.py']:
    result = subprocess.run([sys.executable, str(root / 'scripts' / script), '--expected-db', args.expected_db, '--prefix', args.prefix], env=env, capture_output=True, text=True, timeout=60)
    if result.returncode: raise RuntimeError('Auxiliary role setup failed')
base = dict(host='127.0.0.1', port=int(env['PGPORT']), dbname=args.expected_db, autocommit=True)
for kind in ['maintenance', 'exporter']:
    with psycopg.connect(**base, user=args.prefix + '_' + kind, password=passwords[kind]) as conn:
        flags = conn.execute('SELECT rolsuper,rolcreatedb,rolcreaterole,rolbypassrls FROM pg_roles WHERE rolname=current_user').fetchone()
        assert not any(flags)
        if kind == 'exporter':
            assert conn.execute('SHOW default_transaction_read_only').fetchone()[0] == 'on'
            conn.execute('SET default_transaction_read_only=off')
            for statement in ["UPDATE products SET stock=stock WHERE id=1", "SELECT nextval('orders_id_seq')", 'CREATE TABLE public.forbidden_aux(id integer)']:
                try: conn.execute(statement)
                except psycopg.errors.InsufficientPrivilege: pass
                else: raise AssertionError('Read-only snapshot role gained write/DDL access')
            for table in ['orders', 'products', 'finance_cost_history','finance_style_costs','finance_style_cost_audit', 'admin_users']:
                conn.execute('SELECT count(*) FROM ' + table).fetchone()
        else:
            for table in ['orders', 'products', 'finance_cost_history','finance_style_costs','finance_style_cost_audit', 'admin_users']:
                try: conn.execute('SELECT 1 FROM ' + table + ' LIMIT 1')
                except psycopg.errors.InsufficientPrivilege: pass
                else: raise AssertionError('Maintenance role gained business access')
            for statement in ['SELECT token_hash FROM admin_sessions', 'SELECT token_hash FROM store_sessions',
                    'SELECT ip_digest FROM security_audit_events', 'SELECT last_sequence FROM order_notification_state',
                    'UPDATE order_created_events SET publish_sequence=publish_sequence',
                    'INSERT INTO order_created_events(order_id) VALUES(1)']:
                try: conn.execute(statement)
                except psycopg.errors.InsufficientPrivilege: pass
                else: raise AssertionError('Maintenance role gained session secrets/publication access')
            for statement in ['CREATE TABLE public.forbidden_aux(id integer)', 'UPDATE security_rate_buckets SET ticks=ticks']:
                try: conn.execute(statement)
                except psycopg.errors.InsufficientPrivilege: pass
                else: raise AssertionError('Maintenance role gained unneeded rights')
            conn.execute("DELETE FROM security_audit_events WHERE created_at<clock_timestamp()-interval '90 days'")
child = env.copy(); child.update(PGUSER=args.prefix + '_maintenance', PGPASSWORD=passwords['maintenance'])
for script in ['security-maintenance.py', 'cleanup-order-notifications.py', 'cleanup-order-notifications.py']:
    result = subprocess.run([sys.executable, str(root / 'scripts' / script), '--expected-db', args.expected_db], env=child, capture_output=True, text=True, timeout=45)
    if result.returncode: raise RuntimeError('Metadata cleanup failed with its actual limited role: ' + script)
with db._connect() as conn:
    assert not conn.execute('SELECT 1 FROM order_created_events WHERE id=%s', (old,)).fetchone()
    assert conn.execute('SELECT 1 FROM order_created_events WHERE id=%s', (fresh,)).fetchone()
    assert conn.execute('SELECT last_sequence FROM order_notification_state').fetchone()['last_sequence'] == baseline + 2
assert business_fingerprint() == before, 'Cleanup changed business records'
runtime = env.copy(); runtime.update(PGUSER=args.prefix + '_exporter', PGPASSWORD=passwords['exporter'], ORDER_VOICE_CURSOR_SECRET=secrets.token_urlsafe(40))
for mode in ['enable', 'disable']:
    runtime['ORDER_VOICE_ENABLED'] = '1' if mode == 'enable' else '0'
    command = [sys.executable, str(root / 'scripts/verify-order-notifications.py'), '--expect-enabled', mode]
    result = subprocess.run(command, env=runtime, capture_output=True, text=True, timeout=30)
    if result.returncode: raise RuntimeError('Read-only runtime notification check failed')
    runtime['ORDER_VOICE_ENABLED'] = '0' if mode == 'enable' else '1'
    result = subprocess.run(command, env=runtime, capture_output=True, text=True, timeout=30)
    assert result.returncode != 0, 'Mismatched notification switch was accepted'
print(json.dumps({'maintenanceBusinessAccessDenied': True, 'maintenanceJobPassed': True,
    'notificationRetentionPassed': True, 'publicationStatePreserved': True, 'businessFingerprintsUnchanged': True,
    'maintenanceCannotReadSessionSecrets': True, 'runtimeVoiceFlagAndMismatchVerified': True,
    'snapshotReadOnlyDefault': True, 'snapshotWritesAndSequenceAdvanceDenied': True,
    'runtimeDdlDenied': True, 'existingExportChannelChanged': False, 'productionModified': False}))
