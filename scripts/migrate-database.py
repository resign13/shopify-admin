"""Explicit schema migration entrypoint, separate from runtime startup."""
import argparse
import os
from pathlib import Path
import sys

parser = argparse.ArgumentParser()
parser.add_argument('--expected-db', required=True)
parser.add_argument('--backend', choices=['admin-backend', 'storefront-backend'], default='admin-backend')
parser.add_argument('--prepare-only', action='store_true')
args = parser.parse_args()
if args.prepare_only: os.environ['SECURITY_MIGRATION_PREPARE_ONLY'] = '1'
root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root / args.backend))
for name in ('PGUSER', 'PGPASSWORD'):
    if os.environ.get('MIGRATION_' + name):
        os.environ[name] = os.environ['MIGRATION_' + name]
os.environ['ORDER_NOTIFICATION_MAINTENANCE'] = '1'
os.environ['DB_STATEMENT_TIMEOUT_MS'] = '300000'
os.environ['DB_LOCK_TIMEOUT_MS'] = '30000'
import db
if db.DB_NAME != args.expected_db:
    raise RuntimeError('Database name does not match the explicit migration target')
db.migrate_database()
print('Database schema migration completed; runtime startup performs read-only checks.')
