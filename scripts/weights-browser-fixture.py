"""Product/order weights UI fixture; explicit local *_test database only."""
import os
import sys
from pathlib import Path
if os.environ.get('PGHOST') != '127.0.0.1' or not os.environ.get('PGDATABASE', '').endswith('_test'):
    raise RuntimeError('Explicit isolated test database required')
import psycopg
from psycopg.sql import SQL, Identifier
with psycopg.connect(host='127.0.0.1',port=os.environ['PGPORT'],dbname='postgres',
                     user=os.environ['PGUSER'],password=os.environ['PGPASSWORD'],autocommit=True) as management:
    name=os.environ['PGDATABASE']
    if not management.execute('SELECT 1 FROM pg_database WHERE datname=%s',(name,)).fetchone():
        management.execute(SQL('CREATE DATABASE {}').format(Identifier(name)))
from PIL import Image
root=Path(__file__).resolve().parents[1]
uploads=root/'admin-backend/uploads';uploads.mkdir(exist_ok=True)
Image.new('RGB',(160,160),'#334155').save(uploads/'fixture.jpg')
sys.path.insert(0,str(root/'admin-backend'))
os.environ['ORDER_VOICE_ENABLED']='0'
import test_workbench as fixtures
if __name__=='__main__':
    fixtures.seed()
    with fixtures.db.get_connection() as conn:
        conn.execute("UPDATE product_size_prices SET weight_grams=350 WHERE product_id=1 AND size_code='M'")
        conn.execute("UPDATE product_size_prices SET weight_grams=380 WHERE product_id=2 AND size_code='M'")
        # A missing real size must not be recreated by the weight bulk tool.
        conn.execute("DELETE FROM product_size_prices WHERE product_id=3 AND size_code='L'")
        conn.execute("DELETE FROM product_sizes WHERE product_id=3 AND size_code='L'")
        conn.execute('UPDATE products SET stock=20 WHERE id=3')
    fixtures.application.app.run(host='127.0.0.1',port=5360,threaded=True,use_reloader=False)
