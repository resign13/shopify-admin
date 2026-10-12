"""Read-only post-release catalog checks; no app startup, sessions or business writes."""
import argparse
from contextlib import contextmanager
import json
from pathlib import Path
import sys

parser = argparse.ArgumentParser()
parser.add_argument('backend', choices=('admin-backend', 'storefront-backend'))
args = parser.parse_args()
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / args.backend))
import db
import inventory_policy
import style_catalog

with db._connect() as conn:
    conn.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')

    @contextmanager
    def read_connection():
        yield conn

    db.get_connection = read_connection
    column = conn.execute("SELECT data_type FROM information_schema.columns WHERE table_schema='public' AND table_name='products' AND column_name='style_code'").fetchone()
    if not column or column['data_type'] != 'character varying':
        raise RuntimeError('Style identity schema missing')
    row = conn.execute('SELECT * FROM presale_configs WHERE id=1').fetchone()
    if not row or conn.execute('SELECT COUNT(*) AS n FROM presale_configs').fetchone()['n'] != 1:
        raise RuntimeError('Presale configuration singleton missing')
    settings = style_catalog.config(row)
    codes = settings['styleCodes']
    if (settings['sortMode'] not in {'automatic','manual'} or settings['version'] < 0
        or len(codes) != len(set(codes)) or any(not isinstance(code,str) or not code.strip() or code != code.strip() for code in codes)):
        raise RuntimeError('Presale configuration invalid')
    code = style_catalog.style_sql('p')
    expected = conn.execute(f"SELECT {code} AS code,MIN(p.created_at) AS first_date,MIN(p.id) AS first_id FROM products p GROUP BY {code}").fetchall()
    dates = {r['code']:(db._iso(r['first_date']),int(r['first_id'])) for r in expected}
    checks = ['style-schema','presale-singleton','valid-versioned-config']
    if args.backend == 'admin-backend':
        import presale
        import module_permissions
        groups = presale.catalog()
        if set(group['styleCode'] for group in groups) != set(dates):
            raise RuntimeError('Admin style picker incomplete')
        if 'presale' in module_permissions.effective({'role':'sales','permissions':None}):
            raise RuntimeError('Presale permission implicitly granted to sales')
        if 'presale' in module_permissions.effective({'role':'warehouse','permissions':['presale']}):
            raise RuntimeError('Warehouse presale permission exposed')
        checks += ['complete-style-picker','explicit-presale-permission']
    else:
        products = db.list_products()
        groups = style_catalog.group_variants(products)
        balances = {int(r['id']):int(r['stock']) for r in conn.execute(f"SELECT p.id,{inventory_policy.available_sql('p')} AS stock FROM products p WHERE p.is_active=TRUE").fetchall()}
        for product in products:
            if inventory_policy.public_inventory(product)['stock'] != balances[product['id']]:
                raise RuntimeError('Catalog available stock differs from per-size positive balances')
        selected = style_catalog.presale_groups(groups, settings)
        if any(group['styleCode'] not in codes for group in selected):
            raise RuntimeError('Presale selection mismatch')
        if settings['sortMode'] == 'manual' and [codes.index(group['styleCode']) for group in selected] != sorted(codes.index(group['styleCode']) for group in selected):
            raise RuntimeError('Presale manual order mismatch')
        checks += ['public-available-stock','presale-selection-order']
    for group in groups:
        if (group['firstListedAt'],int(group['firstProductId'])) != dates[group['styleCode']]:
            raise RuntimeError('First listing identity mismatch')
    checks.append('first-listing-including-inactive-colors')
    print(json.dumps({'checks':checks,'styleCount':len(groups),'presaleCount':len(codes),'readOnly':True}))
