"""Explicit metadata-maintenance and encrypted-snapshot DB identities.

Not an external API credential. Requires the separately prepared migrator role;
no business records, customer passwords or existing export channel are changed.
"""
import argparse
import base64
import hashlib
import hmac
import os
from pathlib import Path
import re
import secrets
import sys
from psycopg import sql

parser = argparse.ArgumentParser()
parser.add_argument('--expected-db', required=True)
parser.add_argument('--prefix', required=True)
args = parser.parse_args()
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'admin-backend'))
import db
if db.DB_NAME != args.expected_db or not re.fullmatch(r'[a-z][a-z0-9_]{2,38}', args.prefix):
    raise SystemExit('Explicit database and valid role prefix required')
if db.DB_NAME.endswith('_test') and not args.prefix.endswith('_test'):
    raise SystemExit('Isolated test role prefix required')
roles = {kind: args.prefix + '_' + kind for kind in ['maintenance', 'exporter']}
passwords = {kind: os.environ.get('SECURITY_DB_' + kind.upper() + '_PASSWORD', '') for kind in roles}
provided = [value for name, value in os.environ.items() if name.startswith('SECURITY_DB_') and name.endswith('_PASSWORD')]
if any(len(v) < 32 for v in passwords.values()) or len(set(provided)) != len(provided):
    raise SystemExit('Independent generated database credentials required')


def verifier(password):
    salt = secrets.token_bytes(16)
    salted = hashlib.pbkdf2_hmac('sha256', password.encode(), salt, 4096)
    stored = hashlib.sha256(hmac.new(salted, b'Client Key', hashlib.sha256).digest()).digest()
    server = hmac.new(salted, b'Server Key', hashlib.sha256).digest()
    encode = lambda b: base64.b64encode(b).decode()
    return f'SCRAM-SHA-256$4096:{encode(salt)}${encode(stored)}:{encode(server)}'


with db._connect() as conn:
    migrator = args.prefix + '_migrator'
    if not conn.execute('SELECT 1 FROM pg_roles WHERE rolname=%s', (migrator,)).fetchone():
        raise RuntimeError('Prepare primary database identities first')
    for kind, name in roles.items():
        role = sql.Identifier(name)
        existing = conn.execute('SELECT oid FROM pg_roles WHERE rolname=%s', (name,)).fetchone()
        if existing:
            if conn.execute('SELECT 1 FROM pg_auth_members WHERE member=%s', (existing['oid'],)).fetchone() or conn.execute("SELECT 1 FROM pg_class WHERE relowner=%s UNION ALL SELECT 1 FROM pg_namespace WHERE nspowner=%s UNION ALL SELECT 1 FROM pg_database WHERE datdba=%s LIMIT 1", (existing['oid'],) * 3).fetchone():
                raise RuntimeError('Auxiliary role has inherited/ownership privileges')
        else:
            conn.execute(sql.SQL('CREATE ROLE {} LOGIN').format(role))
        conn.execute(sql.SQL('ALTER ROLE {} WITH LOGIN NOINHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS PASSWORD {}').format(role, sql.Literal(verifier(passwords[kind]))))
        conn.execute(sql.SQL('REVOKE ALL ON ALL TABLES IN SCHEMA public FROM {}').format(role))
        conn.execute(sql.SQL('REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM {}').format(role))
        conn.execute(sql.SQL('REVOKE ALL ON DATABASE {} FROM {}').format(sql.Identifier(db.DB_NAME), role))
        conn.execute(sql.SQL('GRANT CONNECT ON DATABASE {} TO {}').format(sql.Identifier(db.DB_NAME), role))
        conn.execute(sql.SQL('GRANT USAGE ON SCHEMA public TO {}').format(role))
        excessive = conn.execute("SELECT has_database_privilege(%s,current_database(),'CREATE') OR has_database_privilege(%s,current_database(),'TEMP') OR has_schema_privilege(%s,'public','CREATE') AS excessive", (name,) * 3).fetchone()['excessive']
        if excessive: raise RuntimeError('Remove inherited database/schema creation privileges first')
    maintenance = sql.Identifier(roles['maintenance']); exporter = sql.Identifier(roles['exporter'])
    retention_columns = {'security_audit_events': ['created_at'], 'security_request_metrics': ['hour'],
        'security_rate_buckets': ['updated_at', 'blocked_until'], 'store_sessions': ['expires_at'],
        'admin_sessions': ['expires_at'], 'order_created_events': ['recorded_at']}
    for table, columns in retention_columns.items():
        conn.execute(sql.SQL('GRANT DELETE ON public.{} TO {}').format(sql.Identifier(table), maintenance))
        conn.execute(sql.SQL('GRANT SELECT ({}) ON public.{} TO {}').format(
            sql.SQL(',').join(map(sql.Identifier, columns)), sql.Identifier(table), maintenance))
    conn.execute(sql.SQL('GRANT SELECT ON ALL TABLES IN SCHEMA public TO {}').format(exporter))
    conn.execute(sql.SQL('GRANT SELECT ON ALL SEQUENCES IN SCHEMA public TO {}').format(exporter))
    conn.execute(sql.SQL('ALTER DEFAULT PRIVILEGES FOR ROLE {} IN SCHEMA public GRANT SELECT ON TABLES TO {}').format(sql.Identifier(migrator), exporter))
    conn.execute(sql.SQL('ALTER DEFAULT PRIVILEGES FOR ROLE {} IN SCHEMA public GRANT SELECT ON SEQUENCES TO {}').format(sql.Identifier(migrator), exporter))
    conn.execute(sql.SQL('ALTER ROLE {} SET default_transaction_read_only=on').format(exporter))
print('Auxiliary database identities provisioned; existing encrypted export channel unchanged')
