"""Deterministic order totals browser fixture; never use the synchronized database."""
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys

if os.environ.get('PGHOST') != '127.0.0.1' or not os.environ.get('PGDATABASE', '').endswith('_test'):
    raise RuntimeError('Explicit isolated local *_test database required')
os.environ.update(APP_ENV='test', DB_SCHEMA_AUTO_MIGRATE='1', SECURITY_ADMIN_CAPTCHA_ENABLED='0', ORDER_VOICE_ENABLED='0')
for category in ('READ', 'VOICE', 'WRITE', 'UPLOAD', 'EXPORT', 'INVENTORY'):
    os.environ['SECURITY_LIMIT_' + category] = '10000'

import psycopg
from psycopg.sql import SQL, Identifier
with psycopg.connect(host='127.0.0.1', port=os.environ['PGPORT'], dbname='postgres',
                     user=os.environ['PGUSER'], password=os.environ['PGPASSWORD'], autocommit=True) as conn:
    if not conn.execute('SELECT 1 FROM pg_database WHERE datname=%s', (os.environ['PGDATABASE'],)).fetchone():
        conn.execute(SQL('CREATE DATABASE {}').format(Identifier(os.environ['PGDATABASE'])))

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root / 'admin-backend'))
import test_workbench as fixtures

if __name__ == '__main__':
    fixtures.seed()
    with fixtures.db.get_connection() as conn:
        for index in range(1, 29):
            is_cny = index == 28
            goods, shipping, total = ('100.20', '5.00', '105.20') if is_cny else ('0.10', '0.20', '0.30')
            order = conn.execute('''INSERT INTO orders(order_no,store_user_id,status,contact_name,phone,country,
                shipping_address,total_amount,shipping_fee,currency,exchange_rate,created_at)
                VALUES(%s,1,%s,'Totals fixture','123','CN','Fixture',%s,%s,%s,%s,%s) RETURNING id''',
                (f'SUMMARY-{index:03}', 'cancelled' if is_cny else 'paid', total, shipping,
                 'CNY' if is_cny else 'USD', '7.2' if is_cny else None,
                 datetime(2026, 10, 1, tzinfo=timezone.utc) + timedelta(minutes=index))).fetchone()
            conn.execute('''INSERT INTO order_items(order_id,product_id,product_name,sku,size_code,quantity,unit_price,total_price)
                VALUES(%s,1,'Totals fixture','GT-2026-1','M',1,%s,%s)''', (order['id'], goods, goods))
    fixtures.application.ADMIN_FRONTEND_DIST = root / 'frontend/dist'
    fixtures.application.app.run(host='127.0.0.1', port=5421, threaded=True, use_reloader=False)
