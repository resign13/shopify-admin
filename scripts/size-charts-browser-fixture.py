"""Local/CI browser fixture. Refuses the synchronized manual database."""
import os
import sys
from pathlib import Path
import psycopg
from psycopg.sql import SQL, Identifier

if os.environ.get('PGHOST') != '127.0.0.1' or not os.environ.get('PGDATABASE', '').endswith('_test'):
    raise RuntimeError('Explicit isolated local *_test database required')
# A fresh CI service contains only its base regression database. Create this
# separately named fixture before importing the pooled application connection.
with psycopg.connect(host='127.0.0.1', port=os.environ['PGPORT'], dbname='postgres',
        user=os.environ['PGUSER'], password=os.environ['PGPASSWORD'], autocommit=True) as conn:
    name = os.environ['PGDATABASE']
    if not conn.execute('SELECT 1 FROM pg_database WHERE datname=%s', (name,)).fetchone():
        conn.execute(SQL('CREATE DATABASE {} TEMPLATE template0').format(Identifier(name)))
os.environ.update(APP_ENV='test', DB_SCHEMA_AUTO_MIGRATE='1', SECURITY_ADMIN_CAPTCHA_ENABLED='0', ORDER_VOICE_ENABLED='0')
root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root / 'admin-backend'))
import test_workbench as fixtures

if __name__ == '__main__':
    fixtures.seed()
    with fixtures.db.get_connection() as conn:
        conn.execute('TRUNCATE product_size_charts,product_size_chart_audit,product_size_chart_receipts RESTART IDENTITY')
    fixtures.db.create_product({'categoryKey':'denim','productCode':'CS2211-blue','sku':'CS2211-blue',
        'slug':'chart-fixture-cs2211','familyCode':'CS2211','colorGroup':'CS2211','colorName':'Blue',
        'title':'Slim fit trousers','image':'/uploads/fixture.jpg','sizes':['28','30','32','S/28'],
        'sizePrices':[{'sizeCode':s,'price':20,'stock':10} for s in ['28','30','32','S/28']]})
    fixtures.application.app.run(host='127.0.0.1', port=int(os.environ.get('CHART_TEST_PORT','5366')), threaded=True, use_reloader=False)
