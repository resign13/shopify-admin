"""Production-safe read-only schema, provenance and customer boundary checks."""
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
import inventory_overdelivery as policy
from inventory_policy import public_inventory

INTERNAL_FIELDS=set(policy.internal(0))

def public_boundary(value):
    if isinstance(value,list):
        for child in value:public_boundary(child)
    elif isinstance(value,dict):
        if INTERNAL_FIELDS.intersection(value):raise RuntimeError('Internal overdelivery ledger exposed to customers')
        for child in value.values():public_boundary(child)

with db._connect() as conn:
    conn.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
    @contextmanager
    def read_connection():yield conn
    db.get_connection=read_connection
    columns=conn.execute("SELECT column_name,data_type,is_nullable FROM information_schema.columns WHERE table_schema='public' AND table_name='inventory_overdelivery'").fetchall()
    types={r['column_name']:(r['data_type'],r['is_nullable']) for r in columns}
    expected={'product_id':('bigint','NO'),'size_code':('character varying','NO'),
              'used':('integer','NO'),'inspection':('integer','NO'),'qualified':('integer','NO'),
              'normal_received':('bigint','YES')}
    if any(types.get(k)!=v for k,v in expected.items()):raise RuntimeError('Overdelivery ledger schema incompatible')
    checks=conn.execute("SELECT contype,convalidated FROM pg_constraint WHERE conrelid='inventory_overdelivery'::regclass").fetchall()
    if (sum(c['contype']=='c' and c['convalidated'] for c in checks)<5
        or not any(c['contype']=='p' for c in checks) or not any(c['contype']=='f' for c in checks)):
        raise RuntimeError('Overdelivery ledger constraints missing')
    rows=conn.execute('SELECT e.*,s.pending_inspection,s.pending_inbound FROM inventory_overdelivery e LEFT JOIN product_size_prices s ON s.product_id=e.product_id AND s.size_code=e.size_code').fetchall()
    totals=policy.contract_totals(conn.cursor(),list({r['product_id'] for r in rows})) if rows else {}
    for row in rows:
        if (row['pending_inspection'] is None or row['pending_inbound'] is None
            or min(row['used'],row['inspection'],row['qualified'])<0
            or row['inspection']>row['pending_inspection'] or row['qualified']>row['pending_inbound']
            or row['inspection']+row['qualified']>row['used']
            or row['used']>min(policy.MAX_QUANTITY,totals.get((row['product_id'],row['size_code']),0)*15//100)):
            raise RuntimeError('Cumulative overdelivery/source invariant failed')
    public_boundary(public_inventory(db.list_products()))
    verified=['ledger-schema','validated-constraints','cumulative-allowance','stage-provenance','public-field-boundary']
    if args.backend=='admin-backend':
        internal=db.list_products(include_contract_pending=True,include_inactive=True)
        if any(not INTERNAL_FIELDS.issubset(s) for p in internal for s in p.get('sizePrices',[])):
            raise RuntimeError('Internal inventory missing cumulative source fields')
        trigger=conn.execute("SELECT 1 FROM pg_trigger WHERE tgrelid='inventory_overdelivery'::regclass AND tgname='admin_audit' AND tgenabled='O'").fetchone()
        if not trigger:raise RuntimeError('Overdelivery audit trigger missing')
        # Importing app would run initialization/migrations: inspect release
        # metadata without executing the application in a read-only smoke check.
        source=(Path(__file__).resolve().parents[1]/args.backend/'app.py').read_text('utf-8')
        if 'INVENTORY_TEMPLATE_VERSION = "inventory-v6"' not in source:raise RuntimeError('Inventory template incompatible')
        verified+=['internal-size-fields','ledger-audit-trigger','inventory-v6']
    print(json.dumps({'readOnly':True,'checks':verified}))
