"""Read-only release check. No login, test accounts, costs or orders are created."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'admin-backend'))
import db
import module_permissions

with db._connect() as conn:
    conn.execute('SET TRANSACTION READ ONLY')
    for table in ('finance_cost_versions', 'finance_cost_history', 'finance_cost_audit',
                  'finance_cost_receipts', 'finance_settings', 'finance_style_costs', 'finance_style_cost_audit'):
        assert conn.execute('SELECT to_regclass(%s) AS name', ('public.' + table,)).fetchone()['name'], table + ' missing'
    for table in ('finance_cost_history','finance_style_costs'):
        column = conn.execute("SELECT is_nullable FROM information_schema.columns WHERE table_schema='public' AND table_name=%s AND column_name='cost_cny'",(table,)).fetchone()
        assert column and column['is_nullable'] == 'YES', 'Cost clearing requires nullable costs: '+table
    effective = conn.execute("SELECT is_nullable,data_type FROM information_schema.columns WHERE table_schema='public' AND table_name='finance_style_cost_audit' AND column_name='effective_at'").fetchone()
    assert effective and effective['is_nullable']=='NO' and effective['data_type']=='timestamp with time zone', 'Style cost timeline missing'
    assert conn.execute("SELECT to_regclass('public.finance_style_cost_audit_timeline') AS name").fetchone()['name'], 'Timeline lookup index missing'
    assert conn.execute("SELECT to_regclass('public.finance_style_cost_audit_initial') AS name").fetchone()['name'], 'Unique initial cost index missing'
    assert conn.execute("SELECT count(*) AS n FROM finance_style_cost_audit WHERE is_initial AND cost_cny IS NULL").fetchone()['n']==0, 'An initial cost must be an explicit amount'
    # Existing deployments validate role names in application code; they do not
    # require a database CHECK on this compatibility column.
    role_column = conn.execute("SELECT character_maximum_length FROM information_schema.columns WHERE table_schema='public' AND table_name='admin_users' AND column_name='role'").fetchone()
    assert role_column and role_column['character_maximum_length'] >= len('finance'), 'Finance role column missing'
    assert conn.execute('SELECT count(*) AS n FROM finance_settings').fetchone()['n'] <= 1, 'Exchange rate must be global'

for role in ('sales', 'warehouse', 'customer'):
    assert not module_permissions.allows_request({'role': role, 'permissions': None}, '/api/admin/finance/costs', 'GET')
assert module_permissions.allows_request({'role': 'finance', 'permissions': None}, '/api/admin/finance/costs', 'GET')
assert not module_permissions.allows_request({'role': 'finance', 'permissions': None}, '/api/admin/orders', 'POST')
print('Read-only style cost schema, shared settings and permission checks passed.')
