"""Read-only release checks; never create orders, log in, or print customer data."""
import argparse
from datetime import datetime, timezone
from pathlib import Path
import sys
parser=argparse.ArgumentParser()
parser.add_argument('backend',choices=('admin-backend','storefront-backend'))
args=parser.parse_args()
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/args.backend))
import db
import order_numbering
with db._connect() as conn:
    conn.execute('SET TRANSACTION READ ONLY')
    column=conn.execute("SELECT character_maximum_length FROM information_schema.columns WHERE table_schema='public' AND table_name='orders' AND column_name='order_no'").fetchone()
    assert column and (column['character_maximum_length'] is None or column['character_maximum_length']>=255), 'Order number column too short'
    constraint=conn.execute("SELECT 1 FROM pg_constraint WHERE conrelid='orders'::regclass AND contype='u' AND pg_get_constraintdef(oid)='UNIQUE (order_no)'").fetchone()
    assert constraint, 'Unique order number constraint missing'
    if args.backend=='admin-backend':
        assert conn.execute("SELECT to_regclass('public.admin_order_drafts') AS table_name").fetchone()['table_name'], 'Order draft schema missing'
assert order_numbering.make_order_number(188,datetime(2026,10,12,16,tzinfo=timezone.utc),'A  张三')=='PO1013-A  张三-000188'
print('Read-only order numbering/schema compatibility checks passed.')
