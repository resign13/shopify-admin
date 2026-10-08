"""Read-only compatibility checks. Never initialize, seed, create sessions or write."""
import argparse
from contextlib import contextmanager
import json
from pathlib import Path
import sys

parser=argparse.ArgumentParser()
parser.add_argument('backend',choices=('admin-backend','storefront-backend'))
args=parser.parse_args()
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/args.backend))
import db

def public_boundary(value):
    if isinstance(value,list):
        for child in value:public_boundary(child)
    elif isinstance(value,dict):
        if 'defectivePending' in value:raise RuntimeError('Internal defect quantity exposed to customers')
        for child in value.values():public_boundary(child)

with db._connect() as conn:
    conn.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
    @contextmanager
    def read_connection():yield conn
    db.get_connection=read_connection
    column=conn.execute("SELECT data_type,is_nullable,column_default FROM information_schema.columns WHERE table_schema='public' AND table_name='product_size_prices' AND column_name='defective_pending'").fetchone()
    if not column or (column['data_type'],column['is_nullable'],column['column_default'])!=('integer','NO','0'):
        raise RuntimeError('Defect column/default incompatible')
    constraints=conn.execute("SELECT COUNT(*) AS n FROM pg_constraint WHERE conrelid='product_size_prices'::regclass AND conname IN ('product_size_prices_defective_pending_check','product_size_prices_defective_reservation_check') AND convalidated").fetchone()['n']
    if constraints!=2:raise RuntimeError('Defect nonnegative/reservation constraints missing')
    invalid=conn.execute('SELECT COUNT(*) AS n FROM product_size_prices WHERE defective_pending<0 OR defective_pending>pending_inspection').fetchone()['n']
    if invalid:raise RuntimeError('Defect reservation invariant failed')
    public_boundary(db.list_products())
    checks=['defective-column','defective-reservation','public-field-boundary']
    if args.backend=='admin-backend':
        import workbench
        internal=db.list_products(include_contract_pending=True,include_inactive=True)
        if any('defectivePending' not in s for p in internal for s in p.get('sizePrices',[])):
            raise RuntimeError('Internal inventory missing defect quantity')
        page=workbench.products_page({'page':1,'pageSize':25,'sort':'category'},pending=True)
        if 'defectivePending' not in page['summary']:raise RuntimeError('Inventory summary missing defect quantity')
        checks+=['internal-size-quantity','inventory-summary']
    print(json.dumps({'readOnly':True,'checks':checks}))
