"""Finance browser fixture; never point it at a manual or production database."""
import os
import sys
import uuid
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
        conn.execute('TRUNCATE finance_cost_history,finance_cost_versions,finance_cost_audit,finance_cost_receipts,finance_settings,finance_style_costs,finance_style_cost_audit RESTART IDENTITY')
        conn.execute("DELETE FROM product_size_prices WHERE product_id=3 AND size_code='L'")
        conn.execute("DELETE FROM product_sizes WHERE product_id=3 AND size_code='L'")
        conn.execute("UPDATE products SET style_code='GT-OTHER' WHERE id=2")
    fixtures.db.create_admin_user({'name':'财务测试员','email':'finance@gingtto.test',
        'passwordHash':generate_password_hash('Workbench-Test-2026', method='pbkdf2:sha256:1000'),
        'status':'active','role':'finance'})
    # Historical events in the isolated fixture let the UI prove that current
    # edits/clears do not reprice earlier orders, including same-day changes.
    with fixtures.db.get_connection() as conn:
        for old,cost,stamp in [(None,12,'2026-09-15T12:00:00+08:00'),(12,18,'2026-09-18T09:00:00+08:00')]:
            conn.execute("INSERT INTO finance_style_cost_audit(style_code,old_cost_cny,cost_cny,actor,request_id,created_at,effective_at,is_initial) VALUES('GT-2026',%s,%s,'{\"name\":\"历史成本夹具\"}',%s,%s,%s,%s)",(old,cost,uuid.uuid4(),stamp,stamp,old is None))
        conn.execute("INSERT INTO finance_style_costs(style_code,cost_cny,revision,updated_at) VALUES('GT-2026',18,2,'2026-09-18T09:00:00+08:00')")
    fixtures.application.app.run(host='127.0.0.1', port=5362, threaded=True, use_reloader=False)
