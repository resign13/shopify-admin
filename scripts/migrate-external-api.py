"""Explicit additive migration; never run from an application's startup."""
import argparse
import sys
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument('--expected-db', required=True)
args = parser.parse_args()
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'admin-backend'))
import db
import external_api_schema
if db.DB_NAME != args.expected_db: raise SystemExit('Database confirmation mismatch')
with db._connect() as conn:
    conn.execute('SET LOCAL lock_timeout=5000')
    conn.execute('SET LOCAL statement_timeout=30000')
    external_api_schema.migrate(conn.cursor())
print('API boundary schema prepared; no business rows or credentials changed')
