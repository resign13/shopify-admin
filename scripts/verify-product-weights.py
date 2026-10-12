"""Read-only release checks; no login, business writes or business data output."""
import argparse
from contextlib import contextmanager
import json
from pathlib import Path
import sys

parser = argparse.ArgumentParser()
parser.add_argument('backend', choices=('admin-backend', 'storefront-backend'))
args = parser.parse_args()
root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root / args.backend))
import db
import product_weights

FIELDS = {'weightGrams', 'unitWeightGrams', 'lineWeightGrams', 'knownWeightGrams',
          'totalWeightGrams', 'missingWeightQuantity', 'weightStatus', 'missingItems'}


def public_boundary(value):
    if isinstance(value, list):
        for child in value:
            public_boundary(child)
    elif isinstance(value, dict):
        if FIELDS.intersection(value):
            raise RuntimeError('Internal product weights exposed by a public/list serializer')
        for child in value.values():
            public_boundary(child)


with db._connect() as conn:
    conn.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')

    @contextmanager
    def read_connection():
        yield conn

    db.get_connection = read_connection
    column = conn.execute("SELECT data_type,is_nullable,column_default FROM information_schema.columns WHERE table_schema='public' AND table_name='product_size_prices' AND column_name='weight_grams'").fetchone()
    if not column or column['data_type'] != 'integer' or column['is_nullable'] != 'YES' or column['column_default'] is not None:
        raise RuntimeError('Optional weight schema incompatible')
    constraint = conn.execute("SELECT convalidated,pg_get_constraintdef(oid) AS definition FROM pg_constraint WHERE conrelid='product_size_prices'::regclass AND conname='product_size_prices_weight_positive' AND contype='c'").fetchone()
    if not constraint or not constraint['convalidated'] or 'weight_grams > 0' not in constraint['definition']:
        raise RuntimeError('Positive-weight constraint missing')
    if conn.execute('SELECT EXISTS(SELECT 1 FROM product_size_prices WHERE weight_grams IS NOT NULL AND weight_grams<=0) AS invalid').fetchone()['invalid']:
        raise RuntimeError('Invalid product weight present')
    public_boundary(db.list_products())
    public_boundary(db.list_orders())
    checks = ['nullable-integer-weights', 'validated-positive-constraint', 'valid-saved-weights', 'public-and-order-list-boundary']
    if args.backend == 'admin-backend':
        orders = db.list_orders(include_weight=True)
        for order in orders:
            expected = product_weights.summary(order['items'])
            if any(order.get(key) != value for key, value in expected.items()):
                raise RuntimeError('Current-weight order summary inconsistent')
            for item in order['items']:
                weight = item['unitWeightGrams']
                line = str(weight * item['quantity']) if weight is not None else None
                if item['lineWeightGrams'] != line:
                    raise RuntimeError('Current-weight order detail inconsistent')
        source = (root / args.backend / 'db.py').read_text('utf-8')
        if 'existing_weights' not in source or 'product_weights.parse(row["weightGrams"]' not in source:
            raise RuntimeError('Weight-preserving product save compatibility missing')
        checks += ['exact-current-order-weights', 'weight-preserving-product-save']
    print(json.dumps({'readOnly': True, 'checks': checks}))
