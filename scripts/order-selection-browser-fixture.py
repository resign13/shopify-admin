"""Order picker regression fixture. Never seed the manual synchronized database."""
import os
import sys
from pathlib import Path

if os.environ.get('PGHOST') != '127.0.0.1' or not os.environ.get('PGDATABASE', '').endswith('_test'):
    raise RuntimeError('Explicit isolated local *_test database required')
os.environ.update(APP_ENV='test', SECURITY_ADMIN_CAPTCHA_ENABLED='0', ORDER_VOICE_ENABLED='0')
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
    fixtures.fixture_file('/uploads/fixture.pdf')
    with fixtures.db.get_connection() as conn:
        conn.execute("UPDATE product_size_prices SET weight_grams=350 WHERE product_id=1 AND size_code='M'")
        conn.execute("UPDATE product_size_prices SET weight_grams=380 WHERE product_id=2 AND size_code='M'")
        conn.execute("DELETE FROM product_size_prices WHERE product_id=3 AND size_code='L'")
        conn.execute("DELETE FROM product_sizes WHERE product_id=3 AND size_code='L'")
        conn.execute('UPDATE products SET stock=20 WHERE id=3')
    for index in range(1, 29):
        code = f'PICK-{index:02}'
        sizes = ['M', 'Tall XL'] if index % 2 else ['XS', 'M']
        fixtures.db.create_product({'categoryKey': 'outerwear', 'productCode': code, 'sku': code,
            'slug': code.lower(), 'familyCode': code, 'colorGroup': code, 'colorName': 'Black',
            'title': 'Picker fixture', 'image': '/uploads/fixture.jpg', 'sizes': sizes,
            'sizePrices': [{'sizeCode': size, 'price': 7.5, 'stock': 0} for size in sizes]})
    standards = [
        ('DEMO-NOSIZE', ['M']),
        ('DEMO-MANY', ['XXS', 'XS', 'S', 'M', 'L', 'XL', 'XXL', 'XXXL', '4XL', '5XL', '6XL', '7XL', '8XL', '9XL', 'Tall XL', 'CUSTOM-SIZE-EXTRA-LONG-LABEL']),
        ('DEMO-MIX600-黑', ['S/28', 'M/30', 'L/32']),
        ('DEMO-OS500-灰', ['均码']),
        ('DEMO-SH400-黑', ['38', '39', '40', '41', '42']),
        ('DEMO-KD300-白', ['110', '120', '130', '140']),
        ('DEMO-JN200-蓝', ['36', '34', '32', '30', '28']),
        ('DEMO-TS100-黑', ['XS', 'S', 'M', 'L', 'XL']),
    ]
    for index, (code, sizes) in enumerate(standards):
        product = fixtures.db.create_product({'categoryKey': 'outerwear', 'productCode': code, 'sku': code,
            'slug': f'size-standards-{index}', 'familyCode': code, 'colorGroup': code, 'colorName': 'Black',
            'title': 'Size standards fixture', 'image': '/uploads/fixture.jpg', 'sizes': sizes,
            'sizePrices': [{'sizeCode': size, 'price': 9, 'stock': 0} for size in sizes]})
        if code == 'DEMO-NOSIZE':
            with fixtures.db.get_connection() as conn:
                conn.execute('DELETE FROM product_size_prices WHERE product_id=%s', (product['id'],))
                conn.execute('DELETE FROM product_sizes WHERE product_id=%s', (product['id'],))
    fixtures.application.app.run(host='127.0.0.1', port=5360, threaded=True, use_reloader=False)
