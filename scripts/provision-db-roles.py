"""Explicit database privilege split. Supply secrets in the process environment.

Run as the current database owner only during a separately approved cutover;
this script never changes application account passwords or business records.
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

parser=argparse.ArgumentParser()
parser.add_argument('--expected-db',required=True)
parser.add_argument('--prefix',required=True)
args=parser.parse_args()
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'admin-backend'))
import db
if db.DB_NAME!=args.expected_db: raise SystemExit('Database confirmation does not match')
if not re.fullmatch(r'[a-z][a-z0-9_]{2,38}',args.prefix): raise SystemExit('Invalid role prefix')
if db.DB_NAME.endswith('_test') and not args.prefix.endswith('_test'): raise SystemExit('Test roles require a _test prefix suffix')

def scram(password):
    salt=secrets.token_bytes(16);count=4096
    salted=hashlib.pbkdf2_hmac('sha256',password.encode(),salt,count)
    stored=hashlib.sha256(hmac.new(salted,b'Client Key',hashlib.sha256).digest()).digest()
    server=hmac.new(salted,b'Server Key',hashlib.sha256).digest()
    enc=lambda v:base64.b64encode(v).decode()
    return f'SCRAM-SHA-256${count}:{enc(salt)}${enc(stored)}:{enc(server)}'

roles={kind:args.prefix+'_'+kind for kind in ('migrator','admin','store')}
passwords={kind:os.environ.get('SECURITY_DB_'+kind.upper()+'_PASSWORD','') for kind in roles}
if any(len(v)<32 for v in passwords.values()): raise SystemExit('Three independent database passwords of at least 32 characters are required')
if len(set(passwords.values()))!=3: raise SystemExit('Database credentials must be independent')

with db._connect() as conn:
    for kind,name in roles.items():
        if not conn.execute('SELECT 1 FROM pg_roles WHERE rolname=%s',(name,)).fetchone():
            conn.execute(sql.SQL('CREATE ROLE {} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS NOINHERIT').format(sql.Identifier(name)))
        conn.execute(sql.SQL('ALTER ROLE {} WITH LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS NOINHERIT PASSWORD {}').format(sql.Identifier(name),sql.Literal(scram(passwords[kind]))))
        conn.execute(sql.SQL('GRANT CONNECT ON DATABASE {} TO {}').format(sql.Identifier(db.DB_NAME),sql.Identifier(name)))
    conn.execute('REVOKE CREATE ON SCHEMA public FROM PUBLIC')
    conn.execute(sql.SQL('REVOKE TEMPORARY ON DATABASE {} FROM PUBLIC').format(sql.Identifier(db.DB_NAME)))
    conn.execute(sql.SQL('ALTER SCHEMA public OWNER TO {}').format(sql.Identifier(roles['migrator'])))
    tables=[r['tablename'] for r in conn.execute("SELECT tablename FROM pg_tables WHERE schemaname='public'")]
    sequences=[r['sequencename'] for r in conn.execute("SELECT sequencename FROM pg_sequences WHERE schemaname='public'")]
    for name in tables:
        conn.execute(sql.SQL('ALTER TABLE public.{} OWNER TO {}').format(sql.Identifier(name),sql.Identifier(roles['migrator'])))
    for name in sequences:
        # Identity sequence ownership follows its table.
        owner=conn.execute("SELECT 1 FROM pg_depend WHERE objid=%s::regclass AND deptype IN ('a','i')",('public.'+name,)).fetchone()
        if not owner: conn.execute(sql.SQL('ALTER SEQUENCE public.{} OWNER TO {}').format(sql.Identifier(name),sql.Identifier(roles['migrator'])))
    for name in ('capture_admin_audit','capture_order_created_notification'):
        conn.execute(sql.SQL('ALTER FUNCTION public.{}() OWNER TO {}').format(sql.Identifier(name),sql.Identifier(roles['migrator'])))
        conn.execute(sql.SQL('ALTER FUNCTION public.{}() SECURITY DEFINER').format(sql.Identifier(name)))
        conn.execute(sql.SQL('ALTER FUNCTION public.{}() SET search_path TO pg_catalog,public').format(sql.Identifier(name)))
    admin=sql.Identifier(roles['admin']);store=sql.Identifier(roles['store']);migrator=sql.Identifier(roles['migrator'])
    for runtime in (admin,store):
        conn.execute(sql.SQL('GRANT USAGE ON SCHEMA public TO {}').format(runtime))
        conn.execute(sql.SQL('REVOKE ALL ON ALL TABLES IN SCHEMA public FROM {}').format(runtime))
        conn.execute(sql.SQL('REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM {}').format(runtime))
    conn.execute(sql.SQL('GRANT SELECT,INSERT,UPDATE,DELETE ON ALL TABLES IN SCHEMA public TO {}').format(admin))
    conn.execute(sql.SQL('GRANT USAGE,SELECT ON ALL SEQUENCES IN SCHEMA public TO {}').format(admin))
    conn.execute(sql.SQL('ALTER DEFAULT PRIVILEGES FOR ROLE {} IN SCHEMA public GRANT SELECT,INSERT,UPDATE,DELETE ON TABLES TO {}').format(migrator,admin))
    conn.execute(sql.SQL('ALTER DEFAULT PRIVILEGES FOR ROLE {} IN SCHEMA public GRANT USAGE,SELECT ON SEQUENCES TO {}').format(migrator,admin))
    read=['security_schema_versions','security_media_migrations','products','product_categories','product_category_translations','product_translations','product_sizes','product_size_prices','product_images','banners','banner_translations','homepage_configs','presale_configs','store_users','orders','order_items','inventory_legacy_cancelled_orders','security_files','security_file_refs']
    for name in read:
        if name in tables: conn.execute(sql.SQL('GRANT SELECT ON public.{} TO {}').format(sql.Identifier(name),store))
    for name in ['orders','order_items','store_sessions','security_files','security_file_refs','security_audit_events','security_rate_buckets','security_request_metrics']:
        conn.execute(sql.SQL('GRANT INSERT ON public.{} TO {}').format(sql.Identifier(name),store))
    for name in ['store_sessions','security_rate_buckets','security_request_metrics']:
        conn.execute(sql.SQL('GRANT SELECT,UPDATE ON public.{} TO {}').format(sql.Identifier(name),store))
    conn.execute(sql.SQL('GRANT DELETE ON public.security_file_refs TO {}').format(store))
    conn.execute(sql.SQL('GRANT UPDATE(updated_at) ON public.store_users TO {}').format(store))
    conn.execute(sql.SQL('GRANT UPDATE(stock,updated_at) ON public.products TO {}').format(store))
    conn.execute(sql.SQL('GRANT UPDATE(stock) ON public.product_size_prices TO {}').format(store))
    # Number assignment and customer cancellation need only these columns.
    # Do not grant table-wide UPDATE (prices, ownership and payment data stay locked).
    conn.execute(sql.SQL('GRANT UPDATE(order_no,status,updated_at,cancellation_note) ON public.orders TO {}').format(store))
    for name in ['orders_id_seq','order_items_id_seq','store_sessions_id_seq','security_audit_events_id_seq']:
        if name in sequences: conn.execute(sql.SQL('GRANT USAGE,SELECT ON public.{} TO {}').format(sql.Identifier(name),store))
print('Database roles provisioned; runtime DDL and storefront finance/account-management access removed')
