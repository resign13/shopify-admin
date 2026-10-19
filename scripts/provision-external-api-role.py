"""Explicit least-privilege role provisioning, not called by either web app."""
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
parser.add_argument('--role', required=True)
args = parser.parse_args()
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'admin-backend'))
import db
from external_api_schema import VIEWS
if db.DB_NAME != args.expected_db or not re.fullmatch(r'[a-z][a-z0-9_]{2,55}', args.role):
    raise SystemExit('Explicit database and role required')
if db.DB_NAME.endswith('_test') and not args.role.endswith('_test'):
    raise SystemExit('Test-only role suffix required')
password = os.environ.get('EXTERNAL_API_DB_PASSWORD', '')
if len(password) < 32 or len(set(password)) < 16 or password == db.DB_PASSWORD:
    raise SystemExit('Independent generated API database credential required')
salt = secrets.token_bytes(16)
salted = hashlib.pbkdf2_hmac('sha256', password.encode(), salt, 4096)
stored = hashlib.sha256(hmac.new(salted, b'Client Key', hashlib.sha256).digest()).digest()
server = hmac.new(salted, b'Server Key', hashlib.sha256).digest()
encode = lambda value: base64.b64encode(value).decode()
verifier = f'SCRAM-SHA-256$4096:{encode(salt)}${encode(stored)}:{encode(server)}'
with db._connect() as conn:
    role = sql.Identifier(args.role)
    existing = conn.execute('SELECT oid FROM pg_roles WHERE rolname=%s', (args.role,)).fetchone()
    if existing:
        flags = conn.execute('SELECT rolsuper,rolcreatedb,rolcreaterole,rolbypassrls FROM pg_roles WHERE rolname=%s',(args.role,)).fetchone()
        if any(flags.values()): raise RuntimeError('Existing privileged identity must not be repurposed for the API')
        if conn.execute('SELECT 1 FROM pg_auth_members WHERE member=%s', (existing['oid'],)).fetchone() or conn.execute('''
          SELECT 1 FROM pg_class WHERE relowner=%s UNION ALL SELECT 1 FROM pg_namespace WHERE nspowner=%s
          UNION ALL SELECT 1 FROM pg_database WHERE datdba=%s LIMIT 1''', (existing['oid'],)*3).fetchone():
            raise RuntimeError('API identity has inherited or ownership privileges')
        for table in conn.execute("SELECT c.relname FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='public' AND c.relkind IN ('r','p','v','m','f')").fetchall():
            name = table['relname']
            if name in {'api_integrations','api_call_logs','api_rate_buckets','api_request_leases',*VIEWS}: continue
            if conn.execute("SELECT has_any_column_privilege(%s,%s,'SELECT,INSERT,UPDATE,REFERENCES') OR has_table_privilege(%s,%s,'DELETE,TRUNCATE,TRIGGER') AS excessive", (args.role,name,args.role,name)).fetchone()['excessive']:
                raise RuntimeError('Existing business or maintenance identity must not be repurposed for the API')
    else: conn.execute(sql.SQL('CREATE ROLE {} LOGIN').format(role))
    conn.execute(sql.SQL('ALTER ROLE {} WITH LOGIN NOINHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS PASSWORD {}').format(role, sql.Literal(verifier)))
    conn.execute(sql.SQL('REVOKE ALL ON ALL TABLES IN SCHEMA public FROM {}').format(role))
    conn.execute(sql.SQL('REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM {}').format(role))
    conn.execute(sql.SQL('REVOKE ALL ON DATABASE {} FROM {}').format(sql.Identifier(db.DB_NAME), role))
    conn.execute(sql.SQL('GRANT CONNECT ON DATABASE {} TO {}').format(sql.Identifier(db.DB_NAME), role))
    conn.execute(sql.SQL('GRANT USAGE ON SCHEMA public TO {}').format(role))
    excessive = conn.execute("SELECT has_schema_privilege(%s,'public','CREATE') OR has_database_privilege(%s,current_database(),'CREATE,TEMP') AS excessive", (args.role, args.role)).fetchone()['excessive']
    if excessive: raise RuntimeError('Remove inherited PUBLIC creation/TEMP privileges in a separately reviewed database change first')
    for view in VIEWS:
        conn.execute(sql.SQL('GRANT SELECT ON {} TO {}').format(sql.Identifier(view), role))
    conn.execute(sql.SQL('GRANT SELECT(admin_user_id,key_id), UPDATE(last_used_at) ON api_integrations TO {}').format(role))
    conn.execute(sql.SQL('GRANT INSERT ON api_call_logs TO {}').format(role))
    conn.execute(sql.SQL('GRANT USAGE ON SEQUENCE api_call_logs_id_seq TO {}').format(role))
    conn.execute(sql.SQL('GRANT SELECT,INSERT,UPDATE ON api_rate_buckets TO {}').format(role))
    conn.execute(sql.SQL('GRANT SELECT,INSERT,DELETE ON api_request_leases TO {}').format(role))
print('External API database role prepared; no business table grants')
