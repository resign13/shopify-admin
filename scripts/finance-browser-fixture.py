"""Finance browser fixture; never point it at a manual or production database."""
import os
import sys
from pathlib import Path

if os.environ.get('PGHOST') != '127.0.0.1' or not os.environ.get('PGDATABASE', '').endswith('_test'):
    raise RuntimeError('Explicit isolated local *_test database required')

import psycopg
from psycopg.sql import SQL, Identifier
from werkzeug.security import generate_password_hash

with psycopg.connect(host='127.0.0.1', port=os.environ['PGPORT'], dbname='postgres',
                     user=os.environ['PGUSER'], password=os.environ['PGPASSWORD'], autocommit=True) as conn:
    name = os.environ['PGDATABASE']
    if not conn.execute('SELECT 1 FROM pg_database WHERE datname=%s', (name,)).fetchone():
        conn.execute(SQL('CREATE DATABASE {}').format(Identifier(name)))

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root / 'admin-backend'))
os.environ['ORDER_VOICE_ENABLED'] = '0'
import test_workbench as fixtures

if __name__ == '__main__':
    fixtures.seed()
    with fixtures.db.get_connection() as conn:
        conn.execute('TRUNCATE finance_cost_history,finance_cost_versions,finance_cost_audit,finance_cost_receipts,finance_settings RESTART IDENTITY')
        conn.execute("DELETE FROM product_size_prices WHERE product_id=3 AND size_code='L'")
        conn.execute("DELETE FROM product_sizes WHERE product_id=3 AND size_code='L'")
    fixtures.db.create_admin_user({'name':'财务测试员','email':'finance@gingtto.test',
        'passwordHash':generate_password_hash('Workbench-Test-2026', method='pbkdf2:sha256:1000'),
        'status':'active','role':'finance'})
    fixtures.application.app.run(host='127.0.0.1', port=5362, threaded=True, use_reloader=False)
