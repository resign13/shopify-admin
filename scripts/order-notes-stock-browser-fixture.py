"""Order cancellation/live-stock UI fixture; explicit local *_test database only."""
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
sys.path.insert(0,str(root/'admin-backend'))
os.environ['ORDER_VOICE_ENABLED']='0'
import test_workbench as fixtures
if __name__=='__main__':
    fixtures.seed()
    from werkzeug.security import generate_password_hash
    fixtures.db._fetch_one('UPDATE orders SET owner_admin_id=2 WHERE id=1 RETURNING id')
    fixtures.db.create_admin_user({'name':'财务验收','email':'finance@gingtto.test',
        'passwordHash':generate_password_hash('Workbench-Test-2026',method='pbkdf2:sha256:1000'),
        'role':'finance','status':'active','permissions':['orders','finance']})
    uploads=fixtures.application.media.uploads['admin'];uploads.mkdir(parents=True,exist_ok=True)
    Image.new('RGB',(160,160),'#334155').save(uploads/'fixture.jpg')
    fixtures.fixture_file('/uploads/fixture.pdf')
    with fixtures.db.get_connection() as conn:
        conn.execute("UPDATE product_size_prices SET weight_grams=350 WHERE product_id=1 AND size_code='M'")
        conn.execute("UPDATE product_size_prices SET weight_grams=380 WHERE product_id=2 AND size_code='M'")
        # A missing real size must not be recreated by the weight bulk tool.
        conn.execute("DELETE FROM product_size_prices WHERE product_id=3 AND size_code='L'")
        conn.execute("DELETE FROM product_sizes WHERE product_id=3 AND size_code='L'")
        conn.execute('UPDATE products SET stock=20 WHERE id=3')
    # Historical missing sizes belong to a closed order, so product edits remain valid.
    with fixtures.db.get_connection() as conn:
        conn.execute("UPDATE orders SET status='completed' WHERE id=2")
        conn.execute("UPDATE order_items SET size_code='' WHERE order_id=2 AND product_id=1")
        conn.execute("UPDATE order_items SET size_code='Removed-size' WHERE order_id=2 AND product_id=2")
        conn.execute("UPDATE order_items SET size_code='L' WHERE order_id=4 AND product_id=1")
    fixtures.application.app.run(host='127.0.0.1',port=5360,threaded=True,use_reloader=False)
